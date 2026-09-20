from typing import Dict, List

import requests


class SemanticScholarSearch:
    """
    Semantic Scholar API retriever
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    VALID_SORT_CRITERIA = ["relevance", "citationCount", "publicationDate"]

    def __init__(self, query: str, sort: str = "relevance", query_domains=None):
        """
        用查询与排序条件初始化 SemanticScholarSearch 类。

        :param query: 搜索查询字符串
        :param sort: 排序条件（'relevance'、'citationCount'、'publicationDate'）
        """
        self.query = query
        assert sort in self.VALID_SORT_CRITERIA, "Invalid sort criterion"
        # 原样保留（camelCase 的）排序条件。Semantic Scholar API 要求
        # ``citationCount`` / ``publicationDate`` 逐字一致；改成小写会得到
        # ``citationcount`` / ``publicationdate``，API 会拒绝或静默忽略。
        self.sort = sort

    def search(self, max_results: int = 20) -> List[Dict[str, str]]:
        """
        在 Semantic Scholar 上执行搜索并返回结果。

        :param max_results: 最多获取的结果数
        :return: 字典列表，每项含该论文的 title、href 与 body
        """
        params = {
            "query": self.query,
            "limit": max_results,
            "fields": "title,abstract,url,venue,year,authors,isOpenAccess,openAccessPdf",
            "sort": self.sort,
        }

        try:
            response = requests.get(self.BASE_URL, params=params)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"An error occurred while accessing Semantic Scholar API: {e}")
            return []

        payload = response.json()
        if not isinstance(payload, dict):
            return []
        results = payload.get("data") or []
        if not isinstance(results, list):
            return []

        search_result = []
        for result in results:
            if not isinstance(result, dict):
                continue
            pdf = result.get("openAccessPdf")
            if not (result.get("isOpenAccess") and isinstance(pdf, dict)):
                continue
            href = pdf.get("url") or ""
            if not href:
                continue
            search_result.append(
                {
                    "title": result.get("title") or "No Title",
                    "href": href,
                    "body": result.get("abstract") or "Abstract not available",
                }
            )

        return search_result
