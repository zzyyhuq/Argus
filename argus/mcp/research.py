"""
MCP 研究执行 skill。

作为 skill 组件，负责用选出的 MCP 工具执行研究。
"""
import asyncio
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class MCPResearchSkill:
    """
    用选出的 MCP 工具执行研究。
    
    职责：
    - 借助 LLM 与绑定的工具执行研究
    - 把工具返回结果整理成标准格式
    - 管理工具执行与错误处理
    """

    def __init__(self, cfg, researcher=None):
        """
        初始化 MCP 研究 skill。
        
        参数：
            cfg: 携带 LLM 设置的配置对象
            researcher: 用于统计花费的 researcher 实例
        """
        self.cfg = cfg
        self.researcher = researcher

    async def conduct_research_with_tools(self, query: str, selected_tools: List) -> List[Dict[str, str]]:
        """
        让 LLM 带上绑定工具去开展研究。
        
        参数：
            query: 研究查询
            selected_tools: 选出的 MCP 工具列表
            
        返回：
            List[Dict[str, str]]: 标准格式的研究结果
        """
        if not selected_tools:
            logger.warning("No tools available for research")
            return []
            
        logger.info(f"Conducting research using {len(selected_tools)} selected tools")
        
        try:
            from ..llm_provider.generic.base import GenericLLMProvider
            
            # 按配置创建 LLM provider
            provider_kwargs = {
                'model': self.cfg.strategic_llm_model,
                **self.cfg.llm_kwargs
            }
            
            llm_provider = GenericLLMProvider.from_provider(
                self.cfg.strategic_llm_provider, 
                **provider_kwargs
            )
            
            # 把工具绑定到 LLM
            llm_with_tools = llm_provider.llm.bind_tools(selected_tools)
            
            # 在此处导入，避免循环导入
            from ..prompts import PromptFamily
            
            # 生成研究用的 prompt
            research_prompt = PromptFamily.generate_mcp_research_prompt(query, selected_tools)

            # 组装 messages
            messages = [{"role": "user", "content": research_prompt}]
            
            # 带上工具调用 LLM
            logger.info("LLM researching with bound tools...")
            response = await llm_with_tools.ainvoke(messages)
            
            # 处理工具调用与返回结果
            research_results = []
            
            # 看 LLM 是否发起了工具调用
            if hasattr(response, 'tool_calls') and response.tool_calls:
                logger.info(f"LLM made {len(response.tool_calls)} tool calls")
                
                # 逐个处理工具调用
                for i, tool_call in enumerate(response.tool_calls, 1):
                    tool_name = tool_call.get("name", "unknown")
                    tool_args = tool_call.get("args", {})
                    
                    logger.info(f"Executing tool {i}/{len(response.tool_calls)}: {tool_name}")
                    
                    # 记录工具入参，便于事后追溯
                    if tool_args:
                        args_str = ", ".join([f"{k}={v}" for k, v in tool_args.items()])
                        logger.debug(f"Tool arguments: {args_str}")
                    
                    try:
                        # 按名字找到对应工具
                        tool = next((t for t in selected_tools if t.name == tool_name), None)
                        if not tool:
                            logger.warning(f"Tool {tool_name} not found in selected tools")
                            continue
                        
                        # 执行该工具
                        if hasattr(tool, 'ainvoke'):
                            result = await tool.ainvoke(tool_args)
                        elif hasattr(tool, 'invoke'):
                            result = tool.invoke(tool_args)
                        else:
                            result = await tool(tool_args) if asyncio.iscoroutinefunction(tool) else tool(tool_args)
                        
                        # 记录工具的真实返回内容，便于排查
                        if result:
                            result_preview = str(result)[:500] + "..." if len(str(result)) > 500 else str(result)
                            logger.debug(f"Tool {tool_name} response preview: {result_preview}")
                            
                            # 处理返回结果
                            formatted_results = self._process_tool_result(tool_name, result)
                            research_results.extend(formatted_results)
                            logger.info(f"Tool {tool_name} returned {len(formatted_results)} formatted results")
                            
                            # 记录每条格式化结果的细节
                            for j, formatted_result in enumerate(formatted_results):
                                title = formatted_result.get("title", "No title")
                                content_preview = formatted_result.get("body", "")[:200] + "..." if len(formatted_result.get("body", "")) > 200 else formatted_result.get("body", "")
                                logger.debug(f"Result {j+1}: '{title}' - Content: {content_preview}")
                        else:
                            logger.warning(f"Tool {tool_name} returned empty result")
                            
                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {e}")
                        continue
                        
            # 把 LLM 自己的分析/回答也当作一条结果收进来
            if hasattr(response, 'content') and response.content:
                llm_analysis = {
                    "title": f"LLM Analysis: {query}",
                    "href": "mcp://llm_analysis",
                    "body": response.content
                }
                research_results.append(llm_analysis)
                
                # 记录 LLM 的分析内容
                analysis_preview = response.content[:300] + "..." if len(response.content) > 300 else response.content
                logger.debug(f"LLM Analysis: {analysis_preview}")
                logger.info("Added LLM analysis to results")
            
            logger.info(f"Research completed with {len(research_results)} total results")
            return research_results
            
        except Exception as e:
            logger.error(f"Error in LLM research with tools: {e}")
            return []

    def _process_tool_result(self, tool_name: str, result: Any) -> List[Dict[str, str]]:
        """
        把工具返回结果转换成搜索结果格式。
        
        参数：
            tool_name: 产出该结果的工具名
            result: 工具的返回结果
            
        返回：
            List[Dict[str, str]]: 格式化后的搜索结果
        """
        search_results = []
        
        try:
            # 1) 先处理带 structured_content/content 的 MCP 结果包装
            if isinstance(result, dict) and ("structured_content" in result or "content" in result):
                search_results = []
                # 有 structured_content 时优先用它
                structured = result.get("structured_content")
                if isinstance(structured, dict):
                    items = structured.get("results")
                    if isinstance(items, list):
                        for i, item in enumerate(items):
                            if isinstance(item, dict):
                                search_results.append({
                                    "title": item.get("title", f"Result from {tool_name} #{i+1}"),
                                    "href": item.get("href", item.get("url", f"mcp://{tool_name}/{i}")),
                                    "body": item.get("body", item.get("content", str(item)))
                                })
                    # 没有 items 数组、但 structured 本身是 dict 时，当作单条结果
                    elif isinstance(structured, dict):
                        search_results.append({
                            "title": structured.get("title", f"Result from {tool_name}"),
                            "href": structured.get("href", structured.get("url", f"mcp://{tool_name}")),
                            "body": structured.get("body", structured.get("content", str(structured)))
                        })
                # 上面没取到就退回 content（MCP 规范：{type: text, text: ...} 组成的列表）
                if not search_results:
                    content_field = result.get("content")
                    if isinstance(content_field, list):
                        texts = []
                        for part in content_field:
                            if isinstance(part, dict):
                                if part.get("type") == "text" and isinstance(part.get("text"), str):
                                    texts.append(part["text"])
                                elif "text" in part:
                                    texts.append(str(part.get("text")))
                                else:
                                    # 认不出的片段，直接转字符串
                                    texts.append(str(part))
                            else:
                                texts.append(str(part))
                        body_text = "\n\n".join([t for t in texts if t])
                    elif isinstance(content_field, str):
                        body_text = content_field
                    else:
                        body_text = str(result)
                    search_results.append({
                        "title": f"Result from {tool_name}",
                        "href": f"mcp://{tool_name}",
                        "body": body_text,
                    })
                return search_results

            # 2) 结果本身就是 list，逐项常规处理
            if isinstance(result, list):
                # 结果是 list，逐项处理
                for i, item in enumerate(result):
                    if isinstance(item, dict):
                        # 字段齐全就直接沿用该条目
                        if "title" in item and ("content" in item or "body" in item):
                            search_result = {
                                "title": item.get("title", ""),
                                "href": item.get("href", item.get("url", f"mcp://{tool_name}/{i}")),
                                "body": item.get("body", item.get("content", str(item))),
                            }
                            search_results.append(search_result)
                        else:
                            # 否则补一个通用标题，构造搜索结果
                            search_result = {
                                "title": f"Result from {tool_name}",
                                "href": f"mcp://{tool_name}/{i}",
                                "body": str(item),
                            }
                            search_results.append(search_result)
            # 3) 结果是 dict（非 MCP 包装）时，整体作为单条搜索结果
            elif isinstance(result, dict):
                # 结果是字典，就整体作为单条搜索结果
                search_result = {
                    "title": result.get("title", f"Result from {tool_name}"),
                    "href": result.get("href", result.get("url", f"mcp://{tool_name}")),
                    "body": result.get("body", result.get("content", str(result))),
                }
                search_results.append(search_result)
            else:
                # 其他类型一律转成字符串，作为单条搜索结果
                search_result = {
                    "title": f"Result from {tool_name}",
                    "href": f"mcp://{tool_name}",
                    "body": str(result),
                }
                search_results.append(search_result)
                
        except Exception as e:
            logger.error(f"Error processing tool result from {tool_name}: {e}")
            # 兜底：构造一条最基础的结果
            search_result = {
                "title": f"Result from {tool_name}",
                "href": f"mcp://{tool_name}",
                "body": str(result),
            }
            search_results.append(search_result)
        
        return search_results 