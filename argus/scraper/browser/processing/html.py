"""HTML 处理函数"""
from __future__ import annotations

from bs4 import BeautifulSoup
from requests.compat import urljoin


def extract_hyperlinks(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """从 BeautifulSoup 对象中提取超链接

    参数：
        soup (BeautifulSoup): BeautifulSoup 对象
        base_url (str): base URL

    返回：
        List[Tuple[str, str]]: 提取出的超链接
    """
    return [
        (link.text, urljoin(base_url, link["href"]))
        for link in soup.find_all("a", href=True)
    ]


def format_hyperlinks(hyperlinks: list[tuple[str, str]]) -> list[str]:
    """把超链接格式化成便于展示给用户的形式

    参数：
        hyperlinks (List[Tuple[str, str]]): 要格式化的超链接

    返回：
        List[str]: 格式化后的超链接
    """
    return [f"{link_text} ({link_url})" for link_text, link_url in hyperlinks]
