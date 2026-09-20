"""Argus 的 LLM 工具函数。

本模块通过统一接口，提供与各类 LLM 服务商交互的工具函数。
"""
from __future__ import annotations

import logging
import os
from typing import Any
import asyncio

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from argus.llm_provider.generic.base import (
    NO_SUPPORT_TEMPERATURE_MODELS,
    SUPPORT_REASONING_EFFORT_MODELS,
    ReasoningEfforts,
)

from ..prompts import PromptFamily
from .costs import calculate_llm_cost
from .validators import Subtopics


def get_llm(llm_provider: str, **kwargs):
    """获取一个 LLM 服务商实例。

    参数：
        llm_provider: LLM 服务商名称（如 'openai'、'anthropic'）。
        **kwargs: 透传给服务商的额外关键字参数。

    返回：
        按指定服务商配置好的 GenericLLMProvider 实例。
    """
    from argus.llm_provider import GenericLLMProvider
    return GenericLLMProvider.from_provider(llm_provider, **kwargs)


async def create_chat_completion(
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = 0.4,
        max_tokens: int | None = 4000,
        llm_provider: str | None = None,
        stream: bool = False,
        websocket: Any | None = None,
        llm_kwargs: dict[str, Any] | None = None,
        cost_callback: callable = None,
        reasoning_effort: str | None = ReasoningEfforts.Medium.value,
        **kwargs
) -> str:
    """使用 OpenAI API 创建一次 chat completion
    参数：
        messages (list[dict[str, str]]): 发送给 chat completion 的消息。
        model (str, optional): 使用的模型。默认为 None。
        temperature (float, optional): 使用的 temperature。默认为 0.4。
        max_tokens (int, optional): 使用的最大 token 数。默认为 4000。
        llm_provider (str, optional): 使用的 LLM 服务商。
        stream (bool): 是否流式返回响应。默认为 False。
        webocket (WebSocket): 当前请求所用的 websocket，
        llm_kwargs (dict[str, Any], optional): 额外的 LLM 关键字参数。默认为 None。
        cost_callback: 用于更新成本的回调函数。
        reasoning_effort (str, optional): OpenAI reasoning 模型的 reasoning effort。默认为 'low'。
        **kwargs: 额外的关键字参数。
    返回：
        str: chat completion 返回的响应。
    """
    # 校验入参
    if model is None:
        raise ValueError("Model cannot be None")
    # 兜底拦截明显离谱的取值（例如环境变量拼错）。真正的单模型输出上限
    # 由上游服务商把关。
    if max_tokens is not None and max_tokens > 200_000:
        raise ValueError(
            f"max_tokens={max_tokens} exceeds the largest output limit of "
            "any currently available model (128k as of late 2025). "
            "Check your FAST_TOKEN_LIMIT / SMART_TOKEN_LIMIT / "
            "STRATEGIC_TOKEN_LIMIT env vars for typos."
        )

    # 从受支持的服务商中取出对应的 provider
    provider_kwargs = {'model': model}

    if llm_kwargs:
        provider_kwargs.update(llm_kwargs)
    elif os.environ.get("LLM_KWARGS"):
        import json
        try:
            provider_kwargs.update(json.loads(os.environ["LLM_KWARGS"]))
        except json.JSONDecodeError:
            pass

    if model in SUPPORT_REASONING_EFFORT_MODELS:
        provider_kwargs['reasoning_effort'] = reasoning_effort

    if model not in NO_SUPPORT_TEMPERATURE_MODELS:
        provider_kwargs['temperature'] = temperature
    else:
        # 这些模型强制使用自己的默认 temperature，但输出上限依然生效
        # （langchain-openai 会把 max_tokens 映射到 API 的
        # max_completion_tokens）。注意 reasoning 模型的这个上限也把
        # reasoning token 算在内，因此预算需要留更多余量。
        provider_kwargs['temperature'] = None
    provider_kwargs['max_tokens'] = max_tokens

    if llm_provider == "openai":
        base_url = os.environ.get("OPENAI_BASE_URL", None)
        if base_url:
            provider_kwargs['openai_api_base'] = base_url

    provider = get_llm(llm_provider, **provider_kwargs)
    response = ""
    # 生成响应
    max_attempts = 1 if (stream and websocket is not None) else 10
    last_exception: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await provider.get_chat_response(
                messages, stream, websocket, **kwargs
            )
        except Exception as exc:
            last_exception = exc
            logging.getLogger(__name__).warning(
                f"LLM request failed (attempt {attempt}/{max_attempts}): {exc}"
            )
            if attempt < max_attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                continue
            break

        if not response:
            last_exception = RuntimeError("Empty response from LLM provider")
            logging.getLogger(__name__).warning(
                f"LLM returned empty response (attempt {attempt}/{max_attempts})"
            )
            if attempt < max_attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                continue
            break

        if cost_callback:
            llm_costs = calculate_llm_cost(
                llm_provider=llm_provider,
                model=model,
                input_content=str(messages),
                output_content=response,
                response_metadata=provider.last_response_metadata,
                usage_metadata=provider.last_usage_metadata,
                request_options=provider_kwargs,
            )
            cost_callback(llm_costs)

        return response

    logging.error(f"Failed to get response from {llm_provider} API")
    raise RuntimeError(f"Failed to get response from {llm_provider} API") from last_exception


async def construct_subtopics(
    task: str,
    data: str,
    config,
    subtopics: list = [],
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> list:
    """
    根据给定任务与数据构造子主题。

    参数：
        task (str): 主任务或主题。
        data (str): 用于提供上下文的补充数据。
        config: 配置项。
        subtopics (list, optional): 已有的子主题。默认为 []。
        prompt_family (PromptFamily): prompt 家族
        **kwargs: 额外的关键字参数。

    返回：
        list: 构造出的子主题列表。
    """
    try:
        parser = PydanticOutputParser(pydantic_object=Subtopics)

        prompt = PromptTemplate(
            template=prompt_family.generate_subtopics_prompt(),
            input_variables=["task", "data", "subtopics", "max_subtopics"],
            partial_variables={
                "format_instructions": parser.get_format_instructions()},
        )

        provider_kwargs = {'model': config.smart_llm_model}

        if config.llm_kwargs:
            provider_kwargs.update(config.llm_kwargs)

        if config.smart_llm_model in SUPPORT_REASONING_EFFORT_MODELS:
            provider_kwargs['reasoning_effort'] = ReasoningEfforts.High.value
        else:
            provider_kwargs['temperature'] = config.temperature
        provider_kwargs['max_tokens'] = config.smart_token_limit

        provider = get_llm(config.smart_llm_provider, **provider_kwargs)

        model = provider.llm

        chain = prompt | model | parser

        output = await chain.ainvoke({
            "task": task,
            "data": data,
            "subtopics": subtopics,
            "max_subtopics": config.max_subtopics
        }, **kwargs)

        return output

    except Exception as e:
        logging.getLogger(__name__).error(
            "Exception in parsing subtopics: %s", e, exc_info=True
        )
        return subtopics
