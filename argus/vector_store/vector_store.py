"""
langchain vector store 的封装。
"""
from typing import List, Dict

from langchain_core.documents import Document
from langchain_community.vectorstores import VectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

class VectorStoreWrapper:
    """
    包装 LangchainVectorStore，以适配 Argus 的文档类型
    """
    def __init__(self, vector_store : VectorStore):
        self.vector_store = vector_store

    def load(self, documents):
        """
        把文档载入 vector_store。

        先转成 langchain 的文档类型，切成小块，再写入。
        """
        langchain_documents = self._create_langchain_documents(documents)
        splitted_documents = self._split_documents(langchain_documents)
        self.vector_store.add_documents(splitted_documents)
    
    def _create_langchain_documents(self, data: List[Dict[str, str]]) -> List[Document]:
        """把 Argus 的文档转换成 Langchain Document。

        会跳过非 dict 的行，以及 ``raw_content`` 不可用的条目；缺少 ``url``
        时仍会生成文档、source 留空，而不是抛 KeyError。
        """
        docs: List[Document] = []
        if not data:
            return docs
        for item in data:
            if not isinstance(item, dict):
                continue
            content = item.get("raw_content")
            if content is None:
                continue
            docs.append(
                Document(
                    page_content=str(content),
                    metadata={"source": item.get("url") or ""},
                )
            )
        return docs

    def _split_documents(self, documents: List[Document], chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Document]:
        """
        把文档切成更小的块
        """
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return text_splitter.split_documents(documents)

    async def asimilarity_search(self, query, k, filter):
        """通过 vector store 执行查询"""
        results = await self.vector_store.asimilarity_search(query=query, k=k, filter=filter)
        return results
