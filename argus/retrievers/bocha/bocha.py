# BoCha Search retriever

# 依赖库
import os
import requests
import json
import logging


class BoChaSearch():
    """
    BoCha Search retriever
    """

    def __init__(self, query, query_domains=None):
        """
        初始化 BoChaSearch 对象
        参数：
            query:
        """
        self.query = query
        self.query_domains = query_domains or None
        self.api_key = os.environ["BOCHA_API_KEY"]

    def search(self, max_results=7) -> list[dict[str]]:
        """
        执行查询搜索
        返回：

        """
        url = 'https://api.bochaai.com/v1/web-search'
        headers = {
            'Authorization': f'Bearer {self.api_key}',  # 请替换为你的API密钥
            'Content-Type': 'application/json'
        }
        data = {
            "query": self.query,
            "freshness": "noLimit",  # 搜索的时间范围，
            "summary": True,  # 是否返回长文本摘要
            "count": max_results
        }

        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            json_response = response.json()
        except (requests.RequestException, ValueError) as e:
            logging.getLogger(__name__).warning(
                f"Error: {e}. Failed fetching sources. Resulting in empty response."
            )
            return []

        # BoCha 的响应结构是 data.webPages.value；出错或空载荷时其中任一层
        # 都可能缺失，因此这里逐层防御性取值，而不是让整个研究流程抛 KeyError。
        results = (
            ((json_response or {}).get("data") or {}).get("webPages") or {}
        ).get("value") or []
        if not isinstance(results, list):
            return []

        search_results = []

        if not isinstance(results, list):
            return []

        # 把结果归一化成与其他搜索 API 一致的格式。
        # 跳过非 dict 的行与空 URL；缺失字段默认置为 ""。
        for result in results:
            if not isinstance(result, dict):
                continue
            href = result.get("url") or ""
            if not href:
                continue
            search_results.append(
                {
                    "title": result.get("name") or "",
                    "href": href,
                    "body": result.get("snippet") or "",
                }
            )

        return search_results