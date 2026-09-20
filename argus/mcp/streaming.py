"""
MCP 流式输出工具模块。

负责 MCP 操作过程中的 websocket 推送与日志。
"""
import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MCPStreamer:
    """
    负责 MCP 操作的流式输出。
    
    职责：
    - 把日志推送到 websocket
    - 同步/异步两套日志接口
    - 流式输出过程中的错误处理
    """

    def __init__(self, websocket=None):
        """
        初始化 MCP streamer。
        
        参数：
            websocket: 用于流式输出的 WebSocket
        """
        self.websocket = websocket

    async def stream_log(self, message: str, data: Any = None):
        """若有 websocket，就把这条日志推送给它。"""
        logger.info(message)
        
        if self.websocket:
            try:
                from ..actions.utils import stream_output
                await stream_output(
                    type="logs", 
                    content="mcp_retriever", 
                    output=message, 
                    websocket=self.websocket,
                    metadata=data
                )
            except Exception as e:
                logger.error(f"Error streaming log: {e}")
                
    def stream_log_sync(self, message: str, data: Any = None):
        """stream_log 的同步版本，供同步上下文中调用。"""
        logger.info(message)
        
        if self.websocket:
            try:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.stream_log(message, data))
                    else:
                        loop.run_until_complete(self.stream_log(message, data))
                except RuntimeError:
                    logger.debug("Could not stream log: no running event loop")
            except Exception as e:
                logger.error(f"Error in sync log streaming: {e}")

    async def stream_stage_start(self, stage: str, description: str):
        """推送某个研究阶段的开始。"""
        await self.stream_log(f"🔧 {stage}: {description}")

    async def stream_stage_complete(self, stage: str, result_count: int = None):
        """推送某个研究阶段的完成。"""
        if result_count is not None:
            await self.stream_log(f"✅ {stage} completed: {result_count} results")
        else:
            await self.stream_log(f"✅ {stage} completed")

    async def stream_tool_selection(self, selected_count: int, total_count: int):
        """推送工具筛选的结果。"""
        await self.stream_log(f"🧠 Using LLM to select {selected_count} most relevant tools from {total_count} available")

    async def stream_tool_execution(self, tool_name: str, step: int, total: int):
        """推送工具的执行进度。"""
        await self.stream_log(f"🔍 Executing tool {step}/{total}: {tool_name}")

    async def stream_research_results(self, result_count: int, total_chars: int = None):
        """推送研究结果的汇总。"""
        if total_chars:
            await self.stream_log(f"✅ MCP research completed: {result_count} results obtained ({total_chars:,} chars)")
        else:
            await self.stream_log(f"✅ MCP research completed: {result_count} results obtained")

    async def stream_error(self, error_msg: str):
        """推送错误信息。"""
        await self.stream_log(f"❌ {error_msg}")

    async def stream_warning(self, warning_msg: str):
        """推送警告信息。"""
        await self.stream_log(f"⚠️ {warning_msg}")

    async def stream_info(self, info_msg: str):
        """推送提示信息。"""
        await self.stream_log(f"ℹ️ {info_msg}") 