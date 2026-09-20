from itertools import islice
from ..utils import check_pkg

# argus.skills.researcher._search_relevant_source_urls() 会把任何
# raw_content/body 超过 100 字符的搜索结果当成已抓取好的全文——这个
# 启发式是为那些真正在结果里内联返回全文的 retriever（如 PubMed Central）
# 设计的。ddgs 把 "body" 填成普通搜索摘要，长度经常超过 100 字符，
# 所以不做这个截断，每条结果都会被误判为已抓取，真实页面永远不会被实际
# 抓取（get_source_urls() 随后返回 []，报告里的可验证引用为零）。
# 这里在源头就做截断，而不是去改 _search_relevant_source_urls() 本身，
# 这样该函数将来的分类逻辑变更（bug 修复、新增记录）都会自动继承。
# 被截断的摘要只用于这个分类判断和早期的子查询规划——一旦某个 URL
# 走上真实抓取流程，argus 取用并使用的是真实页面内容，而不是这段摘要。
_MAX_PREFETCHED_LEN = 100


class Duckduckgo:
    """
    Duckduckgo API retriever
    """

    # ddgs 在 "body" 里返回的是摘要片段；真实页面正文仍需另行抓取。
    requires_scraping = True
    def __init__(self, query, query_domains=None):
        check_pkg('ddgs')
        from ddgs import DDGS
        self.ddg = DDGS()
        self.query = query
        self.query_domains = query_domains or None

    def search(self, max_results=5):
        """
        执行搜索，并把 ddgs 的载荷归一化成其他 retriever 共用的
        ``{href, body, title?}`` 契约。

        ``ddgs`` 早期返回带 ``href``/``body`` 键的 dict；较新版本改用
        ``link``/``url`` 以及 ``body``/``snippet``/``description``。
        下游研究步骤依赖 ``href``，若原样返回 ddgs 的原始结构，
        会抛 KeyError 或直接跳过这些来源。
        """
        # TODO: 增加对 query domains 的支持
        try:
            search_response = self.ddg.text(self.query, region='wt-wt', max_results=max_results)
        except Exception as e:
            print(f"Error: {e}. Failed fetching sources. Resulting in empty response.")
            search_response = []

        if not search_response:
            return []

        normalized = []
        for result in search_response:
            if not isinstance(result, dict):
                continue
            href = (
                result.get("href")
                or result.get("link")
                or result.get("url")
                or ""
            )
            if not href:
                continue
            body = (
                result.get("body")
                or result.get("snippet")
                or result.get("description")
                or ""
            )
            item = {"href": href, "body": body[:_MAX_PREFETCHED_LEN]}
            title = result.get("title")
            if title:
                item["title"] = title
            normalized.append(item)

        # 即使客户端忽略了 max_results，也保证返回调用方要求的条数。
        return list(islice(normalized, max_results))
