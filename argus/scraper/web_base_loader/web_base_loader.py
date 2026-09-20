from bs4 import BeautifulSoup
import requests
from ..utils import extract_title

class WebBaseLoaderScraper:

    def __init__(self, link, session=None):
        self.link = link
        self.session = session or requests.Session()

    def scrape(self) -> tuple:
        """
        本函数使用 WebBaseLoader 对象抓取网页内容，并返回拼接后的页面内容。

        返回：
          `scrape` 方法返回名为 `content` 的字符串变量，其中是 `WebBaseLoader`
        所加载文档拼接后的页面内容。过程中若发生异常，会打印错误信息并返回空字符串。
        """
        try:
            from langchain_community.document_loaders import WebBaseLoader
            loader = WebBaseLoader(self.link)
            loader.requests_kwargs = {"verify": False}
            docs = loader.load() or []
            content = ""

            for doc in docs:
                if doc is None:
                    continue
                page = getattr(doc, "page_content", None)
                if page is None:
                    continue
                content += str(page)

            title = ""
            try:
                response = self.session.get(self.link)
                soup = BeautifulSoup(response.content, 'html.parser')

                # 用工具函数提取标题
                title = extract_title(soup)
            except Exception as e:
                print("Error extracting title! : " + str(e))

            return content, title

        except Exception as e:
            print("Error! : " + str(e))
            return "", ""
