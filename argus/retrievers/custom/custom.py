from typing import Any, Dict, List
import requests
import os


class CustomRetriever:
    """
    Custom API retriever
    """

    # 约定的契约是 list[{url, raw_content}]——内容由调用方自己的 endpoint 提供。
    requires_scraping = False

    def __init__(self, query: str, query_domains=None):
        self.endpoint = os.getenv('RETRIEVER_ENDPOINT')
        if not self.endpoint:
            raise ValueError("RETRIEVER_ENDPOINT environment variable not set")

        self.params = self._populate_params()
        self.query = query

    def _populate_params(self) -> Dict[str, Any]:
        """
        从以 'RETRIEVER_ARG_' 开头的环境变量中读取参数
        """
        return {
            key[len('RETRIEVER_ARG_'):].lower(): value
            for key, value in os.environ.items()
            if key.startswith('RETRIEVER_ARG_')
        }

    def search(self, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        使用自定义 retriever endpoint 执行搜索。

        :param max_results: 最多返回的结果数（当前未使用）
        :return: 如下格式的 JSON 响应：
            [
              {
                "url": "http://example.com/page1",
                "raw_content": "Content of page 1"
              },
              {
                "url": "http://example.com/page2",
                "raw_content": "Content of page 2"
              }
            ]
        """
        try:
            response = requests.get(
                self.endpoint,
                params={**self.params, "query": self.query},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as e:
            # ValueError 覆盖 JSONDecodeError（其子类）及其他解析失败情况。
            print(f"Failed to retrieve search results: {e}")
            return []

        # 契约：调用方会遍历返回值。JSON body 为 null 或载荷不是 list 时，
        # 过去会在后续环节爆出 TypeError（或是文档里写着、却很反直觉的 Optional）。
        # 因此这里始终返回 list。
        if payload is None:
            return []
        if not isinstance(payload, list):
            print(
                "Custom retriever response must be a JSON list of "
                "{url, raw_content} objects; got "
                f"{type(payload).__name__}"
            )
            return []

        # 契约是 list[{url, raw_content}]。下游会对每个元素调用 .get，
        # 因此过滤掉非 dict 元素和没有可用 URL 的行，
        # 避免单个畸形数据把研究流水线搞崩。
        cleaned: List[Dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("href") or ""
            if not url:
                continue
            cleaned.append(
                {
                    "url": url,
                    "raw_content": item.get("raw_content") or item.get("body") or "",
                }
            )
        return cleaned
