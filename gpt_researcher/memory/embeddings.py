"""Embedding provider management for GPT Researcher.

This build is pinned to a single embedding backend: Alibaba DashScope's
``text-embedding-v3``, consumed through its **OpenAI-compatible endpoint**
(``/compatible-mode/v1``) so the LangChain OpenAI client can do the talking.
The upstream provider matrix — 20+ backends behind a ``match`` in
``Memory.__init__`` — has been dropped.

Provider and model are set by ``EMBEDDING`` (``"dashscope:<model>"``) in
``config/variables/default.py``; the DashScope-specific quirks below are
defaulted in code so callers don't have to rediscover them.
"""

import os
from typing import Any

# Kept for cost estimation only: `context/compression.py` passes this to
# `estimate_embedding_cost()` as a tiktoken tokenizer proxy. tiktoken does not
# know DashScope model names, so it falls back to the default encoding anyway;
# the USD figure it produces is a rough gauge, not a real price.
OPENAI_EMBEDDING_MODEL = os.environ.get(
    "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
)

_SUPPORTED_PROVIDERS = {"dashscope"}

_DASHSCOPE_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class Memory:
    """Manages embedding generation for document similarity and retrieval.

    Example:
        ```python
        memory = Memory("dashscope", "text-embedding-v3")
        embeddings = memory.get_embeddings()
        ```
    """

    def __init__(self, embedding_provider: str, model: str, **embedding_kwargs: Any):
        """Initialize the Memory with the DashScope embedding backend.

        Args:
            embedding_provider: Must be ``"dashscope"``.
            model: DashScope model name, e.g. ``text-embedding-v3``.
            **embedding_kwargs: Forwarded to ``OpenAIEmbeddings``. Any key set
                here wins over the defaults applied below.

        Raises:
            ValueError: If the provider is not DashScope, or if no DashScope
                API key can be found.
        """
        if embedding_provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported embedding provider {embedding_provider!r}. "
                f"Supported providers: {', '.join(sorted(_SUPPORTED_PROVIDERS))}"
            )

        # Fail here rather than letting OpenAIEmbeddings silently pick up
        # OPENAI_API_KEY — that holds the chat model's key, which DashScope
        # rejects with an opaque 401.
        if not embedding_kwargs.get("openai_api_key"):
            api_key = os.environ.get("DASHSCOPE_API_KEY")
            if not api_key:
                raise ValueError(
                    "No DashScope API key found. Set DASHSCOPE_API_KEY, or pass "
                    "openai_api_key in EMBEDDING_KWARGS."
                )
            embedding_kwargs["openai_api_key"] = api_key

        embedding_kwargs.setdefault(
            "openai_api_base",
            os.environ.get("DASHSCOPE_BASE_URL", _DASHSCOPE_COMPAT_BASE_URL),
        )
        # text-embedding-v3 is not a tiktoken model, so the client-side context
        # length check raises before the request is ever sent.
        embedding_kwargs.setdefault("check_embedding_ctx_length", False)
        # DashScope rejects embedding batches larger than 10 inputs.
        embedding_kwargs.setdefault("chunk_size", 10)

        from langchain_openai import OpenAIEmbeddings

        self._embeddings = OpenAIEmbeddings(model=model, **embedding_kwargs)

    def get_embeddings(self):
        """Get the configured embeddings instance.

        Returns:
            The LangChain embeddings instance configured for this project.
        """
        return self._embeddings