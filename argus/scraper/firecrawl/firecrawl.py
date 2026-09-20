import asyncio
import os

# 模块级 semaphore，所有 FireCrawl 实例共用。
# 用于限制并发 API 调用，避免超出 FireCrawl 的限流。
# FireCrawl 免费套餐允许 2 个并发浏览器；可通过 FIRECRAWL_CONCURRENCY 配置。
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
        获取 FireCrawl API key
        返回：
        API key (str)
        """
        try:
            api_key = os.environ["FIRECRAWL_API_KEY"]
        except KeyError:
            raise Exception(
                "FireCrawl API key not found. Please set the FIRECRAWL_API_KEY environment variable.")
        return api_key

    def get_server_url(self) -> str:
        """
        获取 FireCrawl 的服务器 URL。
        默认使用官方 FireCrawl 服务器（'https://api.firecrawl.dev'）。
        返回：
        服务器 url (str)
        """
        try:
            server_url = os.environ["FIRECRAWL_SERVER_URL"]
        except KeyError:
            server_url = 'https://api.firecrawl.dev'
        return server_url

    def scrape(self) -> tuple:
        """
        本函数使用 FireCrawl Python SDK 从指定链接中提取内容与标题。

        返回：
          `scrape` 方法返回由提取到的内容和页面标题组成的元组。
        过程中若发生任何异常，会打印错误信息并返回空结果。
        """

        try:
            # 已修复：为匹配 FireCrawl SDK v4.6.0+，由 scrape_url() 改为 scrape()
            response = self.firecrawl.scrape(url=self.link, formats=["markdown"])

            # 检查页面是否抓取成功
            # 已修复：直接访问 metadata 的属性（而非当作 dict 的键）
            if response.metadata and response.metadata.error:
                print("Scrape failed! : " + str(response.metadata.error))
                return "", ""
            elif response.metadata and response.metadata.status_code and response.metadata.status_code != 200:
                print(f"Scrape failed! Status code: {response.metadata.status_code}")
                return "", ""

            # 从 FireCrawl 响应中提取内容（markdown）与标题
            # 已修复：直接访问属性（而非当作 dict 的键）
            content = response.markdown if response.markdown else ""
            title = response.metadata.title if response.metadata and response.metadata.title else ""

            return content, title

        except Exception as e:
            print("Error! : " + str(e))
            return "", ""

    async def scrape_async(self) -> tuple:
        """
        scrape() 的异步版本，带并发限制以避免触发 FireCrawl API 限流。

        FireCrawl 免费套餐把并发浏览器数限制为 2。深度研究模式会发起大量并行请求，
        其中大部分会静默失败并返回空内容。本方法使用模块级共享 semaphore，
        让所有 FireCrawl 实例合计最多同时运行 FIRECRAWL_CONCURRENCY 个请求（默认 2）。

        返回：
            (content, title) 元组——与 scrape() 相同。
        """
        async with _get_semaphore():
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.scrape)
