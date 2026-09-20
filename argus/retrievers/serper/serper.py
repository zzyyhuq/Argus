# Google Serper retriever

# 依赖库
import os
import requests
import json


class SerperSearch():
    """
    Google Serper retriever，支持按国家、语言与时间范围过滤
    """
    def __init__(self, query, query_domains=None, country=None, language=None, time_range=None, exclude_sites=None):
        """
        初始化 SerperSearch 对象
        参数：
            query (str): 搜索查询字符串。
            query_domains (list, optional): 要纳入搜索的域名列表。默认为 None。
            country (str, optional): 搜索结果的国家代码（如 'us'、'kr'、'jp'）。默认为 None。
            language (str, optional): 搜索结果的语言代码（如 'en'、'ko'、'ja'）。默认为 None。
            time_range (str, optional): 时间范围过滤（如 'qdr:h'、'qdr:d'、'qdr:w'、'qdr:m'、'qdr:y'）。默认为 None。
            exclude_sites (list, optional): 要从搜索结果中排除的站点列表。默认为 None。
        """
        self.query = query
        self.query_domains = query_domains or None
        self.country = country or os.getenv("SERPER_REGION")
        self.language = language or os.getenv("SERPER_LANGUAGE")
        self.time_range = time_range or os.getenv("SERPER_TIME_RANGE")
        self.exclude_sites = exclude_sites or self._get_exclude_sites_from_env()
        self.api_key = self.get_api_key()

    def _get_exclude_sites_from_env(self):
        """
        从环境变量中读取要排除的站点列表
        返回：
            list: 要排除的站点列表
        """
        exclude_sites_env = os.getenv("SERPER_EXCLUDE_SITES", "")
        if exclude_sites_env:
            # 按逗号切分并去掉空白
            return [site.strip() for site in exclude_sites_env.split(",") if site.strip()]
        return []

    def get_api_key(self):
        """
        获取 Serper API key
        返回：

        """
        try:
            api_key = os.environ["SERPER_API_KEY"]
        except Exception:
            raise Exception("Serper API key not found. Please set the SERPER_API_KEY environment variable. "
                            "You can get a key at https://serper.dev/")
        return api_key

    def search(self, max_results=7):
        """
        执行查询搜索，可选地带上国家、语言与时间过滤
        返回：
            list: 含 title、href 与 body 的搜索结果列表
        """
        print("Searching with query {0}...".format(self.query))
        """Useful for general internet search queries using the Serper API."""

        # 执行查询搜索（请求格式见 https://serper.dev/playground）
        url = "https://google.serper.dev/search"

        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

        # 构造搜索参数
        query_with_filters = self.query

        # 用 Google 搜索语法排除指定站点
        if self.exclude_sites:
            for site in self.exclude_sites:
                query_with_filters += f" -site:{site}"

        # 若指定了域名过滤，则加上
        if self.query_domains:
            # 在搜索查询后追加 site:domain1 OR site:domain2 OR ...
            domain_query = " site:" + " OR site:".join(self.query_domains)
            query_with_filters += domain_query

        search_params = {
            "q": query_with_filters,
            "num": max_results
        }

        # 存在时加上可选参数
        if self.country:
            search_params["gl"] = self.country  # 地理位置（国家）

        if self.language:
            search_params["hl"] = self.language  # 界面语言

        if self.time_range:
            search_params["tbs"] = self.time_range  # 按时间过滤搜索

        data = json.dumps(search_params)

        resp = requests.request("POST", url, timeout=10, headers=headers, data=data)

        # 预处理结果。始终返回 list，避免调用方（会做 `len(...)` 或遍历结果）
        # 拿到 None。
        if resp is None:
            return []
        try:
            search_results = json.loads(resp.text)
        except Exception:
            return []
        if search_results is None or not isinstance(search_results, dict):
            return []

        results = search_results.get("organic") or []
        if not isinstance(results, list):
            return []
        search_results = []

        # 把结果归一化成与其他搜索 API 一致的格式
        # 被排除的站点应已由查询参数过滤掉
        for result in results:
            if not isinstance(result, dict):
                continue
            href = result.get("link") or result.get("url") or ""
            if not href:
                continue
            search_results.append(
                {
                    "title": result.get("title") or "",
                    "href": href,
                    "body": result.get("snippet") or result.get("body") or "",
                }
            )

        return search_results
