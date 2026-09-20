"""Argus 的 GroundRoute search retriever。

GroundRoute 把每个查询路由到多个 web 搜索引擎（Serper、Brave、Exa、Tavily、
Firecrawl、Perplexity），挑出满足质量门槛的最便宜方案，缓存重复查询，并支持
故障转移——对外暴露为一个统一的搜索 API。
"""

import os

import requests


class GroundRouteSearch:
    """GroundRoute 多引擎 search retriever。"""

    def __init__(self, query, headers=None, topic="general", query_domains=None):
        self.query = query
        self.headers = headers or {}
        self.topic = topic
        self.base_url = "https://api.groundroute.ai/v1/search"
        self.api_key = self.get_api_key()
        self.query_domains = query_domains or None

    def get_api_key(self):
        """从 headers 或环境变量中获取 GroundRoute API key。"""
        api_key = self.headers.get("groundroute_api_key")
        if not api_key:
            try:
                api_key = os.environ["GROUNDROUTE_API_KEY"]
            except KeyError:
                raise Exception(
                    "GroundRoute API key not found. Set the GROUNDROUTE_API_KEY "
                    "environment variable. Create a key at https://groundroute.ai/overview"
                )
        return api_key

    def search(self, max_results=7):
        """通过 GroundRoute 执行搜索。返回 [{"href": url, "body": content}, ...]。"""
        try:
            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": self.query, "max_results": max_results},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            print(f"Error performing GroundRoute search: {e}")
            return []

        if isinstance(payload, list):
            results = payload
        elif isinstance(payload, dict):
            results = payload.get("results", [])
        else:
            return []

        if not isinstance(results, list):
            return []

        normalized = []
        for r in results:
            if not isinstance(r, dict):
                continue
            href = r.get("url") or r.get("href") or r.get("link") or ""
            if not href:
                continue
            body = r.get("content") or r.get("snippet") or r.get("body") or ""
            normalized.append({"href": href, "body": body})
            if len(normalized) >= max_results:
                break
        return normalized
