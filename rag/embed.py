"""Text embedders. The index needs only `name` and `embed`; tests inject a stub.

`SentenceTransformerEmbedder` imports sentence-transformers (and so torch) on
first use, so importing this module, the index or the tools stays cheap and
offline. The first real use downloads the model from Hugging Face once.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

Vectors = npt.NDArray[np.float32]


class Embedder(Protocol):
    @property
    def name(self) -> str:
        """Stored in the index; a different name means the vectors must be rebuilt."""
        ...

    def embed(self, texts: list[str]) -> Vectors:
        """One L2-normalised float32 row per text."""
        ...


class SentenceTransformerEmbedder:
    def __init__(self, model: str) -> None:
        self._model_name = model
        self._model: Any = None

    @property
    def name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> Vectors:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device="cpu")
        vectors = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vectors, dtype=np.float32)
