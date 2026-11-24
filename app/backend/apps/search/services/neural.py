"""Gömme (bge-m3) ve yeniden sıralama (bge-reranker-v2-m3) modelleri.

Modeller açılışta değil ilk kullanımda yüklenir; süreç başına tek kopya, kilitle korunur.
Ekran kartı yoksa CPU'ya düşülür (yavaş: 50 aday ~11-19 sn). Testler bu modülün `encode_texts` ve
`score_pairs` fonksiyonlarını servis sınırında sahteler; gerçek model testte yüklenmez.
"""

import logging
import threading

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)

_load_lock = threading.Lock()
# Tek ekran kartında iki iş parçacığı aynı anda tahmin yürütmesin.
_run_lock = threading.Lock()
_embedder = None
_reranker = None


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_embedder():
    from sentence_transformers import SentenceTransformer

    device = _device()
    # Model /models önbelleğinden gelir; ağdan indirme denenmez.
    model = SentenceTransformer(
        settings.SEARCH["embed_model"], device=device, local_files_only=True
    )
    model.max_seq_length = settings.SEARCH["embed_max_seq_length"]
    if device == "cuda":
        model.half()
    else:
        logger.warning("Ekran kartı yok: gömme modeli CPU'da çalışıyor.")
    return model


def _load_reranker():
    import torch
    from sentence_transformers import CrossEncoder

    device = _device()
    kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if device == "cuda" else {}
    model = CrossEncoder(
        settings.SEARCH["rerank_model"],
        device=device,
        max_length=settings.SEARCH["rerank_max_length"],
        local_files_only=True,
        **kwargs,
    )
    if device != "cuda":
        logger.warning("Ekran kartı yok: yeniden sıralama modeli CPU'da çalışıyor.")
    return model


def get_embedder():
    global _embedder
    with _load_lock:
        if _embedder is None:
            _embedder = _load_embedder()
        return _embedder


def get_reranker():
    global _reranker
    with _load_lock:
        if _reranker is None:
            _reranker = _load_reranker()
        return _reranker


def encode_texts(texts: list[str]) -> np.ndarray:
    """Metinleri normalize, float16 vektörlere çevirir: (n, 1024)."""
    model = get_embedder()
    with _run_lock:
        vectors = model.encode(
            list(texts), batch_size=16, normalize_embeddings=True, convert_to_numpy=True
        )
    return vectors.astype(np.float16)


def score_pairs(pairs: list[tuple[str, str]]) -> list[float]:
    """(sorgu, belge) çiftlerinin yeniden sıralama puanları."""
    if not pairs:
        return []
    model = get_reranker()
    with _run_lock:
        scores = model.predict(
            pairs, batch_size=settings.SEARCH["rerank_batch_size"], show_progress_bar=False
        )
    return [float(score) for score in scores]
