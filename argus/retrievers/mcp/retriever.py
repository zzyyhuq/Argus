"""
基于 MCP 的研究 retriever

一个使用 Model Context Protocol (MCP) 工具做智能研究的 retriever。
它采用两阶段方案：
1. 工具选择：由 LLM 从全部可用的 MCP 工具中挑出最相关的 2-3 个
2. 研究执行：由 LLM 使用选中的工具开展智能研究
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    HAS_MCP_ADAPTERS = True
except ImportError:
    HAS_MCP_ADAPTERS = False

from ...mcp.client import MCPClientManager
from ...mcp.tool_selector import MCPToolSelector
from ...mcp.research import MCPResearchSkill
from ...mcp.streaming import MCPStreamer

logger = logging.getLogger(__name__)


class MCPRetriever:
    """
    Argus 的 Model Context Protocol (MCP) retriever。

    本 retriever 采用两阶段方案：
    1. 工具选择：由 LLM 从全部可用的 MCP 工具中挑出最相关的 2-3 个
    2. 研究执行：由绑定了工具的 LLM 开展智能研究

    该方案比调用全部工具更高效，研究结果也更好、更有针对性。

    retriever 需要一个 researcher 实例，以便访问：
    - mcp_configs: MCP 服务器配置列表
    - cfg: 含 LLM 设置与参数的配置对象
    - add_costs: 用于统计研究成本的方法
    """

    def __init__(
        self, 
        query: str, 
        headers: Optional[Dict[str, str]] = None,
        query_domains: Optional[List[str]] = None,
        websocket=None,
        researcher=None,
        **kwargs
    ):
        """
        初始化 MCP Retriever。

        参数：
            query (str): 搜索查询字符串。
            headers (dict, optional): 含 MCP 配置的 headers。
            query_domains (list, optional): 要搜索的域名列表（MCP 中不使用）。
            websocket: 用于流式日志的 WebSocket。
            researcher: 含 mcp_configs 与 cfg 的 Researcher 实例。
            **kwargs: 附加参数（用于兼容）。
        """
        self.query = query
        self.headers = headers or {}
        self.query_domains = query_domains or []
        self.websocket = websocket
        self.researcher = researcher
        
        # 从 researcher 实例中取出 mcp_configs 与 config
        self.mcp_configs = self._get_mcp_configs()
        self.cfg = self._get_config()
        
        # 初始化各模块化组件
        self.client_manager = MCPClientManager(self.mcp_configs)
        self.tool_selector = MCPToolSelector(self.cfg, self.researcher)
        self.mcp_researcher = MCPResearchSkill(self.cfg, self.researcher)
        self.streamer = MCPStreamer(self.websocket)
        
        # 初始化缓存
        self._all_tools_cache = None
        
        # 记录初始化日志
        if self.mcp_configs:
            self.streamer.stream_log_sync(f"🔧 Initializing MCP retriever for query: {self.query}")
            self.streamer.stream_log_sync(f"🔧 Found {len(self.mcp_configs)} MCP server configurations")
        else:
            logger.error("No MCP server configurations found. The retriever will fail during search.")
            self.streamer.stream_log_sync("❌ CRITICAL: No MCP server configurations found. Please check documentation.")

    def _get_mcp_configs(self) -> List[Dict[str, Any]]:
        """
        从 researcher 实例中获取 MCP 配置。

        返回：
            List[Dict[str, Any]]: MCP 服务器配置列表。
        """
        if self.researcher and hasattr(self.researcher, 'mcp_configs'):
            return self.researcher.mcp_configs or []
        return []

    def _get_config(self):
        """
        从 researcher 实例中获取配置。

        返回：
            Config: 含 LLM 设置的配置对象。
        """
        if self.researcher and hasattr(self.researcher, 'cfg'):
            return self.researcher.cfg
        
        # 没有可用 config 属于致命错误
        logger.error("No config found in researcher instance. MCPRetriever requires a researcher instance with cfg attribute.")
        raise ValueError("MCPRetriever requires a researcher instance with cfg attribute containing LLM configuration")

    async def search_async(self, max_results: int = 10) -> List[Dict[str, str]]:
        """
        使用 MCP 工具执行异步搜索，采用智能的两阶段方案。

        参数：
            max_results: 最多返回的结果数。

        返回：
            List[Dict[str, str]]: 搜索结果。
        """
        # 检查是否有任何服务器配置
        if not self.mcp_configs:
            error_msg = "No MCP server configurations available. Please provide mcp_configs parameter to Argus."
            logger.error(error_msg)
            await self.streamer.stream_error("MCP retriever cannot proceed without server configurations.")
            return []  # 返回空列表而不是抛异常，让研究流程能继续走下去
            
        # 记录日志，便于排查集成流程
        logger.info(f"MCPRetriever.search_async called for query: {self.query}")
            
        try:
            # 阶段 1：获取所有可用工具
            await self.streamer.stream_stage_start("Stage 1", "Getting all available MCP tools")
            all_tools = await self._get_all_tools()
            
            if not all_tools:
                await self.streamer.stream_warning("No MCP tools available, skipping MCP research")
                return []
            
            # 阶段 2：挑选最相关的工具
            await self.streamer.stream_stage_start("Stage 2", "Selecting most relevant tools")
            selected_tools = await self.tool_selector.select_relevant_tools(self.query, all_tools, max_tools=3)
            
            if not selected_tools:
                await self.streamer.stream_warning("No relevant tools selected, skipping MCP research")
                return []
            
            # 阶段 3：用选中的工具开展研究
            await self.streamer.stream_stage_start("Stage 3", "Conducting research with selected tools")
            results = await self.mcp_researcher.conduct_research_with_tools(self.query, selected_tools)
            
            # 限制结果条数
            if len(results) > max_results:
                logger.info(f"Limiting {len(results)} MCP results to {max_results}")
                results = results[:max_results]
            
            # 记录结果摘要，并附带实际内容样本
            logger.info(f"MCPRetriever returning {len(results)} results")
            
            # 统计内容总长度，用于摘要
            total_content_length = sum(len(result.get("body", "")) for result in results)
            await self.streamer.stream_research_results(len(results), total_content_length)
            
            # 记录详细内容样本，便于调试
            if results:
                # 展示前几条结果的样本
                for i, result in enumerate(results[:3]):  # 只展示前 3 条结果
                    title = result.get("title", "No title")
                    url = result.get("href", "No URL")
                    content = result.get("body", "")
                    content_length = len(content)
                    content_sample = content[:400] + "..." if len(content) > 400 else content
                    
                    logger.debug(f"Result {i+1}/{len(results)}: '{title}'")
                    logger.debug(f"URL: {url}")
                    logger.debug(f"Content ({content_length:,} chars): {content_sample}")
                    
                if len(results) > 3:
                    remaining_results = len(results) - 3
                    remaining_content = sum(len(result.get("body", "")) for result in results[3:])
                    logger.debug(f"... and {remaining_results} more results ({remaining_content:,} chars)")
                    
            return results
            
        except Exception as e:
            logger.error(f"Error in MCP search: {e}")
            await self.streamer.stream_error(f"Error in MCP search: {str(e)}")
            return []
        finally:
            # 确保搜索完成后清理客户端
            try:
                await self.client_manager.close_client()
            except Exception as e:
                logger.error(f"Error during client cleanup: {e}")

    def search(self, max_results: int = 10) -> List[Dict[str, str]]:
        """
        使用 MCP 工具执行搜索，采用智能的两阶段方案。

        这是 Argus 要求的同步接口，内部包装了异步的 search_async 方法。

        参数：
            max_results: 最多返回的结果数。

        返回：
            List[Dict[str, str]]: 搜索结果。
        """
        # 检查是否有任何服务器配置
        if not self.mcp_configs:
            error_msg = "No MCP server configurations available. Please provide mcp_configs parameter to Argus."
            logger.error(error_msg)
            self.streamer.stream_log_sync("❌ MCP retriever cannot proceed without server configurations.")
            return []  # 返回空列表而不是抛异常，让研究流程能继续走下去
            
        # 记录日志，便于排查集成流程
        logger.info(f"MCPRetriever.search called for query: {self.query}")
        
        try:
            # 妥善处理 async/sync 的边界
            try:
                # 尝试获取当前事件循环
                loop = asyncio.get_running_loop()
                # 若处于 async 上下文中，就需要另行调度这个协程。
                # 这里稍微绕一点——我们创建一个任务并让它自己跑起来。
                import concurrent.futures
                import threading
                
                # 在独立线程中新建一个事件循环
                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(self.search_async(max_results))
                        return result
                    finally:
                        # 针对 MCP 连接的强化清理流程
                        try:
                            # 取消所有待处理任务（带超时）
                            pending = asyncio.all_tasks(new_loop)
                            for task in pending:
                                task.cancel()
                            
                            # 带超时地等待已取消任务收尾
                            if pending:
                                try:
                                    new_loop.run_until_complete(
                                        asyncio.wait_for(
                                            asyncio.gather(*pending, return_exceptions=True),
                                            timeout=5.0  # 清理超时 5 秒
                                        )
                                    )
                                except asyncio.TimeoutError:
                                    logger.debug("Timeout during task cleanup, continuing...")
                                except Exception:
                                    pass  # 忽略其他清理错误
                        except Exception:
                            pass  # 忽略清理错误
                        finally:
                            try:
                                # 给事件循环一点时间完成最后的清理
                                import time
                                time.sleep(0.1)
                                
                                # 强制垃圾回收，清理残留引用
                                import gc
                                gc.collect()
                                
                                # 再留一点时间给 HTTP 客户端完成清理
                                time.sleep(0.2)
                                
                                # 关闭事件循环
                                if not new_loop.is_closed():
                                    new_loop.close()
                            except Exception:
                                pass  # 忽略关闭时的错误
                
                # 放到线程池里跑，避免阻塞主事件循环
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    results = future.result(timeout=300)  # 5 分钟超时
                    
            except RuntimeError:
                # 没有事件循环在运行，可以直接跑
                results = asyncio.run(self.search_async(max_results))
            
            return results
            
        except Exception as e:
            logger.error(f"Error in MCP search: {e}")
            self.streamer.stream_log_sync(f"❌ Error in MCP search: {str(e)}")
            # 返回空结果而不是抛异常，让研究流程能继续走下去
            return []

    async def _get_all_tools(self) -> List:
        """
        从 MCP 服务器获取所有可用工具。

        返回：
            List: 所有可用的 MCP 工具
        """
        if self._all_tools_cache is not None:
            return self._all_tools_cache
            
        try:
            all_tools = await self.client_manager.get_all_tools()
            
            if all_tools:
                await self.streamer.stream_log(f"📋 Loaded {len(all_tools)} total tools from MCP servers")
                self._all_tools_cache = all_tools
                return all_tools
            else:
                await self.streamer.stream_warning("No tools available from MCP servers")
                return []
                
        except Exception as e:
            logger.error(f"Error getting MCP tools: {e}")
            await self.streamer.stream_error(f"Error getting MCP tools: {str(e)}")
            return [] 