"""Argus 的浏览器管理技能。

本模块提供 BrowserManager 类，负责网页抓取与从 URL 提取正文。
"""

from argus.utils.workers import WorkerPool

from ..actions.utils import stream_output
from ..actions.web_scraping import scrape_urls


class BrowserManager:
    """负责研究过程中的网页浏览与内容抓取。

    本类在检索过程中处理 URL 抓取与正文提取。

    属性：
        researcher: 持有该管理器的父级 Argus 实例。
        worker_pool: 用于并发抓取的 worker 池。
    """

    def __init__(self, researcher):
        """初始化 BrowserManager。

        参数：
            researcher: 持有该管理器的 Argus 实例。
        """
        self.researcher = researcher
        self.worker_pool = WorkerPool(
            researcher.cfg.max_scraper_workers,
            researcher.cfg.scraper_rate_limit_delay
        )

    async def browse_urls(self, urls: list[str]) -> list[dict]:
        """
        从一组 URL 中抓取正文。

        参数：
            urls (list[str]): 待抓取的 URL 列表。

        返回：
            list[dict]: 抓取结果列表。
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "scraping_urls",
                f"🌐 Scraping content from {len(urls)} URLs...",
                self.researcher.websocket,
            )

        scraped_content = await scrape_urls(
            urls, self.researcher.cfg, self.worker_pool
        )
        self.researcher.add_research_sources(scraped_content)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "scraping_content",
                f"📄 Scraped {len(scraped_content)} pages of content",
                self.researcher.websocket,
            )
            await stream_output(
                "logs",
                "scraping_complete",
                f"🌐 Scraping complete",
                self.researcher.websocket,
            )

        return scraped_content
