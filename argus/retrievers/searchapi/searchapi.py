# SearchApi retriever

# 依赖库
import logging
import os
import requests
import urllib.parse


class SearchApiSearch():
    """
    SearchApi retriever
    """
    def __init__(self, query, query_domains=None):
        """
        初始化 SearchApiSearch 对象
        参数：
            query:
        """
        self.query = query
        self.api_key = self.get_api_key()

    def get_api_key(self):
        """
        获取 SearchApi API key
        返回：

        """
        try:
            api_key = os.environ["SEARCHAPI_API_KEY"]
        except Exception:
            raise Exception("SearchApi key not found. Please set the SEARCHAPI_API_KEY environment variable. "
                            "You can get a key at https://www.searchapi.io/")
        return api_key

    def search(self, max_results=7):
        """
        执行查询搜索
        返回：

        """
        print("SearchApiSearch: Searching with query {0}...".format(self.query))
        """Useful for general internet search queries using SearchApi."""


        url = "https://www.searchapi.io/api/v1/search"
        params = {
            "q": self.query,
            "engine": "google",
        }

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
            'X-SearchApi-Source': 'argus'
        }

        encoded_url = url + "?" + urllib.parse.urlencode(params)
        search_response = []

        try:
            response = requests.get(encoded_url, headers=headers, timeout=20)
            if response.status_code == 200:
                search_results = response.json() or {}
                # ``organic_results`` 可能不存在（例如无匹配、错误载荷，
                # 或非 google 引擎的响应）。默认取 []，避免键缺失时抛
                # KeyError，被下面宽泛的 ``except`` 吞掉后静默丢掉全部结果。
                results = search_results.get("organic_results") or []
                results_processed = 0
                for result in results:
                    href = result.get("link") or ""
                    # 跳过 youtube 结果
                    if "youtube.com" in href:
                        continue
                    if results_processed >= max_results:
                        break
                    search_result = {
                        "title": result.get("title") or "",
                        "href": href,
                        "body": result.get("snippet") or "",
                    }
                    search_response.append(search_result)
                    results_processed += 1
        except Exception as e:
            logging.getLogger(__name__).warning(
                "SearchApiSearch: failed fetching sources (%s). "
                "Returning empty response.",
                e,
            )
            search_response = []

        return search_response
