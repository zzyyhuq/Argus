"""Utility functions for web scraping.

This module provides helper functions for extracting and cleaning content
from scraped HTML.
"""

import logging
import re

import bs4
from bs4 import BeautifulSoup


def extract_title(soup: BeautifulSoup) -> str:
    """Extract the title text from the BeautifulSoup object.

    Always returns a string. An empty ``<title></title>`` yields ``""`` (not
    ``None``), and a title containing nested markup (e.g.
    ``<title><span>x</span></title>``) yields its text content rather than the
    raw inner HTML.
    """
    title_tag = soup.title
    if not title_tag:
        return ""
    return title_tag.get_text(strip=True)

def clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """Clean the soup by removing unwanted tags"""
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

    # clean tags with certain classes
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
    """Get the relevant text from the soup with improved filtering"""
    if soup is None:
        return ""
    text = soup.get_text(strip=True, separator="\n")
    # Remove excess whitespace
    text = re.sub(r"\s{2,}", " ", text)
    return text
