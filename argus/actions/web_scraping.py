from typing import Any
from colorama import Fore, Style

from argus.utils.workers import WorkerPool
from ..scraper import Scraper
from ..config.config import Config
from ..utils.logger import get_formatted_logger

logger = get_formatted_logger()


async def scrape_urls(
    urls, cfg: Config, worker_pool: WorkerPool
) -> list[dict[str, Any]]:
    """
    抓取这些 URL

    参数：
        urls: URL 列表
        cfg: Config（可选）

    返回：
        list[dict[str, Any]]: 抓取到的页面内容

    """
    scraped_data = []
    user_agent = (
        cfg.user_agent
        if cfg
        else "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    scraper = None
    try:
        scraper = Scraper(urls, user_agent, cfg.scraper, worker_pool=worker_pool)
        scraped_data = await scraper.run()
    except Exception as e:
        print(f"{Fore.RED}Error in scrape_urls: {e}{Style.RESET_ALL}")
    finally:
        # 关闭 requests.Session，以释放其底层连接池（以及它保活的 socket）
        if scraper is not None and getattr(scraper, "session", None) is not None:
            scraper.session.close()

    return scraped_data


async def filter_urls(urls: list[str], config: Config) -> list[str]:
    """
    根据配置过滤 URL。

    参数：
        urls (list[str]): 要过滤的 URL 列表。
        config (Config): 配置对象。

    返回：
        list[str]: 过滤后的 URL 列表。
    """
    filtered_urls = []
    excluded = getattr(config, "excluded_domains", None) or []
    if not isinstance(excluded, (list, tuple, set)):
        excluded = []
    for url in urls or []:
        # URL 必须是非空字符串；null/int 之类的噪声会让排除域名的子串
        # 判断抛 TypeError。
        if not isinstance(url, str) or not url:
            continue
        if not any(isinstance(ex, str) and ex and ex in url for ex in excluded):
            filtered_urls.append(url)
    return filtered_urls

async def extract_main_content(html_content: str) -> str:
    """
    从 HTML 中提取正文内容。

    参数：
        html_content (str): 原始 HTML 内容。

    返回：
        str: 提取出的正文内容。
    """
    # 在这里实现正文提取逻辑
    # 可以用 BeautifulSoup 之类的库，或自写解析逻辑
    # 目前先直接返回原始 HTML 作为占位
    return html_content

async def process_scraped_data(scraped_data: list[dict[str, Any]], config: Config) -> list[dict[str, Any]]:
    """
    处理抓取到的数据，提取并清洗正文内容。

    参数：
        scraped_data (list[dict[str, Any]]): 含抓取数据的字典列表。
        config (Config): 配置对象。

    返回：
        list[dict[str, Any]]: 处理后的抓取数据。
    """
    processed_data = []
    for item in scraped_data:
        if not isinstance(item, dict):
            continue
        # 以前对不完整的 scraper 返回体用严格取键，会在一批的中途崩掉；
        # 这里的跳过/原样回写保护能让本轮剩下的继续跑完。
        status = item.get("status")
        if status == "success":
            main_content = await extract_main_content(item.get("content") or "")
            processed_data.append({
                "url": item.get("url") or "",
                "content": main_content,
                "status": "success",
            })
        else:
            processed_data.append(item)
    return processed_data
