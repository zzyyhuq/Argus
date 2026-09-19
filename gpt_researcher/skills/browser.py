"""Browser manager skill for GPT Researcher.

This module provides the BrowserManager class that handles web scraping
and content extraction from URLs.
"""

from gpt_researcher.utils.workers import WorkerPool

from ..actions.utils import stream_output
from ..actions.web_scraping import scrape_urls


class BrowserManager:
    """Manages web browsing and content scraping for research.

    This class handles URL scraping and content extraction during the
    research process.

    Attributes:
        researcher: The parent GPTResearcher instance.
        worker_pool: Pool of workers for parallel scraping.
    """

    def __init__(self, researcher):
        """Initialize the BrowserManager.

        Args:
            researcher: The GPTResearcher instance that owns this manager.
        """
        self.researcher = researcher
        self.worker_pool = WorkerPool(
            researcher.cfg.max_scraper_workers,
            researcher.cfg.scraper_rate_limit_delay
        )

    async def browse_urls(self, urls: list[str]) -> list[dict]:
        """
        Scrape content from a list of URLs.

        Args:
            urls (list[str]): list of URLs to scrape.

        Returns:
            list[dict]: list of scraped content results.
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
