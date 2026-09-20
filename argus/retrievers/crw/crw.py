"""Argus 的 fastCRW API search retriever。

本模块提供 CRWRetriever 类，用于通过 fastCRW 执行网络搜索。fastCRW 是一个
兼容 Firecrawl 的 web 数据引擎（单个二进制，可自托管，也可用托管云服务）。
"""

import json
import os

import requests


class CRWRetriever:
    """
    fastCRW API retriever
    """

    def __init__(self, query, headers=None, topic="general", query_domains=None):
        """
        初始化 CRWRetriever 对象。

        参数：
            query (str): 搜索查询字符串。
            headers (dict, optional): 请求中附加的 headers。默认为 None。
            topic (str, optional): 搜索主题。默认为 "general"。
            query_domains (list, optional): 要纳入搜索的域名列表。默认为 None。
        """
        input_headers = headers or {}
        self.query = query
        self.topic = topic
        self.base_url = self.get_base_url(input_headers)
        self.api_key = self.get_api_key(input_headers)
        self.headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
        self.query_domains = query_domains or None

    def get_api_key(self, headers):
        """
        获取 fastCRW API key
        参数：
            headers (dict): 传给 retriever 的 headers。
        返回：

        """
        api_key = headers.get("crw_api_key")
        if not api_key:
            try:
                api_key = os.environ["CRW_API_KEY"]
            except KeyError:
                print(
                    "CRW API key not found, set to blank. If you need a retriver, please set the CRW_API_KEY environment variable."
                )
                return ""
        return api_key

    def get_base_url(self, headers):
        """
        获取 fastCRW 的 base URL，允许自托管覆盖。

        默认使用托管云服务 https://fastcrw.com/api。可通过 CRW_API_URL 环境变量
        （或 crw_api_url header）指向自建服务器。
        参数：
            headers (dict): 传给 retriever 的 headers。
        返回：
            base URL（末尾不带斜杠）。
        """
        base_url = headers.get("crw_api_url") or os.environ.get(
            "CRW_API_URL", "https://fastcrw.com/api"
        )
        return base_url.rstrip("/")

    def _search(self, query: str, max_results: int = 10) -> dict:
        """
        内部搜索方法，负责把请求发给 API。
        """

        data = {
            "query": query,
            "limit": max_results,
        }

        response = requests.post(
            f"{self.base_url}/v1/search",
            data=json.dumps(data),
            headers=self.headers,
            timeout=100,
        )
        # HTTP 请求返回非成功状态码时抛出 HTTPError
        response.raise_for_status()
        results = response.json()
        # fastCRW 把响应包在 {success, error, data} 信封里。
        if results.get("success") is False:
            raise Exception(results.get("error", "fastCRW API search failed."))
        return results

    def search(self, max_results=10):
        """
        执行查询搜索
        返回：

        """
        try:
            # 执行查询搜索
            results = self._search(self.query, max_results=max_results)
            sources = results.get("data") or []
            if not isinstance(sources, list) or not sources:
                raise Exception("No results found with fastCRW API search.")
            # 返回结果。缺少 "url" 的 source 不可用，直接跳过，
            # 而不是抛 KeyError 丢掉整个结果集。
            search_response = []
            for obj in sources:
                if not isinstance(obj, dict):
                    continue
                href = obj.get("url") or ""
                if not href:
                    continue
                search_response.append(
                    {
                        "href": href,
                        "body": obj.get("markdown") or obj.get("description") or "",
                    }
                )
        except Exception as e:
            print(f"Error: {e}. Failed fetching sources. Resulting in empty response.")
            search_response = []
        return search_response
