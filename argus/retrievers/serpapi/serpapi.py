# SerpApi retriever

# 依赖库
import os
import requests
import urllib.parse


class SerpApiSearch():
    """
    SerpApi retriever
    """
    def __init__(self, query, query_domains=None):
        """
        初始化 SerpApiSearch 对象
        参数：
            query:
        """
        self.query = query
        self.query_domains = query_domains or None
        self.api_key = self.get_api_key()

    def get_api_key(self):
        """
        获取 SerpApi API key
        返回：

        """
        try:
            api_key = os.environ["SERPAPI_API_KEY"]
        except Exception:
            raise Exception("SerpApi API key not found. Please set the SERPAPI_API_KEY environment variable. "
                            "You can get a key at https://serpapi.com/")
        return api_key

    def search(self, max_results=7):
        """
        执行查询搜索
        返回：

        """
        print("SerpApiSearch: Searching with query {0}...".format(self.query))
        """Useful for general internet search queries using SerpApi."""

        url = "https://serpapi.com/search.json"

        search_query = self.query
        if self.query_domains:
            # 在搜索查询后追加 site:domain1 OR site:domain2 OR ...
            search_query += " site:" + " OR site:".join(self.query_domains)

        params = {
            "q": search_query,
            "api_key": self.api_key
        }
        encoded_url = url + "?" + urllib.parse.urlencode(params)
        search_response = []
        try:
            response = requests.get(encoded_url, timeout=10)
            if response.status_code == 200:
                search_results = response.json()
                if search_results:
                    # 没有自然结果的响应（如错误载荷或没匹配到任何内容的查询）
                    # 不含 "organic_results" 键；默认取 []，而不是抛 KeyError。
                    results = search_results.get("organic_results") or []
                    if not isinstance(results, list):
                        results = []
                    results_processed = 0
                    for result in results:
                        if results_processed >= max_results:
                            break
                        if not isinstance(result, dict):
                            continue
                        link = result.get("link") or ""
                        # 没有链接的结果不可用；直接跳过，
                        # 而不是产出一条 href=None 的记录。
                        if not link:
                            continue
                        # 跳过 youtube 结果
                        if "youtube.com" in link:
                            continue
                        search_result = {
                            "title": result.get("title") or "",
                            "href": link,
                            "body": result.get("snippet") or "",
                        }
                        search_response.append(search_result)
                        results_processed += 1
        except Exception as e:
            print(f"Error: {e}. Failed fetching sources. Resulting in empty response.")
            search_response = []

        return search_response
