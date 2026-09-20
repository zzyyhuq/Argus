"""Argus 的 web scraper 模块。

本模块提供 Scraper 类，用多种 scraper 后端（BeautifulSoup、PyMuPDF、
Browser 等）从 URL 中提取内容。
"""

import asyncio
import importlib
import logging
import subprocess
import sys
from urllib.parse import urlparse

import requests
from colorama import Fore, init

from argus.utils.workers import WorkerPool
from argus.utils.url_security import UnsafeURLError, validate_url

from . import (
    ArxivScraper,
    BeautifulSoupScraper,
    BrowserScraper,
    FireCrawl,
    NoDriverScraper,
    PyMuPDFScraper,
    TavilyExtract,
    WebBaseLoaderScraper,
)

# 已知的反爬/挑战页标记，忽略大小写的子串匹配。
# 这类页面会返回 HTTP 200 和真实（往往很大）的 HTML body，因此异常和下面的
# 短内容检查都拦不住——没有这一层，拦截/挑战页就会被当成文章真实内容吃进来。
# 每个标记都取得足够具体，避免与普通行文相撞（例如用
# "researchgate - temporarily unavailable"，而不用光秃秃的
# "temporarily unavailable"——一篇讲别处故障的正常文章完全可能包含这句话）。
# 这里并不穷尽；实践中发现新的拦截页时再补充。
_BLOCK_PAGE_MARKERS = (
    "anubis uses a proof-of-work scheme",  # HAL 及其他以 Anubis 前置的站点
    "making sure you're not a bot",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
    "researchgate - temporarily unavailable",  # ResearchGate 特有的措辞
    "please verify you are a human",
    "attention required! | cloudflare",
    "sorry, you have been blocked",
)

# 拦截页就是整个响应体——一句"请稍候"的提示，而不是真正的文章——所以它们
# 总是很短，并且总是出现在内容的开头。只检查前缀，可以避免每次抓取都对几 MB
# 的正常文档做小写转换并全文扫描。
_BLOCK_PAGE_CHECK_PREFIX_LEN = 5_000

# 词表/词汇表转储（互不相关的单词平铺罗列、没有行文）会被干净地抓下来，
# 又因为词面上几乎能匹配任何查询，很容易占据报告上下文的大头。相对于自身体量，
# 它们的句末标点几乎为零，这点与任何真正的行文都不同（即便是密集的技术写作，
# 也大约每 100-200 字符就有一个句号）。这里不单看体量——正常的长文档是存在的
# ——只检查"体量确实大"且"句子结构几乎完全缺失"同时成立，
# 以压低对真实内容的误判率。除拉丁标点外，也把 CJK 全角句末符（。！？）算进来，
# 这样长篇中文/日文/韩文行文——它们从不用 "." "!" "?"——
# 就不会仅仅因为缺少 ASCII 标点而被误判为词表。
_MIN_LENGTH_FOR_WORDLIST_CHECK = 200_000
_MAX_SENTENCE_DENSITY = 1 / 5000  # 每 5000 字符至多 1 个句末符
_SENTENCE_ENDING_CHARS = frozenset(".!?。！？")


def _looks_like_block_page(text: str) -> bool:
    prefix = text[:_BLOCK_PAGE_CHECK_PREFIX_LEN].lower()
    return any(marker in prefix for marker in _BLOCK_PAGE_MARKERS)


def _looks_like_word_list(text: str) -> bool:
    if len(text) < _MIN_LENGTH_FOR_WORDLIST_CHECK:
        return False
    sentence_endings = sum(1 for ch in text if ch in _SENTENCE_ENDING_CHARS)
    return (sentence_endings / len(text)) < _MAX_SENTENCE_DENSITY


# get_scraper() 依据 URL 后缀挑选后端，但机构仓库（DSpace/EPrints 风格的
# 下载端点）提供的 PDF 是按 content type 路由的，没有文件扩展名——例如
# "scholarspace.manoa.hawaii.edu/bitstreams/<uuid>/download" 就没有。这类
# 链接会落到 text/HTML 的 scraper 上，而它根本无法解码 PDF 内容，于是把
# PDF 的原始字节（FlateDecode 流、xref 表、/Annot 对象）当成页面真实文本
# 返回——而且是静默的：不抛异常，content_length 看着也正常，内容却不可用。
#
# 下面这些 token 是 PDF 自身的内部结构语法；即便巧合，它们也几乎不会出现在
# 真正的行文里。命中两个相互独立的 token，就足以确信这是原始 PDF，而不是
# 恰好包含其中某一个词的普通文本。
_PDF_STRUCTURE_MARKERS = ("endobj", "endstream", "/FlateDecode", "xref", "trailer")
_MIN_PDF_MARKER_HITS = 2


def _looks_like_unextracted_pdf(text: str) -> bool:
    if text.startswith("%PDF-"):
        return True
    hits = sum(1 for marker in _PDF_STRUCTURE_MARKERS if marker in text)
    return hits >= _MIN_PDF_MARKER_HITS


class Scraper:
    """
    Scraper 类，用于从链接中提取内容
    """

    def __init__(self, urls, user_agent, scraper, worker_pool: WorkerPool):
        """
        初始化 Scraper 类。
        参数：
            urls: 要抓取的 URL 列表（会去掉重复项）
        """
        # 优化：去掉重复 URL，避免重复抓取
        unique_urls = list(dict.fromkeys(urls))  # 去重的同时保持原顺序
        duplicates_removed = len(urls) - len(unique_urls)

        self.urls = unique_urls
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.scraper = scraper
        if self.scraper == "tavily_extract":
            self._check_pkg(self.scraper)
        if self.scraper == "firecrawl":
            self._check_pkg(self.scraper)
        self.logger = logging.getLogger(__name__)
        self.worker_pool = worker_pool

        # 若发现重复项，记录去重结果
        if duplicates_removed > 0:
            self.logger.info(
                f"Removed {duplicates_removed} duplicate URL(s). "
                f"Scraping {len(unique_urls)} unique URLs instead of {len(urls)}."
            )

    async def run(self):
        """
        从链接中提取内容
        """
        contents = await asyncio.gather(
            *(self.extract_data_from_url(url, self.session) for url in self.urls)
        )

        # extract_data_from_url 按约定返回 dict，但后端有 bug 或 worker 被取消时
        # 仍可能返回 None / 非 dict。对它们做 content["raw_content"] 取值会让整个
        # gather 结果崩掉，连带丢掉正常的行。
        res = [
            content
            for content in contents
            if isinstance(content, dict) and content.get("raw_content") is not None
        ]
        return res

    def _check_pkg(self, scrapper_name: str) -> None:
        """
        为那些需要 requirements.txt 之外依赖的 scraper 检查并确保所需的 Python 包已安装。
        往仓库里新增 scraper 时，请把它的依赖信息补进 `pkg_map`，
        并在初始化时调用 check_pkg()。
        """
        pkg_map = {
            "tavily_extract": {
                "package_installation_name": "tavily-python",
                "import_name": "tavily",
            },
            "firecrawl": {
                "package_installation_name": "firecrawl-py",
                "import_name": "firecrawl",
            },
        }
        pkg = pkg_map[scrapper_name]
        if not importlib.util.find_spec(pkg["import_name"]):
            pkg_inst_name = pkg["package_installation_name"]
            init(autoreset=True)
            print(Fore.YELLOW + f"{pkg_inst_name} not found. Attempting to install...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg_inst_name]
                )
                importlib.invalidate_caches()
                print(Fore.GREEN + f"{pkg_inst_name} installed successfully.")
            except subprocess.CalledProcessError:
                raise ImportError(
                    Fore.RED
                    + f"Unable to install {pkg_inst_name}. Please install manually with "
                    f"`pip install -U {pkg_inst_name}`"
                )

    async def extract_data_from_url(self, link, session):
        """
        从链接中提取数据，并带日志记录
        """
        async with self.worker_pool.throttle():
            try:
                # 在发出任何请求之前，先拒绝 SSRF / 本地文件类目标（内网主机、
                # 云 metadata 端点、file:// 路径等）。
                try:
                    validate_url(link)
                except UnsafeURLError as e:
                    self.logger.warning(f"Skipping unsafe URL {link}: {e}")
                    return {
                        "url": link,
                        "raw_content": None,
                        "title": "",
                    }

                Scraper = self.get_scraper(link)
                scraper = Scraper(link, session)

                # 取 scraper 名称
                scraper_name = scraper.__class__.__name__
                self.logger.info(f"\n=== Using {scraper_name} ===")

                # 获取内容
                if hasattr(scraper, "scrape_async"):
                    content, title = await scraper.scrape_async()
                else:
                    content, title = await asyncio.get_running_loop().run_in_executor(
                        self.worker_pool.executor, scraper.scrape
                    )

                if not content or len(content) < 100:
                    return self._reject(link, title, "Content too short or empty")

                # 记录结果
                self.logger.info(f"\nTitle: {title}")
                self.logger.info(f"Content length: {len(content)} characters")
                self.logger.info(f"URL: {link}")
                self.logger.info("=" * 50)

                if _looks_like_block_page(content):
                    return self._reject(link, title, "Anti-bot/challenge page detected")

                if _looks_like_word_list(content):
                    return self._reject(link, title, "Word-list-like content detected")

                if _looks_like_unextracted_pdf(content) and Scraper is not PyMuPDFScraper:
                    self.logger.warning(
                        f"{link} looks like unextracted PDF binary via {scraper_name} "
                        f"(no .pdf suffix, so get_scraper() didn't route it to "
                        f"PyMuPDFScraper) -- retrying with PyMuPDFScraper"
                    )
                    retried = await self._retry_as_pdf(link, session)
                    if retried is not None:
                        return retried
                    self.logger.warning(f"PyMuPDFScraper retry also failed for {link}")
                    return {
                        "url": link,
                        "raw_content": None,
                        "title": title,
                    }

                return {
                    "url": link,
                    "raw_content": content,
                    "title": title,
                }

            except Exception as e:
                self.logger.error(f"Error processing {link}: {str(e)}")
                return {"url": link, "raw_content": None, "title": ""}

    def _reject(self, link, title, reason):
        """把"抓到了但不可用"的页面按抓取失败处理，返回结构与抛异常或内容
        过短时已有的返回一致——下游代码（Scraper.run）会丢弃
        任何 raw_content: None 的记录。"""
        self.logger.warning(f"{reason} for {link}, treating as fetch failure")
        return {"url": link, "raw_content": None, "title": title}


    async def _retry_as_pdf(self, link, session):
        """get_scraper() 最初挑中的 scraper 返回了未抽取的 PDF 二进制后，
        改用 PyMuPDFScraper 重新抓取该链接。

        成功时返回 extract_data_from_url 的常规结果 dict；若重试仍拿不到可用
        内容则返回 None（这样调用方会退回按普通抓取失败处理，
        而不是把二进制内容放行到下游）。
        """
        scraper = PyMuPDFScraper(link, session)
        content, title = await asyncio.get_running_loop().run_in_executor(
            self.worker_pool.executor, scraper.scrape
        )
        if not content or len(content) < 100:
            return None
        self.logger.info(f"PyMuPDFScraper retry recovered {len(content)} characters for {link}")
        return {
            "url": link,
            "raw_content": content,
            "title": title,
        }

    def get_scraper(self, link):
        """
        `get_scraper` 函数根据传入的链接确定合适的 scraper 类，没有匹配项时回退到默认 scraper。

        参数：
          link: `get_scraper` 接收 `link` 参数，它是指向网页或 PDF 文件的 URL。方法根据链接
        指向的内容类型，判断该用哪个 scraper 类来提取数据。

        返回：
          `get_scraper` 根据传入的链接返回对应的 scraper 类。方法依据 `SCRAPER_CLASSES`
        字典中预定义的映射判断该用哪个 scraper 类。链接以 ".pdf" 结尾时选中
        `PyMuPDFScraper`；链接含 "arxiv.org" 时选中 `ArxivScraper
        """

        SCRAPER_CLASSES = {
            "pdf": PyMuPDFScraper,
            "arxiv": ArxivScraper,
            "bs": BeautifulSoupScraper,
            "web_base_loader": WebBaseLoaderScraper,
            "browser": BrowserScraper,
            "nodriver": NoDriverScraper,
            "tavily_extract": TavilyExtract,
            "firecrawl": FireCrawl,
        }

        scraper_key = None

        # 只检查 path 部分，避免 query string / fragment 把扩展名藏起来
        # （例如 "…/doc.pdf?sig=…" 这类带签名的 CDN/S3 链接）。
        # 匹配时忽略大小写，因为 ".PDF" 也是完全合法的后缀。
        path = urlparse(link).path
        if path.lower().endswith(".pdf"):
            scraper_key = "pdf"
        elif "arxiv.org" in link:
            scraper_key = "arxiv"
        else:
            scraper_key = self.scraper

        scraper_class = SCRAPER_CLASSES.get(scraper_key)
        if scraper_class is None:
            raise Exception("Scraper not found.")

        return scraper_class
