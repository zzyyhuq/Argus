"""
Argus 的启用工具的 LLM 工具函数

本模块借助 LangChain 的统一接口，提供与具体服务商无关的 tool calling 能力，
让任何支持 function calling 的 LLM 服务商都能无缝使用工具。
"""

import asyncio
import logging
from typing import Any, Dict, List, Tuple, Callable, Optional
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool

from .costs import calculate_llm_cost
from .llm import create_chat_completion

logger = logging.getLogger(__name__)


def _track_response_cost(
    *,
    llm_provider: str | None,
    model: str | None,
    input_payload: Any,
    response_message: Any,
    request_options: Dict[str, Any],
    cost_callback: Callable | None,
) -> None:
    if not cost_callback:
        return

    response_content = getattr(response_message, "content", "") or ""
    llm_costs = calculate_llm_cost(
        llm_provider=llm_provider,
        model=model,
        input_content=str(input_payload),
        output_content=str(response_content),
        response_metadata=getattr(response_message, "response_metadata", None),
        usage_metadata=getattr(response_message, "usage_metadata", None),
        request_options=request_options,
    )
    cost_callback(llm_costs)


async def create_chat_completion_with_tools(
    messages: List[Dict[str, str]],
    tools: List[Callable],
    model: str | None = None,
    temperature: float | None = 0.4,
    max_tokens: int | None = 4000,
    llm_provider: str | None = None,
    llm_kwargs: Dict[str, Any] | None = None,
    cost_callback: Callable = None,
    websocket: Any | None = None,
    **kwargs
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    创建支持 tool calling 的 chat completion，兼容所有 LLM 服务商。
    
    本函数用 LangChain 的 bind_tools() 以与具体服务商无关的方式启用 function
    calling。由 AI 自主决定何时以及如何使用工具。
    
    参数：
        messages: chat 消息列表，每条含 role 与 content
        tools: LangChain 工具函数列表（用 @tool 装饰）
        model: 使用的模型（取自配置）
        temperature: 生成时的 temperature
        max_tokens: 最多生成的 token 数
        llm_provider: LLM 服务商名称（取自配置）
        llm_kwargs: 额外的 LLM 关键字参数
        cost_callback: 用于成本统计的回调函数
        websocket: 可选的 websocket，用于流式输出
        **kwargs: 额外的参数
        
    返回：
        (response_content, tool_calls_metadata) 元组
        
    异常：
        Exception: 启用工具的 completion 失败时会回退到简单 completion
    """
    try:
        from ..llm_provider.generic.base import GenericLLMProvider
        
        # 按配置创建 LLM provider
        provider_kwargs = {
            'model': model,
            **(llm_kwargs or {})
        }
        
        llm_provider_instance = GenericLLMProvider.from_provider(
            llm_provider, 
            **provider_kwargs
        )
        
        # 把消息转换成 LangChain 格式
        lc_messages = []
        for msg in messages:
            if msg["role"] == "system":
                lc_messages.append(SystemMessage(content=msg["content"]))
            elif msg["role"] == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                lc_messages.append(AIMessage(content=msg["content"]))
        
        # 把工具绑定到 LLM 上 —— 凡是支持 function calling 的 LangChain
        # 服务商都能这么用
        llm_with_tools = llm_provider_instance.llm.bind_tools(tools)
        
        # 带着工具调用 LLM —— 完整的多轮对话流程由它负责
        logger.info(f"Invoking LLM with {len(tools)} available tools")
        
        # tool calling 需要处理包含工具返回结果的完整对话
        from langchain_core.messages import ToolMessage
        
        # 第一次调用 LLM
        response = await llm_with_tools.ainvoke(lc_messages)
        _track_response_cost(
            llm_provider=llm_provider,
            model=model,
            input_payload=lc_messages,
            response_message=response,
            request_options=provider_kwargs,
            cost_callback=cost_callback,
        )
        
        # 若发生了工具调用，则逐条处理
        tool_calls_metadata = []
        if hasattr(response, 'tool_calls') and response.tool_calls:
            logger.info(f"LLM made {len(response.tool_calls)} tool calls")
            
            # 把带 tool calls 的 assistant 回复追加进对话
            lc_messages.append(response)
            
            # 执行每个工具调用，并把结果加入对话
            for tool_call in response.tool_calls:
                tool_name = tool_call.get('name', 'unknown')
                tool_args = tool_call.get('args', {})
                tool_id = tool_call.get('id', '')
                
                logger.info(f"Tool called: {tool_name}")
                if tool_args:
                    args_str = ", ".join([f"{k}={v}" for k, v in tool_args.items()])
                    logger.debug(f"Tool arguments: {args_str}")
                
                # 找到并执行该工具
                tool_result = "Tool execution failed"
                for tool in tools:
                    if tool.name == tool_name:
                        try:
                            if hasattr(tool, 'ainvoke'):
                                tool_result = await tool.ainvoke(tool_args)
                            elif hasattr(tool, 'invoke'):
                                tool_result = tool.invoke(tool_args)
                            else:
                                tool_result = await tool(**tool_args) if asyncio.iscoroutinefunction(tool) else tool(**tool_args)
                            break
                        except Exception as e:
                            error_type = type(e).__name__
                            error_msg = str(e)
                            logger.error(
                                f"Error executing tool '{tool_name}': {error_type}: {error_msg}",
                                exc_info=True
                            )
                            # 给出对用户友好的错误提示
                            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                                tool_result = f"Tool '{tool_name}' timed out. The operation took too long to complete. Please try again or check your network connection."
                            elif "connection" in error_msg.lower() or "network" in error_msg.lower():
                                tool_result = f"Tool '{tool_name}' failed due to a network issue. Please check your internet connection and try again."
                            elif "permission" in error_msg.lower() or "access" in error_msg.lower():
                                tool_result = f"Tool '{tool_name}' failed due to insufficient permissions. Please check your API keys or access credentials."
                            else:
                                tool_result = f"Tool '{tool_name}' encountered an error: {error_msg}. Please check the logs for more details."
                
                # 把工具结果加入对话
                tool_message = ToolMessage(content=str(tool_result), tool_call_id=tool_id)
                lc_messages.append(tool_message)
                
                # 记入元数据
                tool_calls_metadata.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "call_id": tool_id,
                    "result": str(tool_result)[:200] + "..." if len(str(tool_result)) > 200 else str(tool_result)
                })
            
            # 工具执行完后，取 LLM 的最终回复
            logger.info("Getting final response from LLM after tool execution")
            final_response = await llm_with_tools.ainvoke(lc_messages)
             
            # 提供了回调就统计成本
            _track_response_cost(
                llm_provider=llm_provider,
                model=model,
                input_payload=lc_messages,
                response_message=final_response,
                request_options=provider_kwargs,
                cost_callback=cost_callback,
            )
             
            return final_response.content, tool_calls_metadata
         
        else:
            # 没有工具调用，直接返回普通响应
            return response.content, []
        
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(
            f"Error in tool-enabled chat completion: {error_type}: {error_msg}",
            exc_info=True
        )
        logger.info("Falling back to simple chat completion without tools")
        
        # 回退到不带工具的简单 chat completion
        response = await create_chat_completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            llm_provider=llm_provider,
            llm_kwargs=llm_kwargs,
            cost_callback=cost_callback,
            websocket=websocket,
            **kwargs
        )
        return response, []


def create_search_tool(search_function: Callable[[str], Dict]) -> Callable:
    """
    创建一个标准化的搜索工具，供启用工具的 chat completion 使用。
    
    参数：
        search_function: 接收查询字符串并返回搜索结果的函数
        
    返回：
        用 @tool 装饰的 LangChain 工具函数
    """
    @tool
    def search_tool(query: str) -> str:
        """Search for current events or online information when you need new knowledge that doesn't exist in the current context"""
        try:
            results = search_function(query)
            if results and 'results' in results:
                search_content = f"Search results for '{query}':\n\n"
                for result in results['results'][:5]:
                    search_content += f"Title: {result.get('title', '')}\n"
                    search_content += f"Content: {result.get('content', '')[:300]}...\n"
                    search_content += f"URL: {result.get('url', '')}\n\n"
                return search_content
            else:
                return f"No search results found for: {query}"
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(
                f"Search tool error: {error_type}: {error_msg}",
                exc_info=True
            )
            # 按错误类型给出贴合场景的提示
            if "api" in error_msg.lower() or "key" in error_msg.lower():
                return f"Search failed: API key issue. Please verify your search API credentials are configured correctly."
            elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                return f"Search timed out. The search request took too long. Please try again with a different query."
            elif "rate limit" in error_msg.lower() or "quota" in error_msg.lower():
                return f"Search rate limit exceeded. Please wait a moment before trying again."
            else:
                return f"Search encountered an error: {error_msg}. Please check your search provider configuration."
    
    return search_tool


def create_custom_tool(
    name: str,
    description: str, 
    function: Callable,
    parameter_schema: Optional[Dict] = None
) -> Callable:
    """
    创建一个自定义工具，供启用工具的 chat completion 使用。
    
    参数：
        name: 工具名称
        description: 工具用途说明
        function: 实际要执行的函数
        parameter_schema: 函数参数的可选 schema
        
    返回：
        用 @tool 装饰的 LangChain 工具函数
    """
    @tool
    def custom_tool(*args, **kwargs) -> str:
        try:
            result = function(*args, **kwargs)
            return str(result) if result is not None else "Tool executed successfully"
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(
                f"Custom tool '{name}' error: {error_type}: {error_msg}",
                exc_info=True
            )
            # 给出有用提示，同时不把内部细节暴露出去
            if "validation" in error_msg.lower() or "invalid" in error_msg.lower():
                return f"Tool '{name}' received invalid input. Please check the parameters and try again."
            elif "not found" in error_msg.lower() or "missing" in error_msg.lower():
                return f"Tool '{name}' could not find required resources. Please verify the input data is correct."
            else:
                return f"Tool '{name}' encountered an error: {error_msg}. Please check the tool configuration."
    
    # 设置工具元数据
    custom_tool.name = name
    custom_tool.description = description
    
    return custom_tool


# 常见工具模式的辅助函数
def get_available_providers_with_tools() -> List[str]:
    """
    获取支持 tool calling 的 LLM 服务商列表。
    
    返回：
        支持 function calling 的服务商名称列表
    """
    # 这些是已知在 LangChain 中支持 function calling 的服务商
    return [
        "openai",
        "anthropic", 
        "google_genai",
        "azure_openai",
        "fireworks",
        "groq",
        # 注意：随着更多服务商支持 function calling，这个列表可能还会扩充
    ]


def supports_tools(provider: str) -> bool:
    """
    判断给定服务商是否支持 tool calling。
    
    参数：
        provider: LLM 服务商名称
        
    返回：
        服务商支持工具时返回 True，否则返回 False
    """
    return provider in get_available_providers_with_tools()
