import json_repair
import logging
from typing import Any, Dict, List

from argus.llm_provider.generic.base import ReasoningEfforts

from ..config import Config
from ..prompts import PromptFamily
from ..utils.llm import create_chat_completion


def _normalize_sub_queries(parsed: Any, fallback_query: str) -> List[str]:
    """把解析后的 LLM 响应统一整理成扁平的查询字符串列表。

    ``json_repair.loads`` 可能返回列表、字典（如 ``{"queries": [...]}``
    或单个 ``{"query": "..."}``）、裸字符串，或者在模型没返回干净 JSON 时
    返回 ``None``。调用方期望拿到 ``list[str]``，否则会在 ``.append`` /
    迭代时崩掉，所以这里做防御性归一化。
    """
    if isinstance(parsed, dict):
        for key in ("queries", "sub_queries", "subQueries", "items"):
            value = parsed.get(key)
            if isinstance(value, list):
                parsed = value
                break
        else:
            # 形如 {"query": "..."} 的单查询字典，或无法识别的结构。
            single = parsed.get("query")
            parsed = [single] if isinstance(single, str) else []

    if isinstance(parsed, str):
        parsed = [parsed] if parsed.strip() else []

    if not isinstance(parsed, list):
        parsed = []

    queries = [str(item).strip() for item in parsed if str(item).strip()]
    if not queries and fallback_query.strip():
        return [fallback_query.strip()]
    return queries

logger = logging.getLogger(__name__)

async def get_search_results(
    query: str,
    retriever: Any,
    query_domains: List[str] = None,
    researcher=None,
    max_results: int | None = None,
) -> List[Dict[str, Any]]:
    """
    获取给定查询的网络搜索结果。

    参数：
        query: 搜索查询
        retriever: retriever 实例
        query_domains: 可选的待搜索域名列表
        researcher: researcher 实例（MCP retriever 需要）
        max_results: 可选的结果数量上限

    返回：
        搜索结果列表
    """
    import asyncio

    # 判断是不是 MCP retriever，是则把 researcher 实例传进去
    if "mcpretriever" in retriever.__name__.lower():
        search_retriever = retriever(
            query, 
            query_domains=query_domains,
            researcher=researcher  # MCP retriever 需要 researcher 实例
        )
    else:
        search_retriever = retriever(query, query_domains=query_domains)

    search_kwargs = {}
    if max_results is not None:
        search_kwargs["max_results"] = max_results

    # retriever 的搜索是阻塞式 HTTP 调用，别让它占住事件循环
    return await asyncio.to_thread(search_retriever.search, **search_kwargs)

async def generate_sub_queries(
    query: str,
    parent_query: str,
    report_type: str,
    context: List[Dict[str, Any]],
    cfg: Config,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> List[str]:
    """
    用指定的 LLM 模型生成子查询。

    参数：
        query: 原始查询
        parent_query: 父查询
        report_type: 报告类型
        max_iterations: 研究迭代的最大次数
        context: 搜索结果的上下文
        cfg: 配置对象
        cost_callback: 计算花费的回调
        prompt_family: prompt 家族

    返回：
        子查询列表
    """
    gen_queries_prompt = prompt_family.generate_search_queries_prompt(
        query,
        parent_query,
        report_type,
        max_iterations=cfg.max_iterations or 3,
        context=context,
        language=cfg.language,
    )

    try:
        response = await create_chat_completion(
            model=cfg.strategic_llm_model,
            messages=[{"role": "user", "content": gen_queries_prompt}],
            llm_provider=cfg.strategic_llm_provider,
            max_tokens=None,
            llm_kwargs=cfg.llm_kwargs,
            reasoning_effort=ReasoningEfforts.Medium.value,
            cost_callback=cost_callback,
            **kwargs
        )
    except Exception as e:
        logger.warning(f"Error with strategic LLM: {e}. Retrying with max_tokens={cfg.strategic_token_limit}.")
        logger.warning(f"See https://github.com/assafelovic/gpt-researcher/issues/1022")
        try:
            response = await create_chat_completion(
                model=cfg.strategic_llm_model,
                messages=[{"role": "user", "content": gen_queries_prompt}],
                max_tokens=cfg.strategic_token_limit,
                llm_provider=cfg.strategic_llm_provider,
                llm_kwargs=cfg.llm_kwargs,
                cost_callback=cost_callback,
                **kwargs
            )
            logger.warning(f"Retrying with max_tokens={cfg.strategic_token_limit} successful.")
        except Exception as e:
            logger.warning(f"Retrying with max_tokens={cfg.strategic_token_limit} failed.")
            logger.warning(f"Error with strategic LLM: {e}. Falling back to smart LLM.")
            response = await create_chat_completion(
                model=cfg.smart_llm_model,
                messages=[{"role": "user", "content": gen_queries_prompt}],
                temperature=cfg.temperature,
                max_tokens=cfg.smart_token_limit,
                llm_provider=cfg.smart_llm_provider,
                llm_kwargs=cfg.llm_kwargs,
                cost_callback=cost_callback,
                **kwargs
            )

    return _normalize_sub_queries(json_repair.loads(response), query)

async def plan_research_outline(
    query: str,
    search_results: List[Dict[str, Any]],
    agent_role_prompt: str,
    cfg: Config,
    parent_query: str,
    report_type: str,
    cost_callback: callable = None,
    retriever_names: List[str] = None,
    **kwargs
) -> List[str]:
    """
    通过生成子查询来规划研究大纲。

    参数：
        query: 原始查询
        search_results: 初始搜索结果
        agent_role_prompt: agent 角色 prompt
        cfg: 配置对象
        parent_query: 父查询
        report_type: 报告类型
        cost_callback: 计算花费的回调
        retriever_names: 正在使用的 retriever 名称

    返回：
        子查询列表
    """
    # 处理未提供 retriever_names 的情况
    if retriever_names is None:
        retriever_names = []
    
    # 对 MCP retriever，可能要跳过子查询生成
    # 判断 MCP 是唯一的 retriever，还是多个 retriever 之一
    if retriever_names and ("mcp" in retriever_names or "MCPRetriever" in retriever_names):
        mcp_only = (len(retriever_names) == 1 and 
                   ("mcp" in retriever_names or "MCPRetriever" in retriever_names))
        
        if mcp_only:
            # MCP 是唯一 retriever 时，跳过子查询生成
            logger.info("Using MCP retriever only - skipping sub-query generation")
            # 返回原始查询，避免产生额外的搜索迭代
            return [query]
        else:
            # MCP 只是多个 retriever 之一时，为其他 retriever 生成子查询
            logger.info("Using MCP with other retrievers - generating sub-queries for non-MCP retrievers")

    # 为研究大纲生成子查询
    sub_queries = await generate_sub_queries(
        query,
        parent_query,
        report_type,
        search_results,
        cfg,
        cost_callback,
        **kwargs
    )

    return sub_queries
