"""
MCP client 管理模块。

负责 MCP client 的创建、配置转换与连接管理。
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    HAS_MCP_ADAPTERS = True
except ImportError:
    HAS_MCP_ADAPTERS = False

logger = logging.getLogger(__name__)


class MCPClientManager:
    """
    管理 MCP client 的生命周期与配置。
    
    职责：
    - 把 Argus 的 MCP 配置转换成 langchain 格式
    - 创建并管理 MultiServerMCPClient 实例
    - 负责 client 的清理与资源释放
    """

    def __init__(self, mcp_configs: List[Dict[str, Any]]):
        """
        初始化 MCP client 管理器。
        
        参数：
            mcp_configs: 来自 Argus 的 MCP server 配置列表
        """
        self.mcp_configs = mcp_configs or []
        self._client = None
        self._client_lock = asyncio.Lock()

    def convert_configs_to_langchain_format(self) -> Dict[str, Dict[str, Any]]:
        """
        把 Argus 的 MCP 配置转换成 langchain-mcp-adapters 所需格式。
        
        返回：
            Dict[str, Dict[str, Any]]: 供 MultiServerMCPClient 使用的 server 配置
        """
        server_configs = {}
        
        for i, config in enumerate(self.mcp_configs):
            # Argus 的 MCP 配置本应是 dict；这里容忍 list/json 之类的类型漂移，
            # 免得单条坏数据就让整个转换抛 AttributeError。
            if not isinstance(config, dict):
                logger.warning(
                    "Skipping MCP server config at index %s: expected dict, got %s",
                    i,
                    type(config).__name__,
                )
                continue
            # 生成 server 名称
            server_name = config.get("name", f"mcp_server_{i+1}")
            
            # 组装 server 配置
            server_config = {}
            
            # 若提供了 URL，就据此自动判断传输类型
            connection_url = config.get("connection_url")
            if connection_url:
                if connection_url.startswith(("wss://", "ws://")):
                    server_config["transport"] = "websocket"
                    server_config["url"] = connection_url
                elif connection_url.startswith(("https://", "http://")):
                    server_config["transport"] = "streamable_http"
                    server_config["url"] = connection_url
                else:
                    # 退回指定的 connection_type，或默认的 stdio
                    connection_type = config.get("connection_type", "stdio")
                    server_config["transport"] = connection_type
                    if connection_type in ["websocket", "streamable_http", "http"]:
                        server_config["url"] = connection_url
            else:
                # 没有 URL 时，使用 stdio（默认）或指定的 connection_type
                connection_type = config.get("connection_type", "stdio")
                server_config["transport"] = connection_type
            
            if server_config.get("transport") in ["streamable_http", "http", "websocket"]:
                connection_headers = config.get("connection_headers")
                if connection_headers and isinstance(connection_headers, dict):
                    server_config["headers"] = connection_headers
            
            # stdio 传输方式的专属配置
            if server_config.get("transport") == "stdio":
                if config.get("command"):
                    server_config["command"] = config["command"]
                    
                    # 处理 server_args
                    server_args = config.get("args", [])
                    if isinstance(server_args, str):
                        server_args = server_args.split()
                    server_config["args"] = server_args
                    
                    # 处理环境变量
                    server_env = config.get("env", {})
                    if server_env:
                        server_config["env"] = server_env
                        
            # 配置里带了认证信息就一并加上
            if config.get("connection_token"):
                server_config["token"] = config["connection_token"]
                
            server_configs[server_name] = server_config
            
        return server_configs

    async def get_or_create_client(self) -> Optional[object]:
        """
        获取或创建 MultiServerMCPClient，并妥善管理其生命周期。
        
        返回：
            MultiServerMCPClient: client 实例；创建失败时为 None
        """
        async with self._client_lock:
            if self._client is not None:
                return self._client
                
            if not HAS_MCP_ADAPTERS:
                logger.error("langchain-mcp-adapters not installed")
                return None
                
            if not self.mcp_configs:
                logger.error("No MCP server configurations found")
                return None
                
            try:
                # 把配置转换成 langchain 格式
                server_configs = self.convert_configs_to_langchain_format()
                logger.info(f"Creating MCP client for {len(server_configs)} server(s)")
                
                # 初始化 MultiServerMCPClient
                self._client = MultiServerMCPClient(server_configs)
                
                return self._client
                
            except Exception as e:
                logger.error(f"Error creating MCP client: {e}")
                return None

    async def close_client(self):
        """
        正确关闭 MCP client 并清理资源。
        """
        async with self._client_lock:
            if self._client is not None:
                try:
                    # langchain-mcp-adapters 0.1.0 里的 MultiServerMCPClient 既不支持
                    # 上下文管理器，也没有显式 close 方法，所以这里只是清掉引用，
                    # 交给垃圾回收去处理。
                    logger.debug("Releasing MCP client reference")
                except Exception as e:
                    logger.error(f"Error during MCP client cleanup: {e}")
                finally:
                    # 无论如何都要清掉引用
                    self._client = None

    async def get_all_tools(self) -> List:
        """
        获取 MCP server 提供的全部可用工具。
        
        返回：
            List: 所有可用的 MCP 工具
        """
        client = await self.get_or_create_client()
        if not client:
            return []
            
        try:
            # 从所有 server 拉取工具
            all_tools = await client.get_tools()
            
            if all_tools:
                logger.info(f"Loaded {len(all_tools)} total tools from MCP servers")
                return all_tools
            else:
                logger.warning("No tools available from MCP servers")
                return []
                
        except Exception as e:
            logger.error(f"Error getting MCP tools: {e}")
            return [] 
