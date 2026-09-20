import logging
import time

from bs4 import BeautifulSoup

from ..utils import extract_title, get_text_from_soup, clean_soup

logger = logging.getLogger(__name__)

# 值得重试一次的状态码：限流与临时性服务端错误。
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_CONTENT_BYTES = 10 * 1024 * 1024  # 超过 10MB 的页面直接跳过

# 页面抓取的 (connect, read) 超时，与 PyMuPDFScraper 的形式保持一致。
#
# 在这个网络环境下关键的是 connect：不可达的主机（被拦或路由不通）会在
# connect 阶段失败，而固定 10s 乘以两次尝试纯属干等，实测每个失效 URL 约
# 花 21s。可达主机完成握手的耗时远低于一秒，所以 5s 没有任何代价。
# read 保持宽松，避免响应慢但正常的大页面被截断。
FETCH_TIMEOUT = (5, 30)


class BeautifulSoupScraper:

    def __init__(self, link, session=None):
        self.link = link
        self.session = session

    def scrape(self):
        """抓取页面并提取清洗后的文本与标题。

        返回：
            (content, title) 元组。页面抓不到或没有可用内容时返回空值。
        """
        response = self._fetch()
        if response is None:
            return "", ""

        try:
            # Content-Type header 未声明 charset 时，response.encoding 默认是
            # ISO-8859-1，会把大量 UTF-8 页面解码成乱码。只有服务器确实声明了
            # charset 才采信它；否则交给 BeautifulSoup 从文档自身探测编码。
            content_type = response.headers.get("Content-Type", "")
            declared_encoding = response.encoding if "charset" in content_type.lower() else None
            soup = BeautifulSoup(
                response.content, "lxml", from_encoding=declared_encoding
            )

            soup = clean_soup(soup)

            content = get_text_from_soup(soup)

            # 用工具函数提取标题
            title = extract_title(soup)

            return content, title

        except Exception as e:
            logger.error(f"Error parsing {self.link}: {e}")
            return "", ""

    def _fetch(self):
        """GET 页面，遇到临时性失败时重试一次。

        成功时返回 response；页面不可达、状态码为错误、或大到不值得解析时返回 None。
        """
        if self.session is None:
            logger.warning(f"No session provided for {self.link}; cannot fetch")
            return None

        for attempt in (1, 2):
            try:
                response = self.session.get(self.link, timeout=FETCH_TIMEOUT)
            except Exception as e:
                logger.warning(f"Request failed for {self.link} (attempt {attempt}): {e}")
                if attempt == 1:
                    time.sleep(1)
                    continue
                return None

            if response.status_code in RETRYABLE_STATUS_CODES and attempt == 1:
                logger.warning(
                    f"Got HTTP {response.status_code} for {self.link}, retrying once"
                )
                time.sleep(1)
                continue

            if response.status_code >= 400:
                # 不要把错误页/付费墙页当成正文来解析
                logger.warning(f"Got HTTP {response.status_code} for {self.link}, skipping")
                return None

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    length_val = int(str(content_length).strip())
                except (TypeError, ValueError):
                    length_val = None
                if length_val is not None and length_val > MAX_CONTENT_BYTES:
                    logger.warning(
                        f"Content too large for {self.link} ({content_length} bytes), skipping"
                    )
                    return None

            return response

        return None
