# Brave 搜索 retriever

# 依赖库
import logging
import os

import requests


class BraveSearch:
    """
    Brave Search API retriever
    """

    def __init__(self, query, query_domains=None):
        """
        初始化 BraveSearch 对象
        参数：
            query:
        """
        self.query = query
        self.query_domains = query_domains or None
        self.api_key = self.get_api_key()
        self.logger = logging.getLogger(__name__)

    def get_api_key(self):
        """
        获取 Brave Search API key
        返回：

        """
        try:
            api_key = os.environ["BRAVE_API_KEY"]
        except Exception:
            raise Exception(
                "Brave Search API key not found. Please set the BRAVE_API_KEY environment variable."
            )
        return api_key

    def search(self, max_results=7) -> list[dict[str, str]]:
        """
        执行查询搜索
        返回：

        """
        print("Searching with query {0}...".format(self.query))
        """Useful for general internet search queries using the Brave Search API."""

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        # TODO: 增加对 query domains 的支持
        params = {
            "q": self.query,
            "count": min(max_results, 20),
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=20)
            response.raise_for_status()
            search_results = response.json()
            if not isinstance(search_results, dict):
                return []
            web = search_results.get("web") or {}
            if not isinstance(web, dict):
                return []
            results = web.get("results") or []
            if not isinstance(results, list):
                return []
        except Exception as e:
            self.logger.error(
                f"Error fetching Brave search results: {e}. Resulting in empty response."
            )
            return []

        if not isinstance(results, list):
            self.logger.warning(
                f"Unexpected Brave web.results type for query: {self.query}"
            )
            return []

        search_results = []

        # 把结果归一化成与其他搜索 API 一致的格式
        for result in results:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if not url:
                continue
            search_result = {
                "title": result.get("title") or "",
                "href": url,
                "body": result.get("description") or "",
            }
            search_results.append(search_result)

        return search_results
