"""用于 LLM / 人类「none」/「no」接受信号的严格解析器。

子串判断（``"None" in response``、``"no" in feedback``）会把
"None of the criteria are met" 这类评审意见、或 "not enough cost data"
这类人类对计划的反馈误判为接受。因此这里要求信号必须精确匹配（仅允许首尾
可选的引号 / 空白），以免真正提出问题的意见被当成批准。
"""

from __future__ import annotations


def is_none_accept_response(response: str | None) -> bool:
    """仅当 *response* 恰好等于接受信号 ``None`` 时返回 True。

    允许首尾有空白，以及一对匹配的 ``'`` / ``"`` 引号（模型经常会给 token
    加上引号）。空字符串 / ``None`` 输入不算作接受——若调用方想表达
    "no review"，应当显式传递该状态，而不是依赖空字符串。
    """
    if response is None:
        return False
    if not isinstance(response, str):
        response = str(response)
    text = response.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text.lower() == "none"


def is_human_plan_approval(feedback: str | None) -> bool:
    """仅当 *feedback* 恰好等于取消/批准信号 ``no`` 时返回 True。

    人类反馈 prompt 要求用户在计划无需修改时回复 ``no``。这里整串（归一化后）
    比较，可以避免误丢掉那些只是恰好含有 ``no`` 两个字母的真实修改请求
    （例如 "not enough on evaluation"、"novel methods"）。
    """
    if feedback is None:
        return False
    if not isinstance(feedback, str):
        feedback = str(feedback)
    return feedback.strip().lower() == "no"
