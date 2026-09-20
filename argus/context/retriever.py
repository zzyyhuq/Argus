import os
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

# 每篇文档参与 embedding 的 raw_content 最大字符数。
# 若把整篇文档一次发出去，大文档（例如抓取到的 PDF）可能超出 embedding API 的
# token 上限（例如 OpenAI 单请求 300 000 token 的限制）。
# 默认 50 000 字符（约 12 500 token）；可用环境变量 MAX_CONTENT_CHARS 覆盖。
_MAX_CONTENT_CHARS = int(os.environ.get("MAX_CONTENT_CHARS", 50000))


class SearchAPIRetriever(BaseRetriever):
    """基于搜索 API 的 retriever。"""
    pages: List[Dict] = []

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:

        docs = [
            Document(
                # ``raw_content`` 可能是显式的 None（抓取失败的页面会被
                # scraper 置为 None），而对 None 做切片会抛 TypeError。
                # 因此先转成字符串再截断。
                page_content=(page.get("raw_content") or "")[:_MAX_CONTENT_CHARS],
                metadata={
                    "title": page.get("title", ""),
                    "source": page.get("url", ""),
                },
            )
            for page in self.pages
        ]

        return docs

class SectionRetriever(BaseRetriever):
    """
    SectionRetriever:
    本类用于检索内容段落，同时避免出现重复的子主题。
    """
    sections: List[Dict] = []
    """
    sections 示例：
    [
        {
            "section_title": "Example Title",
            "written_content": "Example content"
        },
        ...
    ]
    """
    
    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:

        docs = [
            Document(
                page_content=page.get("written_content", ""),
                metadata={
                    "section_title": page.get("section_title", ""),
                },
            )
            for page in self.sections  # 由 'self.pages' 改为 'self.sections'
        ]

        return docs