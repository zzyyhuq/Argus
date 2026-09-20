import os
import sys
from typing import Any, Awaitable, Callable

RunResearchTask = Callable[..., Awaitable[Any]]


def _ensure_repo_root_on_path() -> None:
    """Ensure top-level repo root is importable for multi-agent modules."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _resolve_run_research_task() -> RunResearchTask:
    _ensure_repo_root_on_path()

    # 延迟导入：多智能体那一套依赖 langgraph，只有真正请求时才加载，避免给
    # 其他路径的启动增加开销与硬依赖。
    try:
        from multi_agents.main import run_research_task
        return run_research_task
    except Exception as e:
        raise ImportError("无法从 multi_agents 导入 run_research_task") from e


async def run_multi_agent_task(*args, **kwargs) -> Any:
    run_research_task = _resolve_run_research_task()
    return await run_research_task(*args, **kwargs)
