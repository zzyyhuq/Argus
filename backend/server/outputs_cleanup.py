"""生成出来的报告文件的保留策略。

每次研究都会往 ``outputs/`` 写入 .md/.docx/.json，而这个目录以 ``/outputs``
对外公开挂载，又从来不会自己变小——于是它会无限膨胀，每位访客留下一套文件。超过
保留期的文件由定时任务清掉。

让报告保持私密靠的是文件名随机化（见 ``sanitize_filename``）；本模块只管磁盘。
两者都需要：没有随机化，旧文件仍然可被推导出来；没有保留策略，磁盘无论如何都会
被塞满。

把 ``OUTPUTS_RETENTION_DAYS`` 设为 0 可完全关闭清理。
"""

import asyncio
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path("outputs")

# 本应用给一次研究写出的扩展名。目录里别的东西（手工放进去的文件、临时输出）
# 一律不碰。
_MANAGED_SUFFIXES = (".md", ".docx", ".json")

# 清理的间隔。保留期以天计，几小时的粒度足够，也让这件事不落在请求路径上。
_SWEEP_INTERVAL_SECONDS = 6 * 3600


def _retention_days() -> int:
    try:
        return int(os.getenv("OUTPUTS_RETENTION_DAYS", "7"))
    except ValueError:
        return 7


def purge_expired(now: float | None = None) -> int:
    """删除超过保留期的生成文件。

    参数：
        now: 覆盖当前时间，供测试使用。

    返回：
        int: 删掉了多少个文件。
    """
    days = _retention_days()
    if days <= 0 or not OUTPUTS_DIR.is_dir():
        return 0

    cutoff = (now if now is not None else time.time()) - days * 86400
    removed = 0

    for path in OUTPUTS_DIR.glob("task_*"):
        if path.suffix not in _MANAGED_SUFFIXES or not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as e:
            # 文件被重复删除、或被别的进程占着，都不值得让整个清理失败。
            logger.warning("Could not remove expired file %s: %s", path, e)

    return removed


async def periodic_cleanup() -> None:
    """启动时先清理一次，之后按定时器清理。一直运行到被取消。"""
    while True:
        try:
            removed = purge_expired()
            if removed:
                logger.info("Removed %d expired file(s) from outputs/", removed)
        except Exception as e:
            # 绝不能让某次清理失败把循环弄死，那会影响到进程的整个生命周期。
            logger.warning("outputs cleanup failed: %s", e)
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
