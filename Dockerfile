FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Model caches — mounted as named volumes by docker-compose so the
    # sentence-transformers and rembg downloads survive container rebuilds.
    HF_HOME=/root/.cache/huggingface \
    U2NET_HOME=/root/.u2net

# WORKDIR must be /app: main.py mounts "src/web/static" and token_manager.py
# resolves "./data" — both are CWD-relative.
WORKDIR /app

# CPU-only torch. sentence-transformers is imported at module load by
# src/domain/validators.py, so torch is unavoidable. On x86_64 this index keeps
# the ~2.5GB CUDA wheels out; on arm64 it has no wheel and pip falls back to
# PyPI, whose aarch64 build is already CPU-only.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch

# Dependency layer, cached independently of application source. The editable
# install only needs src/ to exist at build time; compose bind-mounts the real
# code over it at runtime.
COPY pyproject.toml ./
RUN mkdir -p src && touch src/__init__.py && pip install -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
