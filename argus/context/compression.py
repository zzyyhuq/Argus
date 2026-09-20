"""Argus 的上下文压缩工具。

本模块提供若干类，借助 embedding 与相似度过滤，从文档中压缩并取出相关上下文。

压缩流程：
1. 把文档切分成 chunk
2. 依据与查询的 embedding 相似度筛选 chunk
3. 把最相关的 chunk 作为上下文返回

类：
    VectorstoreCompressor: 从向量库中检索上下文。
    ContextCompressor: 用 embedding 相似度压缩原始文档。
    WrittenContentCompressor: 压缩此前写好的内容段落。
"""

import asyncio
import os
from typing import Optional

from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import (
    DocumentCompressorPipeline,
    EmbeddingsFilter,
)
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..memory.embeddings import OPENAI_EMBEDDING_MODEL
from ..prompts import PromptFamily
from ..utils.costs import estimate_embedding_cost
from ..vector_store import VectorStoreWrapper
from .retriever import SearchAPIRetriever, SectionRetriever


class VectorstoreCompressor:
    """从向量库中检索并压缩上下文。

    在已有向量库上做相似度搜索，为给定查询找出相关文档。

    属性：
        vector_store: 待搜索的向量库包装对象。
        max_results: 最多返回的结果条数。
        filter: 向量库查询的可选过滤条件。
    """

    def __init__(
        self,
        vector_store: VectorStoreWrapper,
        max_results: int = 7,
        filter: Optional[dict] = None,
        prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
        **kwargs,
    ):
        """初始化 VectorstoreCompressor。

        参数：
            vector_store: 待搜索的向量库。
            max_results: 最多返回的结果条数。
            filter: 查询用的可选过滤字典。
            prompt_family: 用于格式化输出的 prompt 家族。
            **kwargs: 额外的关键字参数。
        """
        self.vector_store = vector_store
        self.max_results = max_results
        self.filter = filter
        self.kwargs = kwargs
        self.prompt_family = prompt_family

    async def async_get_context(self, query: str, max_results: int = 5) -> str:
        """从向量库中取出相关上下文。

        参数：
            query: 搜索查询。
            max_results: 最多返回的结果条数。

        返回：
            格式化后的相关文档内容字符串。
        """
        results = await self.vector_store.asimilarity_search(query=query, k=max_results, filter=self.filter)
        return self.prompt_family.pretty_print_docs(results)


class ContextCompressor:
    """压缩原始文档，从中提取相关上下文。

    用 embedding 相似度过滤文档 chunk，只保留与给定查询最相关的内容。

    属性：
        documents: 待压缩的文档列表。
        embeddings: 用于计算相似度的 embedding 模型。
        max_results: 最多返回的结果条数。
        similarity_threshold: 入选所需的最低相似度分数。
    """

    def __init__(
        self,
        documents,
        embeddings,
        max_results: int = 5,
        similarity_threshold: float | None = None,
        prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
        **kwargs,
    ):
        """初始化 ContextCompressor。

        参数：
            documents: 待压缩的文档列表。
            embeddings: embedding 模型实例。
            max_results: 最多返回的结果条数。
            similarity_threshold: 入选所需的最低相似度分数。
                未提供时回退到环境变量 SIMILARITY_THRESHOLD。
            prompt_family: 用于格式化输出的 prompt 家族。
            **kwargs: 额外的关键字参数。
        """
        self.max_results = max_results
        self.documents = documents
        self.kwargs = kwargs
        self.embeddings = embeddings
        if similarity_threshold is None:
            similarity_threshold = float(os.environ.get("SIMILARITY_THRESHOLD", 0.35))
        self.similarity_threshold = similarity_threshold
        self.prompt_family = prompt_family

    def __get_contextual_retriever(self):
        """构建上下文压缩 retriever 流水线。

        返回：
            一个配置好文本切分与 embedding 过滤的 ContextualCompressionRetriever。
        """
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        relevance_filter = EmbeddingsFilter(embeddings=self.embeddings,
                                            similarity_threshold=self.similarity_threshold)
        pipeline_compressor = DocumentCompressorPipeline(
            transformers=[splitter, relevance_filter]
        )
        base_retriever = SearchAPIRetriever(
            pages=self.documents
        )
        contextual_retriever = ContextualCompressionRetriever(
            base_compressor=pipeline_compressor, base_retriever=base_retriever
        )
        return contextual_retriever

    async def async_get_context(self, query: str, max_results: int = 5, cost_callback=None) -> str:
        """异步地从文档中取出相关上下文。

        优化点：文档集较小时跳过昂贵的压缩流水线。
        文档本身已经足够简短时，直接拿来用，不做基于 embedding 的过滤。

        参数：
            query: 搜索查询。
            max_results: 最多返回的结果条数。
            cost_callback: 用于统计 embedding 成本的可选回调。

        返回：
            格式化后的相关文档内容字符串。
        """
        # 优化：先算出内容总量
        total_chars = sum(len(str(doc.get('raw_content', ''))) for doc in self.documents)
        chunk_threshold = int(os.environ.get("COMPRESSION_THRESHOLD", "8000"))

        # 内容总量小就直接返回，省掉昂贵的压缩
        if total_chars < chunk_threshold and len(self.documents) <= max_results:
            # 快速路径：无需压缩
            # 把 scraper/retriever 的字典键映射成 pretty_print_docs 期望的 metadata。
            # 原始字典用的是 `url`；SearchAPIRetriever / pretty_print 用的是 `source`。
            direct_docs = [
                Document(
                    page_content=doc.get('raw_content', '') or '',
                    metadata={
                        "title": doc.get("title", "") or "",
                        "source": doc.get("source") or doc.get("url") or "",
                    },
                )
                for doc in self.documents[:max_results]
            ]
            return self.prompt_family.pretty_print_docs(direct_docs, max_results)

        # 常规路径：内容较多时走压缩
        compressed_docs = self.__get_contextual_retriever()
        if cost_callback:
            cost_callback(estimate_embedding_cost(model=OPENAI_EMBEDDING_MODEL, docs=self.documents))
        relevant_docs = await asyncio.to_thread(compressed_docs.invoke, query, **self.kwargs)
        return self.prompt_family.pretty_print_docs(relevant_docs, max_results)


class WrittenContentCompressor:
    """压缩此前已写好的内容段落。

    专用于从已写好的报告内容中找出相关段落的压缩器，会保留段落标题与结构。

    属性：
        documents: 已写好的内容段落列表。
        embeddings: 用于计算相似度的 embedding 模型。
        similarity_threshold: 入选所需的最低相似度分数。
    """

    def __init__(self, documents, embeddings, similarity_threshold: float, **kwargs):
        """初始化 WrittenContentCompressor。

        参数：
            documents: 已写好的内容段落列表。
            embeddings: embedding 模型实例。
            similarity_threshold: 入选所需的最低相似度分数。
            **kwargs: 额外的关键字参数。
        """
        self.documents = documents
        self.kwargs = kwargs
        self.embeddings = embeddings
        self.similarity_threshold = similarity_threshold

    def __get_contextual_retriever(self):
        """构建面向内容段落的上下文压缩 retriever。

        返回：
            一个为段落检索配置好的 ContextualCompressionRetriever。
        """
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        relevance_filter = EmbeddingsFilter(embeddings=self.embeddings,
                                            similarity_threshold=self.similarity_threshold)
        pipeline_compressor = DocumentCompressorPipeline(
            transformers=[splitter, relevance_filter]
        )
        base_retriever = SectionRetriever(
            sections=self.documents
        )
        contextual_retriever = ContextualCompressionRetriever(
            base_compressor=pipeline_compressor, base_retriever=base_retriever
        )
        return contextual_retriever

    def __pretty_docs_list(self, docs, top_n: int) -> list[str]:
        """把文档格式化成「标题/内容」字符串列表。

        参数：
            docs: 待格式化的文档列表。
            top_n: 最多包含的文档数量。

        返回：
            格式化后的文档字符串列表。
        """
        return [f"Title: {d.metadata.get('section_title')}\nContent: {d.page_content}\n" for i, d in enumerate(docs) if i < top_n]

    async def async_get_context(self, query: str, max_results: int = 5, cost_callback=None) -> list[str]:
        """异步地取出相关的已写内容段落。

        参数：
            query: 搜索查询。
            max_results: 最多返回的结果条数。
            cost_callback: 用于统计 embedding 成本的可选回调。

        返回：
            格式化后的段落字符串列表。
        """
        compressed_docs = self.__get_contextual_retriever()
        if cost_callback:
            cost_callback(estimate_embedding_cost(model=OPENAI_EMBEDDING_MODEL, docs=self.documents))
        relevant_docs = await asyncio.to_thread(compressed_docs.invoke, query, **self.kwargs)
        return self.__pretty_docs_list(relevant_docs, max_results)
