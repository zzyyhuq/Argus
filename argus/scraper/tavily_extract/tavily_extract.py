from bs4 import BeautifulSoup
import os
from ..utils import extract_title

class TavilyExtract:

    def __init__(self, link, session=None):
        self.link = link
        self.session = session
        from tavily import TavilyClient
        self.tavily_client = TavilyClient(api_key=self.get_api_key())

    def get_api_key(self) -> str:
        """
        获取 Tavily API key
        返回：
        API key (str)
        """
        try:
            api_key = os.environ["TAVILY_API_KEY"]
        except KeyError:
            raise Exception(
                "Tavily API key not found. Please set the TAVILY_API_KEY environment variable.")
        return api_key

    def scrape(self) -> tuple:
        """
        本函数使用 Tavily Python SDK 从指定链接中提取内容；链接中的标题与图片
        则由 `argus/scraper/utils.py` 中的函数提取。

        返回：
          `scrape` 方法返回一个元组，包含提取到的内容、图片 URL 列表，
        以及 `self.link` 所指网页的标题。它用 Tavily Python SDK 从网页中
        提取并清洗内容。过程中若发生任何异常，会打印错误信息并返回空结果。
        """

        try:
            response = self.tavily_client.extract(urls=self.link)
            if not isinstance(response, dict):
                return "", ""

            # failed_results 可能缺失、为 null，或是一个非空列表。
            failed = response.get("failed_results") or []
            if failed:
                return "", ""

            results = response.get("results") or []
            if not isinstance(results, list) or not results:
                return "", ""
            first = results[0]
            if not isinstance(first, dict):
                return "", ""
            # 优先用 raw_content；提取载荷不完整时也不会抛 KeyError。
            content = first.get("raw_content") or ""
            if not content:
                return "", ""

            # 取标题的可选 HTML 旁路。session 可能未设置
            # （构造函数默认 session=None）——这里直接把这条路封掉，
            # 而不是让它在宽泛的 except 里抛 AttributeError。
            title = ""
            if self.session is not None:
                response_bs = self.session.get(self.link, timeout=4)
                soup = BeautifulSoup(
                    response_bs.content, "lxml", from_encoding=response_bs.encoding
                )
                title = extract_title(soup) or ""

            return content, title

        except Exception as e:
            print("Error! : " + str(e))
            return "", ""
