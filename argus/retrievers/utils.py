"""Argus retriever 的工具函数。

本模块提供各类 search retriever 实现共用的辅助函数与常量。
"""

import importlib.util
import logging
import os
import sys

logger = logging.getLogger(__name__)

async def stream_output(log_type, step, content, websocket=None, with_data=False, data=None):
    """
    把输出流式发送给客户端。

    参数：
        log_type (str): 日志类型
        step (str): 正在执行的步骤
        content (str): 要流式发送的内容
        websocket: 要推送到的 websocket
        with_data (bool): 是否附带 data
        data: 要附带的额外数据
    """
    if websocket:
        try:
            if with_data:
                await websocket.send_json({
                    "type": log_type,
                    "step": step,
                    "content": content,
                    "data": data
                })
            else:
                await websocket.send_json({
                    "type": log_type,
                    "step": step,
                    "content": content
                })
        except Exception as e:
            logger.error(f"Error streaming output: {e}")

def check_pkg(pkg: str) -> None:
    """
    检查某个包是否已安装，未安装则报错。

    参数：
        pkg (str): 包名

    异常：
        ImportError: 包未安装时抛出
    """
    if not importlib.util.find_spec(pkg):
        pkg_kebab = pkg.replace("_", "-")
        raise ImportError(
            f"Unable to import {pkg_kebab}. Please install with "
            f"`pip install -U {pkg_kebab}`"
        )

# 可用于回退的有效 retriever
VALID_RETRIEVERS = [
    "tavily",
    "groundroute",
    "custom",
    "duckduckgo",
    "searchapi",
    "serper",
    "serpapi",
    "google",
    "searx",
    "bing",
    "brave",
    "arxiv",
    "semantic_scholar",
    "pubmed_central",
    "exa",
    "crw",
    "getxapi",
    "mcp",
    "xquik",
    "openalex",
    "mock"
]

def get_all_retriever_names():
    """
    获取所有可用的 retriever 名称
    :return: 所有可用 retriever 名称的列表
    :rtype: list
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 取出当前目录下的所有条目
        all_items = os.listdir(current_dir)
        
        # 只保留目录，排除 __pycache__
        retrievers = [
            item for item in all_items 
            if os.path.isdir(os.path.join(current_dir, item)) and not item.startswith('__')
        ]
        
        return retrievers
    except Exception as e:
        logger.error(f"Error getting retrievers: {e}")
        return VALID_RETRIEVERS
