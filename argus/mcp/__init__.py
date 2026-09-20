"""
Argus 的 MCP（Model Context Protocol）集成。

本模块提供完整的 MCP 接入能力：
- MCP server 的客户端管理
- 工具的筛选与执行
- 借助 MCP 工具开展研究
- 实时推送所需的流式输出支持
"""

import logging

logger = logging.getLogger(__name__)

try:
    # 检查 langchain-mcp-adapters 是否可用
    from langchain_mcp_adapters.client import MultiServerMCPClient
    HAS_MCP_ADAPTERS = True
    logger.debug("langchain-mcp-adapters is available")
    
    # 导入 MCP 的核心组件
    from .client import MCPClientManager
    from .tool_selector import MCPToolSelector
    from .research import MCPResearchSkill
    from .streaming import MCPStreamer
    
    __all__ = [
        "MCPClientManager",
        "MCPToolSelector", 
        "MCPResearchSkill",
        "MCPStreamer",
        "HAS_MCP_ADAPTERS"
    ]
    
except ImportError as e:
    logger.warning(f"MCP dependencies not available: {e}")
    HAS_MCP_ADAPTERS = False
    __all__ = ["HAS_MCP_ADAPTERS"]
    
except Exception as e:
    logger.error(f"Unexpected error importing MCP components: {e}")
    HAS_MCP_ADAPTERS = False
    __all__ = ["HAS_MCP_ADAPTERS"] 