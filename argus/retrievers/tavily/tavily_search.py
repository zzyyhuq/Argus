"""Argus 的 Tavily API search retriever。

本模块提供 TavilySearch 类，用于通过 Tavily API 执行网络搜索。
"""

import json
import os
import re
from typing import Literal, Optional, Sequence

import requests

# Google 风格的 site:domain 操作符，Tavily API 并不支持。
_SITE_OPERATOR_PATTERN = re.compile(r"site:(\S+)", re.IGNORECASE)


class TavilySearch:
    """
    Tavily API retriever
    """

    # Tavily 的 search() 从不设置 include_raw_content，因此结果始终只是
    # 链接加摘要片段——页面仍需另行抓取。
    requires_scraping = True

    def __init__(self, query, headers=None, topic="general", query_domains=None):
        """
        初始化 TavilySearch 对象。

        参数：
            query (str): 搜索查询字符串。
            headers (dict, optional): 请求中附加的 headers。默认为 None。
            topic (str, optional): 搜索主题。默认为 "general"。
            query_domains (list, optional): 要纳入搜索的域名列表。默认为 None。
        """
        self.query = query
        self.headers = headers or {}
        self.topic = topic
        self.base_url = "https://api.tavily.com/search"
        self.api_key = self.get_api_key()
        self.headers = {
            "Content-Type": "application/json",
        }
        self.query_domains = query_domains or None

    def get_api_key(self):
        """
        获取 Tavily API key
        返回：

        """
        api_key = self.headers.get("tavily_api_key")
        if not api_key:
            try:
                api_key = os.environ["TAVILY_API_KEY"]
            except KeyError:
                print(
                    "Tavily API key not found, set to blank. If you need a retriver, please set the TAVILY_API_KEY environment variable."
                )
                return ""
        return api_key


    def _search(
        self,
        query: str,
        search_depth: Literal["basic", "advanced"] = "basic",
        topic: str = "general",
        days: int = 2,
        max_results: int = 10,
        include_domains: Sequence[str] = None,
        exclude_domains: Sequence[str] = None,
        include_answer: bool = False,
        include_raw_content: bool = False,
        include_images: bool = False,
        use_cache: bool = True,
    ) -> dict:
        """
        内部搜索方法，负责把请求发给 API。
        """

        data = {
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "days": days,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "max_results": max_results,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
            "include_images": include_images,
            "api_key": self.api_key,
            "use_cache": use_cache,
        }

        response = requests.post(
            self.base_url, data=json.dumps(data), headers=self.headers, timeout=100
        )

        if response.status_code == 200:
            return response.json()
        else:
            # HTTP 请求返回非成功状态码时抛出 HTTPError
            response.raise_for_status()

    def search(self, max_results=10):
        """
        执行查询搜索
        返回：

        """
        try:
            # LLM 生成的查询常用 Google 风格的 site: 操作符，Tavily 会拒绝这类
            # 查询（返回零结果）。这里改为把它们转换成 Tavily 的 include_domains 参数。
            query = self.query
            include_domains = self.query_domains
            site_domains = _SITE_OPERATOR_PATTERN.findall(query)
            if site_domains:
                query = _SITE_OPERATOR_PATTERN.sub("", query).strip()
                # 只保留域名部分（Tavily 匹配的是域名，不是路径）
                site_domains = [d.strip(",").split("/")[0] for d in site_domains]
                include_domains = list(dict.fromkeys(site_domains + (include_domains or [])))

            # 执行搜索（Tavily 会拒绝超过 400 字符的查询）
            results = self._search(
                query[:400],
                search_depth="basic",
                max_results=max_results,
                topic=self.topic,
                include_domains=include_domains,
            )
            # API/代理异常时 JSON body 可能是 list 或标量；只有 dict 形式的
            # 响应才带我们能识别的顶层 "results" 键。
            if not isinstance(results, dict):
                raise Exception("No results found with Tavily API search.")
            sources = results.get("results", [])
            if not isinstance(sources, list) or not sources:
                raise Exception("No results found with Tavily API search.")
            # 返回结果。对每个 source 做字段缺失/None 保护，
            # 避免单条畸形命中导致整页结果被丢弃。
            search_response = []
            for obj in sources:
                if not isinstance(obj, dict):
                    continue
                href = obj.get("url")
                if not href:
                    continue
                body = obj.get("content") or obj.get("snippet") or ""
                search_response.append({"href": href, "body": body})
        except Exception as e:
            print(f"Error: {e}. Failed fetching sources. Resulting in empty response.")
            search_response = []
        return search_response
