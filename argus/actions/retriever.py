"""Argus 的 retriever 工厂与工具。

本模块提供实例化与管理各类搜索 retriever 实现的函数。
"""


def get_retriever(retriever: str):
    """按名称获取 retriever 类。

    参数：
        retriever: 要获取的 retriever 名称（如 'google'、'tavily'、'duckduckgo'）。

    返回：
        找到时返回对应的 retriever 类，否则返回 None。

    支持的 retriever：
        - google: Google Custom Search
        - searx: SearX 搜索引擎
        - searchapi: SearchAPI 服务
        - serpapi: SerpAPI 服务
        - serper: Serper API
        - duckduckgo: DuckDuckGo 搜索
        - bing: Bing 搜索
        - brave: Brave Search API
        - arxiv: arXiv 学术搜索
        - tavily: Tavily 搜索 API
        - exa: Exa 搜索
        - crw: fastCRW 搜索（兼容 Firecrawl 的网页 scraper）
        - semantic_scholar: Semantic Scholar 学术搜索
        - pubmed_central: PubMed Central 医学文献
        - openalex: OpenAlex 学术成果库
        - custom: 用户自定义 retriever
        - mcp: Model Context Protocol retriever
        - xquik: Xquik X/Twitter 搜索
        - getxapi: GetXAPI X/Twitter 搜索
    """
    match retriever:
        case "google":
            from argus.retrievers import GoogleSearch

            return GoogleSearch
        case "searx":
            from argus.retrievers import SearxSearch

            return SearxSearch
        case "searchapi":
            from argus.retrievers import SearchApiSearch

            return SearchApiSearch
        case "serpapi":
            from argus.retrievers import SerpApiSearch

            return SerpApiSearch
        case "serper":
            from argus.retrievers import SerperSearch

            return SerperSearch
        case "duckduckgo":
            from argus.retrievers import Duckduckgo

            return Duckduckgo
        case "bing":
            from argus.retrievers import BingSearch

            return BingSearch
        case "brave":
            from argus.retrievers import BraveSearch

            return BraveSearch
        case "bocha":
            from argus.retrievers import BoChaSearch

            return BoChaSearch
        case "arxiv":
            from argus.retrievers import ArxivSearch

            return ArxivSearch
        case "tavily":
            from argus.retrievers import TavilySearch

            return TavilySearch
        case "groundroute":
            from argus.retrievers import GroundRouteSearch

            return GroundRouteSearch
        case "exa":
            from argus.retrievers import ExaSearch

            return ExaSearch
        case "crw":
            from argus.retrievers import CRWRetriever

            return CRWRetriever
        case "semantic_scholar":
            from argus.retrievers import SemanticScholarSearch

            return SemanticScholarSearch
        case "pubmed_central":
            from argus.retrievers import PubMedCentralSearch

            return PubMedCentralSearch
        case "custom":
            from argus.retrievers import CustomRetriever

            return CustomRetriever
        case "mcp":
            from argus.retrievers import MCPRetriever

            return MCPRetriever
        case "xquik":
            from argus.retrievers import XquikSearch

            return XquikSearch
        case "openalex":
            from argus.retrievers import OpenAlexSearch

            return OpenAlexSearch
        case "getxapi":
            from argus.retrievers import GetXAPISearch

            return GetXAPISearch

        case _:
            return None


def get_retrievers(headers: dict[str, str], cfg):
    """
    根据 headers、配置或默认值决定使用哪些 retriever。

    参数：
        headers (dict): headers 字典
        cfg: 配置对象

    返回：
        list: 用于搜索的 retriever 类列表。
    """
    # 先在 headers 里查是否指定了多个 retriever
    if headers.get("retrievers"):
        retrievers = headers.get("retrievers").split(",")
    # 没找到再查 headers 里的单个 retriever
    elif headers.get("retriever"):
        retrievers = [headers.get("retriever")]
    # headers 里没有则查配置里的多个 retriever
    elif cfg.retrievers:
        # 配置里的 retrievers 同时兼容列表与字符串两种形式
        if isinstance(cfg.retrievers, str):
            retrievers = cfg.retrievers.split(",")
        else:
            retrievers = cfg.retrievers
    # 再查配置里的单个 retriever
    elif cfg.retriever:
        retrievers = [cfg.retriever]
    # 仍未设置则使用默认 retriever
    else:
        retrievers = [get_default_retriever().__name__]

    # 去掉每个 retriever 名称两侧的空白，好让带空格的逗号分隔列表（例如来自
    # header 或配置的 "tavily, exa"）能正确解析，而不是悄悄退回默认 retriever。
    retrievers = [r.strip() for r in retrievers if r and r.strip()]

    # 把 retriever 名称转换为实际的 retriever 类
    # 无效名称一律用 get_default_retriever() 兜底
    retriever_classes = [get_retriever(r) or get_default_retriever() for r in retrievers]
    
    return retriever_classes


def get_default_retriever():
    """获取默认的 retriever 类。

    返回：
        作为默认搜索 provider 的 TavilySearch retriever 类。
    """
    from argus.retrievers import TavilySearch

    return TavilySearch