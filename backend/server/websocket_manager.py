import os
import asyncio
import datetime
import json
import logging
import os
import traceback
from typing import Dict, List

from fastapi import WebSocket

from backend.report_type import BasicReport, DetailedReport

from argus.utils.enum import ReportType, Tone
from argus.actions import stream_output  # 导入 stream_output
from .multi_agent_runner import run_multi_agent_task
from .server_utils import CustomLogsHandler

logger = logging.getLogger(__name__)

class WebSocketManager:
    """管理 websocket 连接"""

    def __init__(self):
        """初始化 WebSocketManager。"""
        self.active_connections: List[WebSocket] = []
        self.sender_tasks: Dict[WebSocket, asyncio.Task] = {}
        self.message_queues: Dict[WebSocket, asyncio.Queue] = {}

    async def start_sender(self, websocket: WebSocket):
        """启动发送任务。"""
        queue = self.message_queues.get(websocket)
        if not queue:
            return

        while True:
            try:
                message = await queue.get()
                if message is None:  # 关闭信号
                    break
                    
                if websocket in self.active_connections:
                    if message == "ping":
                        await websocket.send_text("pong")
                    else:
                        await websocket.send_text(message)
                else:
                    break
            except Exception as e:
                print(f"Error in sender task: {e}")
                break

    async def connect(self, websocket: WebSocket):
        """接入一个 websocket。"""
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
            self.message_queues[websocket] = asyncio.Queue()
            self.sender_tasks[websocket] = asyncio.create_task(
                self.start_sender(websocket))
        except Exception as e:
            print(f"Error connecting websocket: {e}")
            if websocket in self.active_connections:
                await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket):
        """断开一个 websocket。"""
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                
                # 发送任务存在就取消掉
                if websocket in self.sender_tasks:
                    try:
                        self.sender_tasks[websocket].cancel()
                        await self.message_queues[websocket].put(None)
                    except Exception as e:
                        logger.error(f"Error canceling sender task: {e}")
                    finally:
                        # 无论是否出错都要清理
                        if websocket in self.sender_tasks:
                            del self.sender_tasks[websocket]
                
                # 清理消息队列
                if websocket in self.message_queues:
                    del self.message_queues[websocket]
                
                # 最后关闭 WebSocket
                try:
                    await websocket.close()
                except Exception as e:
                    logger.info(f"WebSocket already closed: {e}")
        except Exception as e:
            logger.error(f"Error during WebSocket disconnection: {e}")
            # 还是尽量把连接关掉
            try:
                await websocket.close()
            except Exception:
                pass  # 这一步也失败的话，就没别的办法了

    async def start_streaming(self, task, report_type, report_source, source_urls, document_urls, tone, websocket, headers=None, query_domains=[], mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], max_search_results=None, api_keys=None):
        """开始流式输出。"""
        tone = Tone[tone]
        # 在这里填入自定义 JSON 配置文件的路径
        config_path = os.environ.get("CONFIG_PATH", "default")

        # 把 MCP 参数传给 run_agent
        report = await run_agent(
            task, report_type, report_source, source_urls, document_urls, tone, websocket,
            headers=headers, query_domains=query_domains, config_path=config_path,
            mcp_enabled=mcp_enabled, mcp_strategy=mcp_strategy, mcp_configs=mcp_configs,
            max_search_results=max_search_results, api_keys=api_keys
        )
        return report

async def run_agent(task, report_type, report_source, source_urls, document_urls, tone: Tone, websocket, stream_output=stream_output, headers=None, query_domains=[], config_path="", return_researcher=False, mcp_enabled=False, mcp_strategy="fast", mcp_configs=[], max_search_results=None, api_keys=None):
    """运行 agent。"""
    # 为本次研究任务创建日志处理器
    logs_handler = CustomLogsHandler(websocket, task)

    # 记录 MCP 的初始化。retriever 与 strategy 是逐请求配置的，通过 Argus 的
    # mcp_configs/mcp_strategy 参数传入——这里不需要改 os.environ，因为改动
    # os.environ 会跨请求残留，影响无关的会话，见 issue #1676。
    if mcp_enabled and mcp_configs:
        print(f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)")
        await logs_handler.send_json({
            "type": "logs",
            "content": "mcp_init",
            "output": f"🔧 MCP enabled with strategy '{mcp_strategy}' and {len(mcp_configs)} server(s)"
        })

    # 按报告类型初始化 researcher
    if report_type == "multi_agents":
        report = await run_multi_agent_task(
            query=task, 
            websocket=logs_handler,  # 用 logs_handler 而不是裸 websocket
            stream_output=stream_output, 
            tone=tone, 
            headers=headers
        )
        report = report.get("report", "")

    elif report_type == ReportType.DetailedReport.value:
        researcher = DetailedReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # 用 logs_handler 而不是裸 websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            max_search_results=max_search_results,
            api_keys=api_keys,
        )
        report = await researcher.run()

    else:
        researcher = BasicReport(
            query=task,
            query_domains=query_domains,
            report_type=report_type,
            report_source=report_source,
            source_urls=source_urls,
            document_urls=document_urls,
            tone=tone,
            config_path=config_path,
            websocket=logs_handler,  # 用 logs_handler 而不是裸 websocket
            headers=headers,
            mcp_configs=mcp_configs if mcp_enabled else None,
            mcp_strategy=mcp_strategy if mcp_enabled else None,
            max_search_results=max_search_results,
            api_keys=api_keys,
        )
        report = await researcher.run()

    if report_type != "multi_agents" and return_researcher:
        return report, researcher.argus
    else:
        return report
