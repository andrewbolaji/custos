FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install with --extra-index-url so pip resolves torch from the
# CPU index. Then remove any CUDA packages that may have landed.
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    . \
    && pip uninstall -y \
       nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 \
       nvidia-cuda-nvrtc-cu12 nvidia-cuda-runtime-cu12 \
       nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
       nvidia-cusolver-cu12 nvidia-cusparse-cu12 \
       nvidia-nccl-cu12 nvidia-nvtx-cu12 triton 2>/dev/null || true

# BUILD-TIME ASSERTION: fail the build if a CUDA torch landed.
# This protects against silent regression from pip resolution
# changes, dependency bumps, or index hiccups.
RUN python -c "\
import torch; \
cuda = torch.version.cuda; \
ver = torch.__version__; \
assert cuda is None, f'CUDA torch installed (cuda={cuda}). Use CPU-only index.'; \
assert 'cu' not in ver, f'CUDA tag in version ({ver}). Use CPU-only index.'; \
print(f'OK: torch {ver}, cuda={cuda}')"

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
