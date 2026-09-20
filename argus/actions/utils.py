from typing import Dict, Any, Callable
from ..utils.logger import get_formatted_logger

logger = get_formatted_logger()


async def stream_output(
    type, content, output, websocket=None, output_log=True, metadata=None
):
    """
    把输出流式发送到 websocket

    参数：
        type:
        content:
        output:

    返回：
        None
    """
    if (not websocket or output_log) and type != "images":
        try:
            logger.info(f"{output}")
        except UnicodeEncodeError:
            # 方案 1：把有问题的字符替换成占位符
            logger.error(output.encode(
                'cp1252', errors='replace').decode('cp1252'))

    if websocket:
        await websocket.send_json(
            {"type": type, "content": content,
                "output": output, "metadata": metadata}
        )


async def safe_send_json(websocket: Any, data: Dict[str, Any]) -> None:
    """
    通过 WebSocket 连接安全地发送 JSON 数据。

    参数：
        websocket (WebSocket): 用于发送数据的 WebSocket 连接。
        data (Dict[str, Any]): 要作为 JSON 发送的数据。

    返回：
        None
    """
    try:
        await websocket.send_json(data)
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(
            f"Error sending JSON through WebSocket: {error_type}: {error_msg}",
            exc_info=True
        )
        # 针对常见的 WebSocket 错误补充更有用的上下文
        if "closed" in error_msg.lower() or "connection" in error_msg.lower():
            logger.warning("WebSocket connection appears to be closed. Client may have disconnected.")
        elif "timeout" in error_msg.lower():
            logger.warning("WebSocket send operation timed out. The client may be unresponsive.")


def calculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str
) -> float:
    """
    根据 token 数量与所用模型计算 API 的使用花费。

    参数：
        prompt_tokens (int): prompt 中的 token 数。
        completion_tokens (int): completion 中的 token 数。
        model (str): 本次 API 调用使用的模型。

    返回：
        float: 计算出的花费，单位为 USD。
    """
    try:
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid token counts for cost calculation "
            f"(prompt={prompt_tokens!r}, completion={completion_tokens!r}); treating as 0."
        )
        prompt_tokens = 0
        completion_tokens = 0
    if prompt_tokens < 0:
        prompt_tokens = 0
    if completion_tokens < 0:
        completion_tokens = 0
    if not isinstance(model, str) or not model:
        model = ""

    # 各模型每 1k token 的单价
    costs = {
        "gpt-3.5-turbo": 0.002,
        "gpt-4": 0.03,
        "gpt-4-32k": 0.06,
        "gpt-4o": 0.00001,
        "gpt-4o-mini": 0.000001,
        "o3-mini": 0.0000005,
        # 需要时在此补充更多模型及其单价
    }

    model = model.lower()
    if model not in costs:
        logger.warning(
            f"Unknown model: {model}. Cost calculation may be inaccurate.")
        return 0.0001 # 模型未知时使用的默认平均花费

    cost_per_1k = costs[model]
    total_tokens = prompt_tokens + completion_tokens
    return (total_tokens / 1000) * cost_per_1k


def format_token_count(count: int) -> str:
    """
    用千位分隔符格式化 token 数，便于阅读。

    参数：
        count (int): 要格式化的 token 数。

    返回：
        str: 格式化后的 token 数。
    """
    try:
        value = int(count or 0)
    except (TypeError, ValueError):
        return "0"
    return f"{value:,}"


async def update_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    websocket: Any
) -> None:
    """
    更新花费信息，并通过 WebSocket 发送出去。

    参数：
        prompt_tokens (int): prompt 中的 token 数。
        completion_tokens (int): completion 中的 token 数。
        model (str): 本次 API 调用使用的模型。
        websocket (WebSocket): 用于发送数据的 WebSocket 连接。

    返回：
        None
    """
    cost = calculate_cost(prompt_tokens, completion_tokens, model)
    total_tokens = prompt_tokens + completion_tokens

    await safe_send_json(websocket, {
        "type": "cost",
        "data": {
            "total_tokens": format_token_count(total_tokens),
            "prompt_tokens": format_token_count(prompt_tokens),
            "completion_tokens": format_token_count(completion_tokens),
            "total_cost": f"${cost:.4f}"
        }
    })


def create_cost_callback(websocket: Any) -> Callable:
    """
    创建一个用于更新花费的回调函数。

    参数：
        websocket (WebSocket): 用于发送数据的 WebSocket 连接。

    返回：
        Callable: 可用于更新花费的回调函数。
    """
    async def cost_callback(
        prompt_tokens: int,
        completion_tokens: int,
        model: str
    ) -> None:
        await update_cost(prompt_tokens, completion_tokens, model, websocket)

    return cost_callback
