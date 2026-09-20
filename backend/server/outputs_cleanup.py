"""Retention for generated report artifacts.

Every research writes .md/.docx/.json into ``outputs/``, which is mounted
publicly at ``/outputs`` and never shrank on its own — so the directory grew
without bound, one set of files per visitor. Files older than the retention
window are swept on a timer.

Filename randomisation (see ``sanitize_filename``) is what keeps a report
private; this module is only about disk. Both are needed: without randomisation
an old file stays derivable, and without retention the disk fills regardless.

Set ``OUTPUTS_RETENTION_DAYS=0`` to disable sweeping entirely.
"""

import asyncio
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path("outputs")

# Extensions this app writes for a research. Anything else in the directory
# (manual files, scratch output) is left alone.
_MANAGED_SUFFIXES = (".md", ".docx", ".json")

# How often to sweep. Retention is measured in days, so a few hours of
# granularity is plenty and keeps this off the request path.
_SWEEP_INTERVAL_SECONDS = 6 * 3600


def _retention_days() -> int:
    try:
        return int(os.getenv("OUTPUTS_RETENTION_DAYS", "7"))
    except ValueError:
        return 7


def purge_expired(now: float | None = None) -> int:
    """Delete generated files older than the retention window.

    Args:
        now: Override for the current time, for tests.

    Returns:
        int: How many files were removed.
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
            # A file being deleted twice, or held open, is not worth failing over.
            logger.warning("Could not remove expired file %s: %s", path, e)

    return removed


async def periodic_cleanup() -> None:
    """Sweep once at start-up, then on a timer. Runs until cancelled."""
    while True:
        try:
            removed = purge_expired()
            if removed:
                logger.info("Removed %d expired file(s) from outputs/", removed)
        except Exception as e:
            # Never let a sweep failure kill the loop for the life of the process.
            logger.warning("outputs cleanup failed: %s", e)
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
