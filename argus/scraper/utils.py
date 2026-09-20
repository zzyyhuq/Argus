"""web 抓取的工具函数。

本模块提供从抓取到的 HTML 中提取与清洗内容的辅助函数。
"""

import logging
import re

import bs4
from bs4 import BeautifulSoup


def extract_title(soup: BeautifulSoup) -> str:
    """从 BeautifulSoup 对象中提取标题文本。

    始终返回字符串。空的 ``<title></title>`` 返回 ``""``（而不是 ``None``）；
    含嵌套标签的标题（如 ``<title><span>x</span></title>``）返回其文本内容，
    而不是原始的内部 HTML。
    """
    title_tag = soup.title
    if not title_tag:
        return ""
    return title_tag.get_text(strip=True)

def clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """通过移除不需要的标签来清洗 soup"""
    for tag in soup.find_all(
        [
            "script",
            "style",
            "footer",
            "header",
            "nav",
            "menu",
            "sidebar",
            "svg",
        ]
    ):
        tag.decompose()

    disallowed_class_set = {"nav", "menu", "sidebar", "footer"}

    # 清洗带特定 class 的标签
    def does_tag_have_disallowed_class(elem) -> bool:
        if not isinstance(elem, bs4.Tag):
            return False

        return any(
            cls_name in disallowed_class_set for cls_name in elem.get("class", [])
        )

    for tag in soup.find_all(does_tag_have_disallowed_class):
        tag.decompose()

    return soup


def get_text_from_soup(soup: BeautifulSoup) -> str:
    """用改进后的过滤方式从 soup 中取出相关文本"""
    if soup is None:
        return ""
    text = soup.get_text(strip=True, separator="\n")
    # 去掉多余空白
    text = re.sub(r"\s{2,}", " ", text)
    return text
