from __future__ import annotations

import traceback
import pickle
from pathlib import Path
from sys import platform
import time
import random
import string
import os

from bs4 import BeautifulSoup
from typing import Iterable, cast

from .processing.scrape_skills import (scrape_pdf_with_pymupdf,
                                       scrape_pdf_with_arxiv)

from urllib.parse import urljoin, urlparse


def _is_pdf_url(url: str) -> bool:
    """当 ``url`` 指向 PDF 时返回 True。

    只检查 path 部分，避免 query string / fragment 把扩展名藏起来
    （``https://host/doc.pdf?sig=...`` 这类带签名的 CDN/S3 链接非常常见）；
    匹配时忽略大小写，因为 ``.PDF`` 也是完全合法的后缀。
    """
    if not url:
        return False
    return urlparse(url).path.lower().endswith(".pdf")

from ..utils import extract_title, get_text_from_soup, clean_soup

FILE_DIR = Path(__file__).parent.parent

class BrowserScraper:
    def __init__(self, url: str, session=None):
        self.url = url
        self.session = session
        self.selenium_web_browser = "chrome"
        self.headless = False
        self.user_agent = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/128.0.0.0 Safari/537.36")
        self.driver = None
        self.use_browser_cookies = False
        self._import_selenium()  # 仅在用到时才导入，避免引入不必要的依赖
        self.cookie_filename = f"{self._generate_random_string(8)}.pkl"

    def scrape(self) -> tuple:
        if not self.url:
            print("URL not specified")
            return "", ""

        try:
            self.setup_driver()
            self._visit_google_and_save_cookies()
            self._load_saved_cookies()
            self._add_header()

            text, title = self.scrape_text_with_selenium()
            return text, title
        except Exception as e:
            print(f"An error occurred during scraping: {str(e)}")
            print("Full stack trace:")
            print(traceback.format_exc())
            # 返回空内容让这次失败被丢弃，
            # 而不是让错误文本在下游被当成页面正文。
            return "", ""
        finally:
            if self.driver:
                self.driver.quit()
            self._cleanup_cookie_file()

    def _import_selenium(self):
        try:
            global webdriver, By, EC, WebDriverWait, TimeoutException, WebDriverException
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.wait import WebDriverWait
            from selenium.common.exceptions import TimeoutException, WebDriverException

            global ChromeOptions, FirefoxOptions, SafariOptions
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            from selenium.webdriver.firefox.options import Options as FirefoxOptions
            from selenium.webdriver.safari.options import Options as SafariOptions
        except ImportError as e:
            print(f"Failed to import Selenium: {str(e)}")
            print("Please install Selenium and its dependencies to use BrowserScraper.")
            print("You can install Selenium using pip:")
            print("    pip install selenium")
            print("If you're using a virtual environment, make sure it's activated.")
            raise ImportError(
                "Selenium is required but not installed. See error message above for installation instructions.") from e

    def setup_driver(self) -> None:
        # print(f"Setting up {self.selenium_web_browser} driver...")

        options_available = {
            "chrome": ChromeOptions,
            "firefox": FirefoxOptions,
            "safari": SafariOptions,
        }

        options = options_available[self.selenium_web_browser]()
        options.add_argument(f"user-agent={self.user_agent}")
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--enable-javascript")

        try:
            if self.selenium_web_browser == "firefox":
                self.driver = webdriver.Firefox(options=options)
            elif self.selenium_web_browser == "safari":
                self.driver = webdriver.Safari(options=options)
            else:  # chrome
                if platform == "linux" or platform == "linux2":
                    options.add_argument("--disable-dev-shm-usage")
                    options.add_argument("--remote-debugging-port=9222")
                options.add_argument("--no-sandbox")
                options.add_experimental_option("prefs", {"download_restrictions": 3})
                self.driver = webdriver.Chrome(options=options)

            if self.use_browser_cookies:
                self._load_browser_cookies()

            # print(f"{self.selenium_web_browser.capitalize()} driver set up successfully.")
        except Exception as e:
            print(f"Failed to set up {self.selenium_web_browser} driver: {str(e)}")
            print("Full stack trace:")
            print(traceback.format_exc())
            raise

    def _load_saved_cookies(self):
        """在访问目标 URL 之前载入已保存的 cookie"""
        cookie_file = Path(self.cookie_filename)
        if cookie_file.exists():
            cookies = pickle.load(open(self.cookie_filename, "rb"))
            for cookie in cookies:
                self.driver.add_cookie(cookie)
        else:
            print("No saved cookies found.")

    def _load_browser_cookies(self):
        """直接从浏览器中载入 cookie"""
        try:
            import browser_cookie3
        except ImportError:
            print(
                "browser_cookie3 is not installed. Please install it using: pip install browser_cookie3"
            )
            return

        if self.selenium_web_browser == "chrome":
            cookies = browser_cookie3.chrome()
        elif self.selenium_web_browser == "firefox":
            cookies = browser_cookie3.firefox()
        else:
            print(f"Cookie loading not supported for {self.selenium_web_browser}")
            return

        for cookie in cookies:
            self.driver.add_cookie({'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain})

    def _cleanup_cookie_file(self):
        """删除 cookie 文件"""
        cookie_file = Path(self.cookie_filename)
        if cookie_file.exists():
            try:
                os.remove(self.cookie_filename)
            except Exception as e:
                print(f"Failed to remove cookie file: {str(e)}")
        else:
            print("No cookie file found to remove.")

    def _generate_random_string(self, length):
        """生成指定长度的随机字符串"""
        return "".join(random.choices(string.ascii_letters + string.digits, k=length))

    def _get_domain(self):
        """从 URL 中提取域名"""
        from urllib.parse import urlparse

        """Get domain from URL, removing 'www' if present"""
        domain = urlparse(self.url).netloc
        return domain[4:] if domain.startswith("www.") else domain

    def _visit_google_and_save_cookies(self):
        """在跳转到目标 URL 前先访问 Google 并保存 cookie"""
        try:
            self.driver.get("https://www.google.com")
            time.sleep(2)  # 等待 cookie 写入

            # 把 cookie 保存到文件
            cookies = self.driver.get_cookies()
            pickle.dump(cookies, open(self.cookie_filename, "wb"))

            # print("Google cookies saved successfully.")
        except Exception as e:
            print(f"Failed to visit Google and save cookies: {str(e)}")
            print("Full stack trace:")
            print(traceback.format_exc())

    def scrape_text_with_selenium(self) -> tuple:
        self.driver.get(self.url)

        try:
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except TimeoutException as e:
            print("Timed out waiting for page to load")
            print(f"Full stack trace:\n{traceback.format_exc()}")
            return "Page load timed out", ""

        self._scroll_to_bottom()

        if _is_pdf_url(self.url):
            text = scrape_pdf_with_pymupdf(self.url)
            return text, ""
        elif "arxiv" in self.url:
            doc_num = self.url.split("/")[-1]
            text = scrape_pdf_with_arxiv(doc_num)
            return text, ""
        else:
            page_source = self.driver.execute_script(
                "return document.documentElement.outerHTML;"
            )
            soup = BeautifulSoup(page_source, "lxml")

            soup = clean_soup(soup)

            text = get_text_from_soup(soup)
            title = extract_title(soup)

        return text, title

    def _scroll_to_bottom(self):
        """滚动到页面底部，以加载全部内容"""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        while True:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # 等待内容加载
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    def _scroll_to_percentage(self, ratio: float) -> None:
        """滚动到页面的指定百分比位置"""
        if ratio < 0 or ratio > 1:
            raise ValueError("Percentage should be between 0 and 1")
        self.driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {ratio});")

    def _add_header(self) -> None:
        """为网站添加一个 header"""
        self.driver.execute_script(open(f"{FILE_DIR}/browser/js/overlay.js", "r").read())
