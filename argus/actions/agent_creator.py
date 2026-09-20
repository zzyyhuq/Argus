"""Argus 的 agent 创建与选择工具。

本模块提供根据查询类型自动选择并配置合适研究 agent 的函数。
"""

import json
import logging
import re

import json_repair

from ..prompts import PromptFamily
from ..utils.llm import create_chat_completion

logger = logging.getLogger(__name__)

async def choose_agent(
    query,
    cfg,
    parent_query=None,
    cost_callback: callable = None,
    headers=None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
):
    """
    自动选择 agent。

    参数：
        parent_query: 有时研究会围绕主查询下的某个子主题展开。
            父查询能让 agent 了解主上下文，从而推理得更准。
        query: 原始查询
        cfg: Config
        cost_callback: 计算 LLM 花费的回调
        prompt_family: prompt 家族

    返回：
        agent: agent 名称
        agent_role_prompt: agent 角色 prompt
    """
    query = f"{parent_query} - {query}" if parent_query else f"{query}"
    response = None  # 先初始化 response，确保它一定有定义

    try:
        response = await create_chat_completion(
            model=cfg.smart_llm_model,
            messages=[
                {"role": "system", "content": f"{prompt_family.auto_agent_instructions()}"},
                {"role": "user", "content": f"task: {query}"},
            ],
            temperature=0.15,
            llm_provider=cfg.smart_llm_provider,
            llm_kwargs=cfg.llm_kwargs,
            cost_callback=cost_callback,
            **kwargs
        )

        # 优先用 json_repair，让带围栏或轻微损坏的 LLM JSON 能在主路径上
        # 直接解析成功，而不是每次都落到异常处理里。
        try:
            agent_dict = json_repair.loads(response) if response is not None else None
        except Exception:
            agent_dict = None
        if not isinstance(agent_dict, dict):
            agent_dict = json.loads(response)
        if not isinstance(agent_dict, dict):
            raise ValueError("agent JSON was not an object")
        return agent_dict["server"], agent_dict["agent_role_prompt"]

    except Exception as e:
        return await handle_json_error(response)


async def handle_json_error(response: str | None):
    """处理 LLM 响应中的 JSON 解析错误。

    对于格式不合规的 JSON 响应，依次用 json_repair 与正则提取作为兜底，
    尽量把 agent 信息捞回来。

    参数：
        response: 初次 JSON 解析失败的 LLM 响应字符串。

    返回：
        (agent_name, agent_role_prompt) 元组。若所有解析尝试都失败，
        则返回默认 agent。
    """
    try:
        agent_dict = json_repair.loads(response) if response is not None else None
        recovered = _agent_pair_from_payload(agent_dict)
        if recovered is not None:
            return recovered
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.warning(
            f"Failed to parse agent JSON with json_repair: {error_type}: {error_msg}",
            exc_info=True
        )
        if response:
            logger.debug(f"LLM response that failed to parse: {response[:500]}...")

    json_string = extract_json_with_regex(response)
    if json_string:
        try:
            json_data = json.loads(json_string)
            recovered = _agent_pair_from_payload(json_data)
            if recovered is not None:
                return recovered
        except json.JSONDecodeError as e:
            logger.warning(
                f"Failed to decode JSON from regex extraction: {str(e)}",
                exc_info=True
            )

    logger.info("No valid JSON found in LLM response. Falling back to default agent.")
    return "Default Agent", (
        "You are an AI critical thinker research assistant. Your sole purpose is to write well written, "
        "critically acclaimed, objective and structured reports on given text."
    )


def _agent_pair_from_payload(payload):
    """仅当 payload 是完整的 dict 时，才返回 (server, agent_role_prompt)。"""
    if not isinstance(payload, dict):
        return None
    server = payload.get("server")
    role = payload.get("agent_role_prompt")
    if server and role:
        return server, role
    return None


def extract_json_with_regex(response: str | None) -> str | None:
    """用正则从字符串中提取 JSON 对象。

    尝试在响应字符串里找到第一个 JSON 对象。

    参数：
        response: 要在其中查找 JSON 内容的字符串。

    返回：
        找到时返回提取出的 JSON 字符串，否则返回 None。
    """
    if not response:
        return None
    # 用贪婪的 ``{.*}``，让匹配从响应里第一个 ``{`` 一直跨到最后一个 ``}``，
    # 从而捕获完整对象。非贪婪的 ``{.*?}`` 会在第一个 ``}`` 处停下，把任何
    # 含多个键、或字符串值里带 ``}`` 的对象（例如 agent_role_prompt 里写了
    # "{markets}"）截断成非法 JSON。
    json_match = re.search(r"{.*}", response, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return None
