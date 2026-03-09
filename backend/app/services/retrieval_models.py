from __future__ import annotations

import threading
from collections.abc import Sequence

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

_embedding_model_lock = threading.Lock()
_embedding_model_loaded = False
_embedding_model = None

_reranker_model_lock = threading.Lock()
_reranker_model_loaded = False
_reranker_model = None


def _load_embedding_model():
    global _embedding_model_loaded, _embedding_model
    if _embedding_model_loaded:
        return _embedding_model

    with _embedding_model_lock:
        if _embedding_model_loaded:
            return _embedding_model
        if not settings.retrieval_embedding_model_enabled:
            _embedding_model_loaded = True
            return None
        try:
            from sentence_transformers import SentenceTransformer

            _embedding_model = SentenceTransformer(
                settings.retrieval_embedding_model_name,
                device=settings.retrieval_model_device,
                trust_remote_code=False,
            )
            logger.info(
                "retrieval_embedding_model_loaded",
                model_name=settings.retrieval_embedding_model_name,
                device=settings.retrieval_model_device,
            )
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            logger.warning(
                "retrieval_embedding_model_unavailable",
                model_name=settings.retrieval_embedding_model_name,
                error=str(exc),
            )
            _embedding_model = None
        _embedding_model_loaded = True
        return _embedding_model


def _load_reranker_model():
    global _reranker_model_loaded, _reranker_model
    if _reranker_model_loaded:
        return _reranker_model

    with _reranker_model_lock:
        if _reranker_model_loaded:
            return _reranker_model
        if not settings.retrieval_reranker_enabled:
            _reranker_model_loaded = True
            return None
        try:
            from sentence_transformers import CrossEncoder

            _reranker_model = CrossEncoder(
                settings.retrieval_reranker_model_name,
                device=settings.retrieval_model_device,
                trust_remote_code=False,
            )
            logger.info(
                "retrieval_reranker_model_loaded",
                model_name=settings.retrieval_reranker_model_name,
                device=settings.retrieval_model_device,
            )
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            logger.warning(
                "retrieval_reranker_model_unavailable",
                model_name=settings.retrieval_reranker_model_name,
                error=str(exc),
            )
            _reranker_model = None
        _reranker_model_loaded = True
        return _reranker_model


def embed_texts(texts: Sequence[str], *, expected_dimension: int) -> list[list[float]] | None:
    if not texts:
        return []

    model = _load_embedding_model()
    if model is None:
        return None

    try:
        vectors = model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        dense_vectors = [[float(v) for v in vector] for vector in vectors]
        if any(len(vector) != expected_dimension for vector in dense_vectors):
            actual_dims = sorted({len(vector) for vector in dense_vectors})
            raise ValueError(
                f"Embedding dimension mismatch: expected {expected_dimension}, got {actual_dims} "
                f"from {settings.retrieval_embedding_model_name}"
            )
        return dense_vectors
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        logger.warning("retrieval_embedding_failed", error=str(exc))
        return None


def embed_query(query: str, *, expected_dimension: int) -> list[float] | None:
    vectors = embed_texts([query], expected_dimension=expected_dimension)
    if not vectors:
        return None
    return vectors[0]


def rerank(query: str, candidates: Sequence[str]) -> list[float] | None:
    if not candidates:
        return []

    model = _load_reranker_model()
    if model is None:
        return None

    try:
        pairs = [(query, candidate) for candidate in candidates]
        scores = model.predict(pairs, show_progress_bar=False)
        return [float(score) for score in scores]
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        logger.warning("retrieval_reranker_failed", error=str(exc))
        return None
