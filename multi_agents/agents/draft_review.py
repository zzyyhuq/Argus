DEFAULT_MAX_DRAFT_REVISIONS = 3


class MaxDraftRevisionsExceededError(RuntimeError):
    """reviewer/reviser 轮次超过所配置的草稿上限时抛出。"""


def route_draft_review(draft, max_draft_revisions=DEFAULT_MAX_DRAFT_REVISIONS):
    """为 editor 的 review 循环返回 accept | revise。

    * ``review is None`` → accept（也包括触发硬上限被强制 accept、由调用方清空
      review 之后的情况）。
    * ``max_draft_revisions is None`` → 永不强制 accept（运维侧主动关闭该机制）。
    * ``draft_revision_count > max`` → 抛异常，让边能优雅地强制 accept，
      而不是撞上 LangGraph 的 recursion_limit。
    """
    if draft.get("review") is None:
        return "accept"

    if max_draft_revisions is None:
        return "revise"

    count = draft.get("draft_revision_count", 0)
    if count > max_draft_revisions:
        raise MaxDraftRevisionsExceededError(
            "Draft revision limit exceeded. "
            f"Received {count} revision rounds; "
            f"max_draft_revisions is {max_draft_revisions}."
        )

    return "revise"
