import asyncio
import os

# Module-level semaphore shared across all FireCrawl instances.
# Limits concurrent API calls to avoid exceeding FireCrawl rate limits.
# FireCrawl Free Tier allows 2 concurrent browsers; configurable via FIRECRAWL_CONCURRENCY.
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        max_concurrent = int(os.environ.get("FIRECRAWL_CONCURRENCY", "2"))
        _semaphore = asyncio.Semaphore(max_concurrent)
    return _semaphore


class FireCrawl:

    def __init__(self, link, session=None):
        self.link = link
        self.session = session
        from firecrawl import FirecrawlApp
        self.firecrawl = FirecrawlApp(api_key=self.get_api_key(), api_url=self.get_server_url())

    def get_api_key(self) -> str:
        """
        Gets the FireCrawl API key
        Returns:
        Api key (str)
        """
        try:
            api_key = os.environ["FIRECRAWL_API_KEY"]
        except KeyError:
            raise Exception(
                "FireCrawl API key not found. Please set the FIRECRAWL_API_KEY environment variable.")
        return api_key

    def get_server_url(self) -> str:
        """
        Gets the FireCrawl server URL.
        Default to official FireCrawl server ('https://api.firecrawl.dev').
        Returns:
        server url (str)
        """
        try:
            server_url = os.environ["FIRECRAWL_SERVER_URL"]
        except KeyError:
            server_url = 'https://api.firecrawl.dev'
        return server_url

    def scrape(self) -> tuple:
        """
        This function extracts content and title from a specified link using the FireCrawl Python SDK.

        Returns:
          The `scrape` method returns a tuple of the extracted content and the page title. If any
        exception occurs during the process, an error message is printed and an empty result is
        returned.
        """

        try:
            # Fixed: Changed from scrape_url() to scrape() to match FireCrawl SDK v4.6.0+
            response = self.firecrawl.scrape(url=self.link, formats=["markdown"])

            # Check if the page has been scraped successfully
            # Fixed: Access metadata attributes directly (not as dict keys)
            if response.metadata and response.metadata.error:
                print("Scrape failed! : " + str(response.metadata.error))
                return "", ""
            elif response.metadata and response.metadata.status_code and response.metadata.status_code != 200:
                print(f"Scrape failed! Status code: {response.metadata.status_code}")
                return "", ""

            # Extract the content (markdown) and title from FireCrawl response
            # Fixed: Access attributes directly (not as dict keys)
            content = response.markdown if response.markdown else ""
            title = response.metadata.title if response.metadata and response.metadata.title else ""

            return content, title

        except Exception as e:
            print("Error! : " + str(e))
            return "", ""

    async def scrape_async(self) -> tuple:
        """
        Async version of scrape() with concurrency limiting to avoid FireCrawl API rate limits.

        FireCrawl Free Tier limits concurrent browsers to 2. When deep research mode launches
        many parallel requests, most fail silently with empty content. This method uses a shared
        module-level semaphore so that at most FIRECRAWL_CONCURRENCY requests run simultaneously
        across all FireCrawl instances (default: 2).

        Returns:
            Tuple of (content, title) — same as scrape().
        """
        async with _get_semaphore():
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.scrape)
