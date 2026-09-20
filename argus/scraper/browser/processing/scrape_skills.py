from langchain_community.document_loaders import PyMuPDFLoader
from langchain_community.retrievers import ArxivRetriever


def scrape_pdf_with_pymupdf(url) -> str:
    """用 pymupdf 抓取 pdf

    参数：
        url (str): 要抓取的 pdf 的 url

    返回：
        str: 从 pdf 中抓取到的文本
    """
    loader = PyMuPDFLoader(url)
    doc = loader.load()
    return str(doc)


def scrape_pdf_with_arxiv(query) -> str:
    """用 arxiv 抓取 pdf
    默认文档长度 70000，约 15 页；设为 None 表示不限制

    参数：
        query (str): 要搜索的查询

    返回：
        str: 从 pdf 中抓取到的文本
    """
    retriever = ArxivRetriever(load_max_docs=2, doc_content_chars_max=None)
    docs = retriever.get_relevant_documents(query=query)
    return docs[0].page_content