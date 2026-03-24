from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import RapidOcrOptions, ThreadedPdfPipelineOptions
from docling.document_converter import DocumentConverter
from docling.document_converter import PdfFormatOption
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware


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


def build_converter() -> DocumentConverter:
    if not env_flag("DOCLING_GPU_ENABLED", default=False):
        return DocumentConverter()

    pipeline_options = ThreadedPdfPipelineOptions(
        accelerator_options=AcceleratorOptions(
            device=AcceleratorDevice.CUDA,
            num_threads=get_int_env("DOCLING_NUM_THREADS", 8),
        ),
        ocr_batch_size=get_int_env("DOCLING_OCR_BATCH_SIZE", 8),
        layout_batch_size=get_int_env("DOCLING_LAYOUT_BATCH_SIZE", 32),
        table_batch_size=get_int_env("DOCLING_TABLE_BATCH_SIZE", 4),
    )
    pipeline_options.ocr_options = RapidOcrOptions(backend="torch")

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


def convert_source(source: str) -> str:
    result = get_converter().convert(source)
    return result.document.export_to_markdown()


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


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "docling-container",
        "health": "/health",
        "convert": "/v1/convert"
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/convert")
async def convert(
    request: Request,
    file: UploadFile | None = File(default=None),
    source_url: str | None = Form(default=None)
) -> dict[str, str]:
    require_api_key(request)

    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        payload = await request.json()
        source_url = payload.get("source_url")

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

        markdown = convert_source(source)

        return {
            "filename": filename,
            "markdown": markdown
        }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
