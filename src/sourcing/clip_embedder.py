"""
Phase 4 — CLIP Image Embedder (Layer C)

Uses sentence-transformers' CLIP implementation (already a project dependency)
to produce 512-dimensional L2-normalized image embeddings.

Model: clip-ViT-B/32 — ~150MB download on first use, cached by HuggingFace.
Subsequent calls are fast (~100ms on CPU after model is loaded).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import structlog

_log = structlog.get_logger(__name__)

# Lazy singleton — loaded on first embed call
_model = None
_MODEL_NAME = "clip-ViT-B-32"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _log.info("clip_model_loading", model=_MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        _log.info("clip_model_loaded", model=_MODEL_NAME)
    return _model


class ClipEmbedder:
    """
    Wrapper around sentence-transformers CLIP for image embeddings.

    Produces L2-normalized 512-dim float32 vectors.
    Sentence-transformers handles model caching automatically.
    """

    MODEL_NAME = _MODEL_NAME

    def embed_image(self, image_path: str | Path) -> np.ndarray:
        """Embed a local image file. Returns L2-normalized 512-dim float32 array."""
        from PIL import Image as PILImage

        model = _get_model()
        img = PILImage.open(image_path).convert("RGB")
        embedding = model.encode(img, convert_to_numpy=True, normalize_embeddings=True)
        return embedding.astype(np.float32)

    def embed_image_url(self, url: str) -> np.ndarray:
        """Download and embed an image URL. Returns L2-normalized float32 array."""
        import httpx
        from io import BytesIO
        from PIL import Image as PILImage

        model = _get_model()
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()

        img = PILImage.open(BytesIO(resp.content)).convert("RGB")
        embedding = model.encode(img, convert_to_numpy=True, normalize_embeddings=True)
        return embedding.astype(np.float32)

    @staticmethod
    def image_hash(image_path: str | Path) -> str:
        """SHA-256 hash of image bytes — used as cache key."""
        with open(image_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Dot product of two L2-normalized vectors = cosine similarity."""
        return float(np.dot(a, b))
