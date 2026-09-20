# Tavily API retriever

# 依赖库
import os
import requests
import json
from urllib.parse import urlencode


class GoogleSearch:
    """
    Google API retriever
    """
    def __init__(self, query, headers=None, query_domains=None):
        """
        初始化 GoogleSearch 对象
        参数：
            query:
        """
        self.query = query
        self.headers = headers or {}
        self.query_domains = query_domains or None
        self.api_key = self.headers.get("google_api_key") or self.get_api_key()  # 使用传入的 api_key，否则回退到环境变量
        self.cx_key = self.headers.get("google_cx_key") or self.get_cx_key()  # 使用传入的 cx_key，否则回退到环境变量

    def get_api_key(self):
        """
        获取 Google API key
        返回：

        """
        # 获取 API key
        try:
            api_key = os.environ["GOOGLE_API_KEY"]
        except Exception:
            raise Exception("Google API key not found. Please set the GOOGLE_API_KEY environment variable. "
                            "You can get a key at https://developers.google.com/custom-search/v1/overview")
        return api_key

    def get_cx_key(self):
        """
        获取 Google CX key
        返回：

        """
        # 获取 API key
        try:
            api_key = os.environ["GOOGLE_CX_KEY"]
        except Exception:
            raise Exception("Google CX key not found. Please set the GOOGLE_CX_KEY environment variable. "
                            "You can get a key at https://developers.google.com/custom-search/v1/overview")
        return api_key

    def search(self, max_results=7):
        """
        使用 Google Custom Search API 执行查询搜索，可选地限定到指定域名
        返回：
            list: 含 title、href 与 body 的搜索结果列表
        """
        # 若指定了域名限制，则据此拼装查询
        search_query = self.query
        if self.query_domains and len(self.query_domains) > 0:
            domain_query = " OR ".join([f"site:{domain}" for domain in self.query_domains])
            search_query = f"({domain_query}) {self.query}"

        print("Searching with query {0}...".format(search_query))

        # 对所有参数做 URL 编码。直接拼接原始查询会破坏任何含保留字符的搜索
        # （例如 "AT&T" 里的 "&" 会多出一个参数，"#" 会截断后面的查询内容）。
        query_string = urlencode(
            {
                "key": self.api_key,
                "cx": self.cx_key,
                "q": search_query,
                "start": 1,
            }
        )
        url = f"https://www.googleapis.com/customsearch/v1?{query_string}"
        resp = requests.get(url)

        if resp.status_code < 200 or resp.status_code >= 300:
            print("Google search: unexpected response status: ", resp.status_code)

        if resp is None:
            return []
        try:
            search_results = json.loads(resp.text)
        except Exception:
            return []
        if not isinstance(search_results, dict):
            return []

        results = search_results.get("items", []) or []
        search_response = []

        # 把结果归一化成与其他搜索 API 一致的格式。
        # 用 .get 取值，避免 title/snippet 缺失就丢掉一条有效链接；
        # 非 dict 的行和空链接直接跳过。
        for result in results:
            if not isinstance(result, dict):
                continue
            link = result.get("link") or ""
            if not link or "youtube.com" in link:
                continue
            search_response.append(
                {
                    "title": result.get("title") or "",
                    "href": link,
                    "body": result.get("snippet") or "",
                }
            )

        return search_response[:max_results]
