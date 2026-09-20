import os
import json
import requests
from typing import List, Dict
from urllib.parse import urljoin

# argus.skills.researcher._search_relevant_source_urls() 会把任何
# raw_content/body 超过 100 字符的搜索结果当成已抓取好的全文——这个
# 启发式是为那些真正在结果里内联返回全文的 retriever（如 PubMed Central）
# 设计的。SearxNG 把 "body" 填成普通搜索结果摘要，长度经常超过 100 字符，
# 所以不做这个截断，每条结果都会被误判为已抓取，真实页面永远不会被实际
# 抓取（get_source_urls() 随后返回 []，报告里的可验证引用为零）。
# 这里在源头就做截断，而不是去改 _search_relevant_source_urls() 本身，
# 这样该函数将来的分类逻辑变更（bug 修复、新增记录）都会自动继承。
# 被截断的摘要只用于这个分类判断和早期的子查询规划——一旦某个 URL
# 走上真实抓取流程，argus 取用并使用的是真实页面内容，而不是这段摘要。
_MAX_PREFETCHED_LEN = 100


class SearxSearch():
    """
    SearxNG API retriever
    """

    # SearxNG 在 "content"/"body" 里放的是普通结果摘要；真实页面正文仍需另行抓取。
    requires_scraping = True
    def __init__(self, query: str, query_domains=None):
        """
        初始化 SearxSearch 对象
        参数：
            query: 搜索查询字符串
        """
        self.query = query
        self.query_domains = query_domains or None
        self.base_url = self.get_searxng_url()

    def get_searxng_url(self) -> str:
        """
        从环境变量中读取 SearxNG 实例的 URL
        返回：
            str: SearxNG 实例的 base URL
        """
        try:
            base_url = os.environ["SEARX_URL"]
            if not base_url.endswith('/'):
                base_url += '/'
            return base_url
        except KeyError:
            raise Exception(
                "SearxNG URL not found. Please set the SEARX_URL environment variable. "
                "You can find public instances at https://searx.space/"
            )

    def search(self, max_results: int = 10) -> List[Dict[str, str]]:
        """
        使用 SearxNG API 执行查询搜索
        参数：
            max_results: 最多返回的结果数
        返回：
            包含搜索结果的字典列表
        """
        search_url = urljoin(self.base_url, "search")
        # TODO: 增加对 query domains 的支持
        params = {
            # 搜索查询。
            'q': self.query,
            # 结果输出格式。该格式需要在 searxng 配置里启用。
            'format': 'json'
        }

        try:
            response = requests.get(
                search_url,
                params=params,
                headers={'Accept': 'application/json'}
            )
            response.raise_for_status()
            results = response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error querying SearxNG: {str(e)}")
        except json.JSONDecodeError:
            raise Exception("Error parsing SearxNG response")

        if not isinstance(results, dict):
            return []

        search_response = []
        raw_results = results.get('results', [])
        if not isinstance(raw_results, list):
            return []

        for result in raw_results:
            if not isinstance(result, dict):
                continue
            href = result.get('url') or result.get('href') or ''
            if not href:
                continue
            body = result.get('content') or result.get('snippet') or ''
            search_response.append({
                "href": href,
                "body": body[:_MAX_PREFETCHED_LEN],
            })
            if len(search_response) >= max_results:
                break

        return search_response
