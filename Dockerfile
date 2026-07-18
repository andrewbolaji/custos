FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install CPU-only torch FIRST. The --extra-index-url approach lets
# pip resolve torch from the CPU index while resolving everything
# else from PyPI. This avoids the CUDA build (~7GB savings).
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    . \
    && pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 \
       nvidia-cuda-nvrtc-cu12 nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 \
       nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-cusolver-cu12 \
       nvidia-cusparse-cu12 nvidia-nccl2 nvidia-nvtx-cu12 triton 2>/dev/null; true

# Vendor the embedder model at build time.
ENV HF_HOME=/build/models
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

RUN groupadd -r custos && useradd -r -g custos -d /app custos

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/models /app/models
COPY corpus/output /app/corpus/output

RUN chown -R custos:custos /app

ENV HF_HOME=/app/models
ENV TRANSFORMERS_OFFLINE=1
ENV HF_DATASETS_OFFLINE=1
ENV CUSTOS_CORPUS_DIR=/app/corpus/output

USER custos
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["python", "-m", "uvicorn", "custos.api:app", "--host", "0.0.0.0", "--port", "8000"]
