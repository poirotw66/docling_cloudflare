FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY container/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

RUN python - <<'PY'
from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import RapidOcrOptions, ThreadedPdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline

pdf_path = Path('/tmp/docling-warmup.pdf')
pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n4 0 obj<< /Length 44 >>stream\nBT /F1 18 Tf 36 100 Td (Docling warmup) Tj ET\nendstream\nendobj\n5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000241 00000 n \n0000000335 00000 n \ntrailer<< /Size 6 /Root 1 0 R >>\nstartxref\n405\n%%EOF\n")

pipeline_options = ThreadedPdfPipelineOptions(
    accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=2)
)
pipeline_options.ocr_options = RapidOcrOptions(backend='torch')

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_cls=ThreadedStandardPdfPipeline,
            pipeline_options=pipeline_options,
        )
    }
)

converter.convert(str(pdf_path))
pdf_path.unlink()
PY

COPY container/app /app/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]