import os
import requests
import tempfile
from urllib.parse import urlparse
from langchain_community.document_loaders import PyMuPDFLoader


class PyMuPDFScraper:

    def __init__(self, link, session=None):
        """
        用链接和可选的 session 初始化 scraper。

        参数：
          link (str): PDF 文档的 URL 或本地文件路径。
          session (requests.Session, optional): 可选的、用于发起 HTTP 请求的 session。
        """
        self.link = link
        self.session = session

    def is_url(self) -> bool:
        """
        检查给定的 `link` 是否为合法 URL。

        返回：
          bool: 链接是合法 URL 时为 True，否则为 False。
        """
        try:
            result = urlparse(self.link)
            return all([result.scheme, result.netloc])  # 检查 scheme 与网络位置是否有效
        except Exception:
            return False

    def scrape(self) -> tuple[str, str]:
        """
        `scrape` 用 PyMuPDFLoader 从给定链接（URL 或本地文件）加载文档，
        并返回其文本与标题。

        返回：
          tuple[str, str]: 已加载文档的内容与标题。
        """
        try:
            if self.is_url():
                http = self.session or requests
                try:
                    response = http.get(self.link, timeout=(5, 30), stream=True)
                    response.raise_for_status()
                except requests.exceptions.SSLError:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"SSL verification failed for {self.link}, retrying without verification"
                    )
                    response = http.get(self.link, timeout=(5, 30), stream=True, verify=False)
                    response.raise_for_status()

                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                    temp_filename = temp_file.name  # 取临时文件名
                    for chunk in response.iter_content(chunk_size=8192):
                        temp_file.write(chunk)  # 把下载到的内容写入临时文件

                # 无论加载是否失败都要清理下载的临时文件
                # （PyMuPDFLoader.load() 遇到畸形/不完整的 PDF 会抛异常）。
                try:
                    loader = PyMuPDFLoader(temp_filename)
                    doc = loader.load()
                finally:
                    try:
                        os.remove(temp_filename)
                    except OSError:
                        pass
            else:
                loader = PyMuPDFLoader(self.link)
                doc = loader.load()

            # 从文档中提取内容与标题。
            # 取所有页面的内容，确保带封面的 PDF 也能通过校验。
            content = "\n".join(page.page_content for page in doc)
            title = doc[0].metadata.get("title", "") if doc else ""
            return content, title

        except requests.exceptions.Timeout:
            print(f"Download timed out. Please check the link : {self.link}")
            return "", ""
        except Exception as e:
            print(f"Error loading PDF : {self.link} {e}")
            return "", ""
