"""
抓取请求的全局限流器。

确保 SCRAPER_RATE_LIMIT_DELAY 在**所有** WorkerPool 之间全局生效，而不只是
各自为政。这样多个并行的 researcher 就不会把 Firecrawl 这类有限流的 API 打爆。
"""
import asyncio
import time
from typing import ClassVar


class GlobalRateLimiter:
    """
    单例全局限流器。

    保证整个应用里任意两次抓取请求之间都满足最小间隔，无论同时跑着多少个
    WorkerPool 或 Argus 实例。
    """

    _instance: ClassVar['GlobalRateLimiter'] = None
    _lock: ClassVar[asyncio.Lock] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化全局限流器（只执行一次）。"""
        if self._initialized:
            return

        self.last_request_time = 0.0
        self.rate_limit_delay = 0.0
        self._initialized = True

        # 锁放在类属性上，确保所有实例共用同一把
        if GlobalRateLimiter._lock is None:
            # 注意：真正初始化要等到首次在 async 上下文中访问时
            GlobalRateLimiter._lock = None

    @classmethod
    def get_lock(cls):
        """获取或创建异步锁（必须在 async 上下文中调用）。"""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    def configure(self, rate_limit_delay: float):
        """
        配置全局限流间隔。

        参数：
            rate_limit_delay: 两次请求之间的最小间隔秒数（0 表示不限流）
        """
        # 环境变量/配置可能给的是字符串，而 wait_if_needed 是按 float 比较的。
        if rate_limit_delay is None:
            self.rate_limit_delay = 0.0
            return
        try:
            delay = float(rate_limit_delay)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"rate_limit_delay must be a number, got {rate_limit_delay!r}"
            ) from e
        if delay < 0:
            raise ValueError(f"rate_limit_delay must be non-negative, got {delay}")
        self.rate_limit_delay = delay

    async def wait_if_needed(self):
        """
        按需等待，以落实全局限流。

        无论同时有多少个 WorkerPool 在跑，本方法都能保证
        SCRAPER_RATE_LIMIT_DELAY 被全局遵守。
        """
        if self.rate_limit_delay <= 0:
            return  # 未启用限流

        lock = self.get_lock()
        async with lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time

            if time_since_last < self.rate_limit_delay:
                sleep_time = self.rate_limit_delay - time_since_last
                await asyncio.sleep(sleep_time)

            self.last_request_time = time.time()

    def reset(self):
        """重置限流器状态（便于测试）。"""
        self.last_request_time = 0.0


# 单例实例
_global_rate_limiter = GlobalRateLimiter()


def get_global_rate_limiter() -> GlobalRateLimiter:
    """获取全局限流器单例。"""
    return _global_rate_limiter
