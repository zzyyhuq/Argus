"""LLM API 调用的成本估算工具。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import tiktoken

# 依据 OpenAI 定价页：https://openai.com/api/pricing/
ENCODING_MODEL = "o200k_base"
INPUT_COST_PER_TOKEN = 0.000005
OUTPUT_COST_PER_TOKEN = 0.000015
IMAGE_INFERENCE_COST = 0.003825
EMBEDDING_COST = 0.02 / 1000000  # 按新版 ada-3-small 估算

# OpenAI 的自动 prompt 缓存会对命中缓存的那部分输入 token 按标准输入价
# 打折计费（目前 GPT-4o/4.1/5 全系均为 50%）。这里只留一个常量，是因为
# OpenAI 至今对所有支持缓存的模型都用统一的 50% 折扣；若将来某个模型引入
# 不同比例，再回来调整。
# https://openai.com/api/pricing/
OPENAI_CACHED_INPUT_DISCOUNT = 0.5

logger = logging.getLogger(__name__)

# (匹配模式, 输入 $/百万 token, 输出 $/百万 token) —— 先匹配者胜出，因此
# 更具体的模式（如 "-mini"）必须排在它对应的基础模型之前。
# 价格截至 2026 年 7 月：https://openai.com/api/pricing/
OPENAI_MODEL_PRICING = (
    (("gpt-5.5-pro",), 30.0, 180.0),
    (("gpt-5.5",), 5.0, 30.0),
    (("gpt-5.4-pro",), 30.0, 180.0),
    (("gpt-5.4-mini",), 0.75, 4.5),
    (("gpt-5.4-nano",), 0.2, 1.25),
    (("gpt-5.4",), 2.5, 15.0),
    (("gpt-5-mini",), 0.25, 2.0),
    (("gpt-5-nano",), 0.05, 0.4),
    (("gpt-5",), 1.25, 10.0),
    (("gpt-4.1-mini",), 0.4, 1.6),
    (("gpt-4.1-nano",), 0.1, 0.4),
    (("gpt-4.1",), 2.0, 8.0),
    (("gpt-4o-mini",), 0.15, 0.6),
    (("gpt-4o",), 2.5, 10.0),
    (("o4-mini",), 1.1, 4.4),
    (("o3-mini",), 1.1, 4.4),
    (("o3",), 2.0, 8.0),
)

ANTHROPIC_MODEL_PRICING = (
    (("claude-opus-4-7",), 5.0, 25.0),
    (("claude-opus-4-6",), 5.0, 25.0),
    (("claude-opus-4-5", "claude-4-opus"), 5.0, 25.0),
    (("claude-opus-4-1",), 15.0, 75.0),
    (("claude-opus-4",), 15.0, 75.0),
    (("claude-sonnet-4-6",), 3.0, 15.0),
    (("claude-sonnet-4-5", "claude-4-sonnet"), 3.0, 15.0),
    (("claude-sonnet-4",), 3.0, 15.0),
    (("claude-haiku-4-5",), 1.0, 5.0),
    (("claude-3-5-haiku",), 0.8, 4.0),
)

ANTHROPIC_US_INFERENCE_GEO_MODELS = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)


def estimate_llm_cost(input_content: str, output_content: str) -> float:
    """根据输入与输出内容估算一次 LLM API 调用的成本。

    估算基于 OpenAI 的定价，用于其他模型时可能不准确。

    参数：
        input_content: 发送给 LLM 的输入文本。
        output_content: 从 LLM 收到的输出文本。

    返回：
        估算成本，单位为美元。
    """
    # 回调与流式路径可能在内容就绪前传入 None，而 tiktoken.encode(None)
    # 会抛 TypeError 并连带中断调用方，所以这里先兜底成空串。
    if input_content is None:
        input_content = ""
    if output_content is None:
        output_content = ""
    if not isinstance(input_content, str):
        input_content = str(input_content)
    if not isinstance(output_content, str):
        output_content = str(output_content)
    encoding = tiktoken.get_encoding(ENCODING_MODEL)
    input_tokens = encoding.encode(input_content)
    output_tokens = encoding.encode(output_content)
    input_costs = len(input_tokens) * INPUT_COST_PER_TOKEN
    output_costs = len(output_tokens) * OUTPUT_COST_PER_TOKEN
    return input_costs + output_costs


def _mapping_to_dict(value: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    return {}


def _resolve_anthropic_model_name(
    model: str | None,
    response_metadata: Mapping[str, Any] | None = None,
) -> str:
    metadata = _mapping_to_dict(response_metadata)
    return str(
        metadata.get("model")
        or metadata.get("model_name")
        or model
        or ""
    ).lower()


def _coerce_token_count(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_anthropic_usage(
    response_metadata: Mapping[str, Any] | None = None,
    usage_metadata: Mapping[str, Any] | Any | None = None,
) -> dict[str, int] | None:
    """提取 Anthropic 的用量信息，含 prompt 缓存相关的 token 字段。

    Anthropic Messages 的 usage 可能包含：
    - input_tokens / output_tokens
    - cache_creation_input_tokens（按输入价约 1.25 倍计费）
    - cache_read_input_tokens（按输入价约 0.1 倍计费）
    """
    metadata = _mapping_to_dict(response_metadata)
    usage = _mapping_to_dict(metadata.get("usage"))

    def _from_usage(usage_dict: dict[str, Any]) -> dict[str, int] | None:
        input_tokens = usage_dict.get("input_tokens")
        output_tokens = usage_dict.get("output_tokens")
        if input_tokens is None or output_tokens is None:
            return None
        return {
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cache_creation_input_tokens": _coerce_token_count(
                usage_dict.get("cache_creation_input_tokens")
            ),
            "cache_read_input_tokens": _coerce_token_count(
                usage_dict.get("cache_read_input_tokens")
            ),
        }

    if usage:
        parsed = _from_usage(usage)
        if parsed is not None:
            return parsed

    usage = _mapping_to_dict(usage_metadata)
    return _from_usage(usage)


def _get_anthropic_pricing(model_name: str) -> tuple[float, float] | None:
    normalized_model_name = model_name.lower()
    for patterns, input_price_per_mtok, output_price_per_mtok in ANTHROPIC_MODEL_PRICING:
        if any(pattern in normalized_model_name for pattern in patterns):
            return input_price_per_mtok, output_price_per_mtok
    return None


def _get_anthropic_pricing_multiplier(
    model_name: str,
    request_options: Mapping[str, Any] | None = None,
) -> float:
    if not request_options:
        return 1.0

    inference_geo = str(request_options.get("inference_geo", "")).lower()
    if inference_geo != "us":
        return 1.0

    if any(pattern in model_name for pattern in ANTHROPIC_US_INFERENCE_GEO_MODELS):
        return 1.1

    return 1.0


def calculate_anthropic_cost(
    model: str | None,
    response_metadata: Mapping[str, Any] | None = None,
    usage_metadata: Mapping[str, Any] | Any | None = None,
    request_options: Mapping[str, Any] | None = None,
) -> float | None:
    usage = _extract_anthropic_usage(response_metadata=response_metadata, usage_metadata=usage_metadata)
    if not usage:
        return None

    model_name = _resolve_anthropic_model_name(model=model, response_metadata=response_metadata)
    pricing = _get_anthropic_pricing(model_name)
    if pricing is None:
        logger.warning(
            "Missing Anthropic pricing rule for model '%s'; falling back to token estimator.",
            model_name or model,
        )
        return None

    input_price_per_mtok, output_price_per_mtok = pricing
    multiplier = _get_anthropic_pricing_multiplier(model_name, request_options=request_options)
    # Anthropic 的 prompt 缓存：写入按输入价约 1.25 倍、读取按约 0.1 倍计费。
    # input_tokens 只统计未命中缓存的输入；缓存那部分单独计费。
    cache_write_price_per_mtok = input_price_per_mtok * 1.25
    cache_read_price_per_mtok = input_price_per_mtok * 0.1
    input_cost = usage["input_tokens"] * input_price_per_mtok / 1_000_000
    cache_write_cost = (
        usage.get("cache_creation_input_tokens", 0) * cache_write_price_per_mtok / 1_000_000
    )
    cache_read_cost = (
        usage.get("cache_read_input_tokens", 0) * cache_read_price_per_mtok / 1_000_000
    )
    output_cost = usage["output_tokens"] * output_price_per_mtok / 1_000_000
    return (input_cost + cache_write_cost + cache_read_cost + output_cost) * multiplier


def _extract_usage_tokens(
    usage_metadata: Mapping[str, Any] | Any | None,
) -> tuple[int, int, int] | None:
    """返回 (input_tokens, output_tokens, cache_read_tokens)。

    cache_read_tokens 是 input_tokens 中命中服务商 prompt 缓存的那部分
    （即 LangChain 标准化的 ``input_token_details.cache_read``），应按
    OPENAI_CACHED_INPUT_DISCOUNT 折扣价而非标准输入价计费。响应未上报
    缓存明细时取 0，因此未走缓存的调用不受影响。
    """
    usage = _mapping_to_dict(usage_metadata)
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is None or output_tokens is None:
        return None

    input_token_details = _mapping_to_dict(usage.get("input_token_details"))
    cache_read_tokens = int(input_token_details.get("cache_read") or 0)

    return int(input_tokens), int(output_tokens), cache_read_tokens


def _get_openai_pricing(model: str | None) -> tuple[float, float] | None:
    normalized = (model or "").lower()
    for patterns, input_price_per_mtok, output_price_per_mtok in OPENAI_MODEL_PRICING:
        if any(pattern in normalized for pattern in patterns):
            return input_price_per_mtok, output_price_per_mtok
    return None


def calculate_llm_cost(
    llm_provider: str | None,
    model: str | None,
    input_content: str,
    output_content: str,
    response_metadata: Mapping[str, Any] | None = None,
    usage_metadata: Mapping[str, Any] | Any | None = None,
    request_options: Mapping[str, Any] | None = None,
) -> float:
    if llm_provider == "anthropic":
        anthropic_cost = calculate_anthropic_cost(
            model=model,
            response_metadata=response_metadata,
            usage_metadata=usage_metadata,
            request_options=request_options,
        )
        if anthropic_cost is not None:
            return anthropic_cost

    # 对序列化后的 message dict，优先采用 API 上报的 token 用量而非 tiktoken
    # 估算：后者会把输入算多，而且完全漏掉 reasoning token。
    usage_tokens = _extract_usage_tokens(usage_metadata)
    if usage_tokens is not None:
        input_tokens, output_tokens, cache_read_tokens = usage_tokens
        # cache_read_tokens 是 input_tokens 的子集而非额外 token —— 把
        # input_tokens 拆成未缓存与已缓存两部分，好让命中缓存的份额按折扣价
        # 而非全额输入价计费。
        non_cached_input_tokens = input_tokens - cache_read_tokens
        pricing = _get_openai_pricing(model)
        if pricing is not None:
            input_price_per_mtok, output_price_per_mtok = pricing
            non_cached_cost = non_cached_input_tokens * input_price_per_mtok
            cached_cost = (
                cache_read_tokens
                * input_price_per_mtok
                * OPENAI_CACHED_INPUT_DISCOUNT
            )
            output_cost = output_tokens * output_price_per_mtok
            return (non_cached_cost + cached_cost + output_cost) / 1_000_000
        cached_cost = (
            cache_read_tokens * INPUT_COST_PER_TOKEN * OPENAI_CACHED_INPUT_DISCOUNT
        )
        non_cached_cost = non_cached_input_tokens * INPUT_COST_PER_TOKEN
        return (
            non_cached_cost
            + cached_cost
            + output_tokens * OUTPUT_COST_PER_TOKEN
        )

    return estimate_llm_cost(input_content, output_content)


def estimate_embedding_cost(model: str, docs: list) -> float:
    """估算文档 embedding 的成本。

    参数：
        model: embedding 模型名称。
        docs: 待 embedding 的文档列表。

    返回：
        估算的 embedding 成本，单位为美元。
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # tiktoken 只认识 OpenAI 的模型名。非 OpenAI 的 embedding 服务商
        # （Ollama、Cohere、Nomic、HuggingFace 等）会在这里抛 KeyError，
        # 从而在研究过程中打断成本统计。退回默认 OpenAI 编码，尽力估个
        # token 数。
        encoding = tiktoken.get_encoding(ENCODING_MODEL)
    total_tokens = sum(len(encoding.encode(str(doc))) for doc in docs)
    return total_tokens * EMBEDDING_COST