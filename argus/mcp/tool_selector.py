"""
MCP 工具筛选模块。

负责借助 LLM 分析来智能挑选工具。
"""
import asyncio
import json
import logging

import json_repair
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class MCPToolSelector:
    """
    借助 LLM 分析，智能挑选要用的 MCP 工具。
    
    职责：
    - 用 LLM 分析有哪些可用工具
    - 为查询挑出最相关的工具
    - 提供兜底的挑选机制
    """

    def __init__(self, cfg, researcher=None):
        """
        初始化工具筛选器。
        
        参数：
            cfg: 携带 LLM 设置的配置对象
            researcher: 用于统计花费的 researcher 实例
        """
        self.cfg = cfg
        self.researcher = researcher

    async def select_relevant_tools(self, query: str, all_tools: List, max_tools: int = 3) -> List:
        """
        用 LLM 为研究查询挑出最相关的工具。
        
        参数：
            query: 研究查询
            all_tools: 全部可用工具列表
            max_tools: 最多挑选几个工具（默认 3）
            
        返回：
            List: 对该查询最相关的已选工具
        """
        if not all_tools:
            return []

        if len(all_tools) < max_tools:
            max_tools = len(all_tools)
            
        logger.info(f"Using LLM to select {max_tools} most relevant tools from {len(all_tools)} available")
        
        # 整理工具描述，供 LLM 分析
        tools_info = []
        for i, tool in enumerate(all_tools):
            tool_info = {
                "index": i,
                "name": tool.name,
                "description": tool.description or "No description available"
            }
            tools_info.append(tool_info)
        
        # 在此处导入，避免循环导入
        from ..prompts import PromptFamily
        
        # 生成用于智能筛选工具的 prompt
        prompt = PromptFamily.generate_mcp_tool_selection_prompt(query, tools_info, max_tools)

        try:
            # 让 LLM 来做工具筛选
            response = await self._call_llm_for_tool_selection(prompt)
            
            if not response:
                logger.warning("No LLM response for tool selection, using fallback")
                return self._fallback_tool_selection(all_tools, max_tools)
            
            # 记录 LLM 返回内容的片段，便于排查
            response_preview = response[:500] + "..." if len(response) > 500 else response
            logger.debug(f"LLM tool selection response: {response_preview}")
            
            # 解析 LLM 的返回 —— json_repair 能处理代码围栏与前后缀（与 deep_research 一致）
            try:
                selection_result = json_repair.loads(response)
            except Exception:
                logger.warning("Could not parse LLM tool selection JSON, using fallback")
                return self._fallback_tool_selection(all_tools, max_tools)

            if not isinstance(selection_result, dict):
                logger.warning("Tool selection response was not a JSON object, using fallback")
                return self._fallback_tool_selection(all_tools, max_tools)

            selected_tools = []

            # 处理被选中的工具
            for tool_selection in selection_result.get("selected_tools", []) or []:
                if not isinstance(tool_selection, dict):
                    continue
                tool_index = tool_selection.get("index")
                tool_name = tool_selection.get("name", "")
                reason = tool_selection.get("reason", "")
                relevance_score = tool_selection.get("relevance_score", 0)

                if tool_index is not None and 0 <= tool_index < len(all_tools):
                    selected_tools.append(all_tools[tool_index])
                    logger.info(f"Selected tool '{tool_name}' (score: {relevance_score}): {reason}")
            
            if len(selected_tools) == 0:
                logger.warning("No tools selected by LLM, using fallback selection")
                return self._fallback_tool_selection(all_tools, max_tools)
            
            # 记录整体筛选思路
            selection_reasoning = selection_result.get("selection_reasoning", "No reasoning provided")
            logger.info(f"LLM selection strategy: {selection_reasoning}")
            
            logger.info(f"LLM selected {len(selected_tools)} tools for research")
            return selected_tools
            
        except Exception as e:
            logger.error(f"Error in LLM tool selection: {e}")
            logger.warning("Falling back to pattern-based selection")
            return self._fallback_tool_selection(all_tools, max_tools)

    async def _call_llm_for_tool_selection(self, prompt: str) -> str:
        """
        复用现成的 create_chat_completion 来调用 LLM，完成工具筛选。
        
        参数：
            prompt (str): 发给 LLM 的 prompt。
            
        返回：
            str: 生成的文本回复。
        """
        if not self.cfg:
            logger.warning("No config available for LLM call")
            return ""
            
        try:
            from ..utils.llm import create_chat_completion
            
            # 组装发给 LLM 的 messages
            messages = [{"role": "user", "content": prompt}]
            
            # 工具筛选用 strategic LLM（这一步推理更复杂）
            result = await create_chat_completion(
                model=self.cfg.strategic_llm_model,
                messages=messages,
                temperature=0.0,  # 低 temperature，让筛选结果稳定
                llm_provider=self.cfg.strategic_llm_provider,
                llm_kwargs=self.cfg.llm_kwargs,
                cost_callback=self.researcher.add_costs if self.researcher and hasattr(self.researcher, 'add_costs') else None,
            )
            return result
        except Exception as e:
            logger.error(f"Error calling LLM for tool selection: {e}")
            return ""

    def _fallback_tool_selection(self, all_tools: List, max_tools: int) -> List:
        """
        LLM 筛选失败时，用模式匹配兜底挑选工具。
        
        参数：
            all_tools: 全部可用工具列表
            max_tools: 最多挑选几个工具
            
        返回：
            List: 选出的工具
        """
        # 与研究场景相关的工具名模式
        research_patterns = [
            'search', 'get', 'read', 'fetch', 'find', 'list', 'query', 
            'lookup', 'retrieve', 'browse', 'view', 'show', 'describe'
        ]
        
        scored_tools = []
        
        for tool in all_tools:
            tool_name = tool.name.lower()
            tool_description = (tool.description or "").lower()
            
            # 按模式匹配累计相关性得分
            score = 0
            for pattern in research_patterns:
                if pattern in tool_name:
                    score += 3
                if pattern in tool_description:
                    score += 1
            
            if score > 0:
                scored_tools.append((tool, score))
        
        # 按分数排序，取前几个
        scored_tools.sort(key=lambda x: x[1], reverse=True)
        selected_tools = [tool for tool, score in scored_tools[:max_tools]]
        
        for i, (tool, score) in enumerate(scored_tools[:max_tools]):
            logger.info(f"Fallback selected tool {i+1}: {tool.name} (score: {score})")
        
        return selected_tools 