"""使用仍在维护的 `arxiv` Client API 抓取 arXiv 论文。

避开 langchain_community.ArxivRetriever——它仍在调用已被移除的
`arxiv.Search.results()` 方法（在 arxiv>=2.2 上已失效）。
"""

from __future__ import annotations

import re


_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/)?(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+/\d{7})(?:\.pdf)?",
    re.IGNORECASE,
)


def _paper_id_from_link(link: str) -> str:
    """从 URL 或裸 id 字符串中提取 arXiv id。"""
    if not link:
        return ""
    m = _ID_RE.search(link.strip())
    if m:
        return m.group("id")
    # 回退到取最后一段路径（沿袭旧行为）
    return link.rstrip("/").split("/")[-1].removesuffix(".pdf")


class ArxivScraper:
    def __init__(self, link, session=None):
        self.link = link
        self.session = session

    def scrape(self):
        """通过 arxiv.Client 获取论文摘要/内容。

        返回：
            (context, title)，与其他 scraper 保持一致。

        当查询匹配不到论文时（id 畸形/非 arXiv，或 client 结果为空），
        降级为空结果而不是抛异常，避免单个坏 URL 中断整条抓取流水线。
        """
        paper_id = _paper_id_from_link(self.link)
        if not paper_id:
            return "", ""

        import arxiv

        client = arxiv.Client()
        search = arxiv.Search(id_list=[paper_id], max_results=1)
        try:
            paper = next(client.results(search))
        except StopIteration:
            # 没有匹配的论文——与其他 scraper 一致：降级为空结果。
            return "", ""

        authors = ", ".join(a.name for a in (paper.authors or []))
        published = paper.published.date().isoformat() if paper.published else ""
        summary = paper.summary or ""
        title = paper.title or paper_id

        context = (
            f"Published: {published}; Author: {authors}; Content: {summary}"
        )
        return context, title
