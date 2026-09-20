"""Argus 的上下文管理技能。

本模块提供 ContextManager 类，负责研究查询的上下文检索、压缩与相似度匹配。
"""

import asyncio
from typing import Dict, List, Optional, Set

from ..actions.utils import stream_output
from ..context.compression import (
    ContextCompressor,
    VectorstoreCompressor,
    WrittenContentCompressor,
)


class ContextManager:
    """负责研究过程中的上下文检索与压缩。

    本类按查询查找相似内容、管理来自不同来源的上下文，
    并对内容进行压缩以提升处理效率。

    属性：
        researcher: 持有该管理器的父级 Argus 实例。
    """

    def __init__(self, researcher):
        """初始化 ContextManager。

        参数：
            researcher: 持有该管理器的 Argus 实例。
        """
        self.researcher = researcher

    async def get_similar_content_by_query(self, query: str, pages: list) -> str:
        """按查询从页面中取出相似内容。

        参数：
            query: 用于查找相似内容的搜索查询。
            pages: 待检索的页面内容列表。

        返回：
            压缩后的相关内容上下文字符串。
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "fetching_query_content",
                f"📚 Getting relevant content based on query: {query}...",
                self.researcher.websocket,
            )

        context_compressor = ContextCompressor(
            documents=pages,
            embeddings=self.researcher.memory.get_embeddings(),
            similarity_threshold=getattr(self.researcher.cfg, "similarity_threshold", None),
            prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )
        return await context_compressor.async_get_context(
            query=query, max_results=10, cost_callback=self.researcher.add_costs
        )

    async def get_similar_content_by_query_with_vectorstore(self, query: str, filter: dict | None) -> str:
        """按查询从 vectorstore 中取出相似内容。

        参数：
            query: 用于查找相似内容的搜索查询。
            filter: 可选的 vectorstore 查询过滤条件字典。

        返回：
            来自 vectorstore 的压缩相关上下文字符串。
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "fetching_query_format",
                f" Getting relevant content based on query: {query}...",
                self.researcher.websocket,
                )
        vectorstore_compressor = VectorstoreCompressor(
            self.researcher.vector_store, filter=filter, prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )
        return await vectorstore_compressor.async_get_context(query=query, max_results=8)

    async def get_similar_written_contents_by_draft_section_titles(
        self,
        current_subtopic: str,
        draft_section_titles: List[str],
        written_contents: List[Dict],
        max_results: int = 10
    ) -> List[str]:
        """根据草稿章节标题取出相似的已写内容。

        查找与当前子主题及草稿章节标题相匹配的、此前已写好的相关内容。

        参数：
            current_subtopic: 当前正在撰写的子主题。
            draft_section_titles: 草稿章节标题字符串列表。
            written_contents: 此前已写内容的字典列表。
            max_results: 最多返回的结果数量。

        返回：
            相关已写内容的字符串列表。
        """
        all_queries = [current_subtopic] + draft_section_titles

        async def process_query(query: str) -> Set[str]:
            return set(await self.__get_similar_written_contents_by_query(query, written_contents, **self.researcher.kwargs))

        results = await asyncio.gather(*[process_query(query) for query in all_queries])
        relevant_contents = set().union(*results)
        relevant_contents = list(relevant_contents)[:max_results]

        return relevant_contents

    async def __get_similar_written_contents_by_query(
        self,
        query: str,
        written_contents: List[Dict],
        similarity_threshold: float = 0.5,
        max_results: int = 10
    ) -> List[str]:
        """针对单个查询取出相似的已写内容。

        参数：
            query: 用于查找相似内容的查询。
            written_contents: 已写内容的字典列表。
            similarity_threshold: 相似度得分的最低阈值。
            max_results: 最多返回的结果数量。

        返回：
            相似已写内容的字符串列表。
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "fetching_relevant_written_content",
                f"🔎 Getting relevant written content based on query: {query}...",
                self.researcher.websocket,
            )

        written_content_compressor = WrittenContentCompressor(
            documents=written_contents,
            embeddings=self.researcher.memory.get_embeddings(),
            similarity_threshold=similarity_threshold,
            **self.researcher.kwargs
        )
        return await written_content_compressor.async_get_context(
            query=query, max_results=max_results, cost_callback=self.researcher.add_costs
        )
