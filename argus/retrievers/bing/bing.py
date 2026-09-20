# Bing Search retriever

# 依赖库
import os
import requests
import json
import logging


class BingSearch():
    """
    Bing Search retriever
    """

    def __init__(self, query, query_domains=None):
        """
        初始化 BingSearch 对象
        参数：
            query:
        """
        self.query = query
        self.query_domains = query_domains or None
        self.api_key = self.get_api_key()
        self.logger = logging.getLogger(__name__)

    def get_api_key(self):
        """
        获取 Bing API key
        返回：

        """
        try:
            api_key = os.environ["BING_API_KEY"]
        except Exception:
            raise Exception(
                "Bing API key not found. Please set the BING_API_KEY environment variable.")
        return api_key

    def search(self, max_results=7) -> list[dict[str]]:
        """
        执行查询搜索
        返回：

        """
        print("Searching with query {0}...".format(self.query))
        """Useful for general internet search queries using the Bing API."""

        # 执行查询搜索
        url = "https://api.bing.microsoft.com/v7.0/search"

        headers = {
            'Ocp-Apim-Subscription-Key': self.api_key,
            'Content-Type': 'application/json'
        }
        # TODO: 增加对 query domains 的支持
        params = {
            "responseFilter": "Webpages",
            "q": self.query,
            "count": max_results,
            "setLang": "en-GB",
            "textDecorations": False,
            "textFormat": "HTML",
            "safeSearch": "Strict"
        }

        resp = requests.get(url, headers=headers, params=params)

        # 预处理结果
        if resp is None:
            return []
        try:
            search_results = json.loads(resp.text)
            results = search_results.get("webPages", {}).get("value", [])
        except Exception as e:
            self.logger.error(
                f"Error parsing Bing search results: {e}. Resulting in empty response.")
            return []
        if not results:
            self.logger.warning(f"No search results found for query: {self.query}")
            return []

        # 把结果归一化成与其他搜索 API 一致的格式。
        # 跳过非 dict 的行（API 变动/错误占位）与空 URL，
        # 而不是让它们在研究过程中触发 AttributeError/'NoneType' 崩溃。
        search_response = []
        if not isinstance(results, list):
            return []
        for result in results:
            if not isinstance(result, dict):
                continue
            url = result.get("url") or ""
            if not url:
                continue
            # 跳过 youtube 结果
            if "youtube.com" in url:
                continue
            search_response.append({
                "title": result.get("name") or "",
                "href": url,
                "body": result.get("snippet") or "",
            })

        return search_response
