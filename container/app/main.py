from __future__ import annotations

import base64
import io
import os
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import RapidOcrOptions, ThreadedPdfPipelineOptions
from docling.document_converter import DocumentConverter
from docling.document_converter import PdfFormatOption
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline
from docling_core.types.doc.base import ImageRefMode
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.app_shell import render_app_html


app = FastAPI(
    title="Docling API",
    version="1.0.0",
    description="Convert PDFs to Markdown using Docling."
)


def get_allowed_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOW_ORIGIN", "*")
    origins = [value.strip() for value in configured.split(",") if value.strip()]
    return origins or ["*"]


def get_api_keys() -> set[str]:
    configured = os.getenv("API_KEYS", "")
    return {value.strip() for value in configured.split(",") if value.strip()}


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    return int(value)


def build_pipeline_options() -> ThreadedPdfPipelineOptions:
    use_gpu = env_flag("DOCLING_GPU_ENABLED", default=False)

    pipeline_options = ThreadedPdfPipelineOptions(
        accelerator_options=AcceleratorOptions(
            device=AcceleratorDevice.CUDA if use_gpu else AcceleratorDevice.CPU,
            num_threads=get_int_env("DOCLING_NUM_THREADS", 8),
        ),
        ocr_batch_size=get_int_env("DOCLING_OCR_BATCH_SIZE", 8),
        layout_batch_size=get_int_env("DOCLING_LAYOUT_BATCH_SIZE", 32),
        table_batch_size=get_int_env("DOCLING_TABLE_BATCH_SIZE", 4),
        generate_picture_images=env_flag("DOCLING_GENERATE_PICTURE_IMAGES", default=True),
    )

    if use_gpu:
        pipeline_options.ocr_options = RapidOcrOptions(backend="torch")

    return pipeline_options


def build_converter() -> DocumentConverter:
    pipeline_options = build_pipeline_options()

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=ThreadedStandardPdfPipeline,
                pipeline_options=pipeline_options,
            )
        }
    )


def resolve_source_path(source: str) -> str:
    host_input_prefix = os.getenv("HOST_INPUT_PREFIX", "").rstrip("/")
    container_input_dir = os.getenv("CONTAINER_INPUT_DIR", "").rstrip("/")

    if host_input_prefix and container_input_dir and source.startswith(host_input_prefix + "/"):
        relative_path = source[len(host_input_prefix):].lstrip("/")
        return f"{container_input_dir}/{relative_path}"

    return source


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"]
)


@lru_cache(maxsize=1)
def get_converter() -> DocumentConverter:
    return build_converter()


def build_markdown_filename(filename: str) -> str:
    source_path = Path(filename)
    stem = source_path.stem or "document"
    return f"{stem}.md"


def build_zip_filename(filename: str) -> str:
    source_path = Path(filename)
    stem = source_path.stem or "document"
    return f"{stem}.zip"


def parse_response_format(value: str | None) -> Literal["json", "zip"]:
    normalized = (value or "json").strip().lower()

    if normalized in {"json", "inline"}:
        return "json"

    if normalized in {"zip", "file", "download", "attachment"}:
        return "zip"

    raise HTTPException(
        status_code=400,
        detail="response_format must be one of: json, zip"
    )


def parse_image_mode(value: str | None, default_mode: ImageRefMode) -> ImageRefMode:
    normalized = (value or "").strip().lower()

    if not normalized:
        return default_mode

    if normalized in {"placeholder", "text-only"}:
        return ImageRefMode.PLACEHOLDER

    if normalized in {"embedded", "inline", "base64"}:
        return ImageRefMode.EMBEDDED

    raise HTTPException(
        status_code=400,
        detail="image_mode must be one of: placeholder, embedded"
    )


def convert_document(source: str):
    return get_converter().convert(source).document


def export_markdown(document, image_mode: ImageRefMode) -> str:
    return document.export_to_markdown(image_mode=image_mode)


def decode_data_uri_image(data_uri: str) -> tuple[str, bytes]:
    header, encoded = data_uri.split(",", 1)
    mime_type = header.split(";", 1)[0].split(":", 1)[1]
    return mime_type, base64.b64decode(encoded)


def convert_image_to_jpg(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        converted = image.convert("RGB")
        output = io.BytesIO()
        converted.save(output, format="JPEG", quality=90)
        return output.getvalue()


def build_zip_package(document, filename: str) -> tuple[str, bytes]:
    markdown = export_markdown(document, image_mode=ImageRefMode.EMBEDDED)
    image_entries: list[tuple[str, bytes]] = []

    for index, picture in enumerate(getattr(document, "pictures", []), start=1):
        image_ref = getattr(picture, "image", None)

        if not image_ref or not getattr(image_ref, "uri", None):
            continue

        image_uri = str(image_ref.uri)

        if not image_uri.startswith("data:image/"):
            continue

        _, raw_bytes = decode_data_uri_image(image_uri)
        image_filename = f"images/image-{index:03d}.jpg"
        jpg_bytes = convert_image_to_jpg(raw_bytes)
        image_entries.append((image_filename, jpg_bytes))
        markdown = markdown.replace(image_uri, image_filename)

    zip_buffer = io.BytesIO()
    markdown_filename = build_markdown_filename(filename)

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(markdown_filename, markdown)

        for image_filename, image_bytes in image_entries:
            archive.writestr(image_filename, image_bytes)

    return build_zip_filename(filename), zip_buffer.getvalue()


async def save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "upload.pdf").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)

        return handle.name


def require_api_key(request: Request) -> None:
    configured_keys = get_api_keys()

    if not configured_keys:
        return

    auth_header = request.headers.get("authorization", "")
    bearer_token = ""

    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[len("Bearer "):].strip()

    api_key_header = request.headers.get("x-api-key", "").strip()
    token = bearer_token or api_key_header

    if token not in configured_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return render_app_html(auth_enabled=bool(get_api_keys()))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/convert")
async def convert(
    request: Request,
    file: UploadFile | None = File(default=None),
    source_url: str | None = Form(default=None),
    response_format: str | None = Form(default=None),
    image_mode: str | None = Form(default=None)
) -> Response:
    require_api_key(request)

    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        payload = await request.json()
        source_url = payload.get("source_url")
        response_format = payload.get("response_format")
        image_mode = payload.get("image_mode")

    output_format = parse_response_format(
        response_format or request.query_params.get("response_format")
    )
    default_image_mode = ImageRefMode.EMBEDDED if output_format == "json" else ImageRefMode.EMBEDDED
    resolved_image_mode = parse_image_mode(
        image_mode or request.query_params.get("image_mode"),
        default_mode=default_image_mode,
    )

    if not file and not source_url:
        raise HTTPException(
            status_code=400,
            detail="Provide a PDF file via multipart/form-data or source_url via JSON."
        )

    temp_path: str | None = None

    try:
        if file:
            temp_path = await save_upload(file)
            source = temp_path
            filename = file.filename or os.path.basename(temp_path)
        else:
            source = resolve_source_path(source_url)
            filename = Path(source_url).name if source_url else "remote.pdf"

        document = convert_document(source)

        if output_format == "zip":
            zip_filename, zip_bytes = build_zip_package(document, filename)
            headers = {
                "Content-Disposition": f'attachment; filename="{zip_filename}"'
            }
            return Response(
                content=zip_bytes,
                media_type="application/zip",
                headers=headers,
            )

        markdown = export_markdown(document, image_mode=resolved_image_mode)

        return JSONResponse(
            content={
                "filename": filename,
                "markdown": markdown,
            }
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
