"""
MCP retriever 模块

本模块只包含 MCP retriever 的实现。
MCP 的核心功能已移到 argus.mcp 模块。
"""
import logging

logger = logging.getLogger(__name__)

try:
    # 检查 langchain-mcp-adapters 是否可用
    from langchain_mcp_adapters.client import MultiServerMCPClient
    HAS_MCP_ADAPTERS = True
    logger.debug("langchain-mcp-adapters is available")
    
    # 导入 retriever
    from .retriever import MCPRetriever
    __all__ = ["MCPRetriever"]
    logger.debug("MCPRetriever imported successfully")
    
except ImportError as e:
    # 记录具体的导入错误，便于排查
    logger.warning(f"Failed to import MCPRetriever: {e}")
    # MCP 包未安装或出现其他导入错误，提供一个占位实现
    MCPRetriever = None
    __all__ = []
except Exception as e:
    # 兜住其他可能出现的异常
    logger.error(f"Unexpected error importing MCPRetriever: {e}")
    MCPRetriever = None
    __all__ = [] 