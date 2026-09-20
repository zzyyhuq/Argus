"""Argus 的 embedding 服务商管理。

本分支只固定使用一个 embedding 后端：阿里 DashScope 的
``text-embedding-v3``，并通过其 **OpenAI 兼容端点**（``/compatible-mode/v1``）
调用，好让 LangChain 的 OpenAI 客户端来出面通信。上游那套服务商矩阵 ——
在 ``Memory.__init__`` 里用一个 ``match`` 撑起 20 多个后端 —— 已被删掉。

服务商与模型由 ``config/variables/default.py`` 中的 ``EMBEDDING``
（``"dashscope:<model>"``）指定；下面那些 DashScope 特有的坑都已在代码里
设好默认值，调用方不必再重新踩一遍。
"""

import os
from typing import Any

# 仅为成本估算而保留：`context/compression.py` 把它当作 tiktoken 分词器代理
# 传给 `estimate_embedding_cost()`。tiktoken 并不认识 DashScope 的模型名，
# 反正会退回默认编码；算出来的美元数字只是粗略参考，不是真实价格。
OPENAI_EMBEDDING_MODEL = os.environ.get(
    "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
)

_SUPPORTED_PROVIDERS = {"dashscope"}

_DASHSCOPE_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class Memory:
    """管理用于文档相似度与检索的 embedding 生成。

    示例：
        ```python
        memory = Memory("dashscope", "text-embedding-v3")
        embeddings = memory.get_embeddings()
        ```
    """

    def __init__(self, embedding_provider: str, model: str, **embedding_kwargs: Any):
        """用 DashScope embedding 后端初始化 Memory。

        参数：
            embedding_provider: 必须是 ``"dashscope"``。
            model: DashScope 的模型名，例如 ``text-embedding-v3``。
            **embedding_kwargs: 透传给 ``OpenAIEmbeddings``。此处设置的任何
                键都优先于下方应用的默认值。

        异常：
            ValueError: 服务商不是 DashScope，或找不到 DashScope 的 API key。
        """
        if embedding_provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported embedding provider {embedding_provider!r}. "
                f"Supported providers: {', '.join(sorted(_SUPPORTED_PROVIDERS))}"
            )

        # 在这里就失败，而不是让 OpenAIEmbeddings 悄悄用上 OPENAI_API_KEY
        # —— 那是聊天模型的 key，DashScope 会用一句语焉不详的 401 拒掉。
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
        # text-embedding-v3 不是 tiktoken 认识的模型，客户端那套上下文长度
        # 校验会在请求发出前就直接报错，所以关掉。
        embedding_kwargs.setdefault("check_embedding_ctx_length", False)
        # DashScope 拒绝单批超过 10 条输入的 embedding 请求。
        embedding_kwargs.setdefault("chunk_size", 10)

        from langchain_openai import OpenAIEmbeddings

        self._embeddings = OpenAIEmbeddings(model=model, **embedding_kwargs)

    def get_embeddings(self):
        """获取已配置好的 embeddings 实例。

        返回：
            为本项目配置的 LangChain embeddings 实例。
        """
        return self._embeddings