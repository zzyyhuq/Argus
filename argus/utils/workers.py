import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from .rate_limiter import get_global_rate_limiter


class WorkerPool:
    def __init__(self, max_workers: int, rate_limit_delay: float = 0.0):
        """
        初始化 WorkerPool 的并发度与限流参数。

        参数：
            max_workers: 最大并发 worker 数
            rate_limit_delay: 全局最小请求间隔秒数（0 表示不限流）
                             该间隔在**所有** WorkerPool 之间统一生效，以免把
                             有限流的 API 打爆。
                             例如：10 req/min（Firecrawl 免费档）对应 6.0

        注意：
            rate_limit_delay 是**全局**生效的，靠单例限流器实现。也就是说，
            即便你同时跑多个 Argus 实例（例如深度研究里），它们也共享同一个
            限流额度，从而避免 API 过载。
        """
        self.max_workers = max_workers
        self.rate_limit_delay = rate_limit_delay
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = asyncio.Semaphore(max_workers)

        # 配置全局限流器
        # 所有 WorkerPool 共用同一个限流器实例
        global_limiter = get_global_rate_limiter()
        global_limiter.configure(rate_limit_delay)

    @asynccontextmanager
    async def throttle(self):
        """
        同时施加并发限制与**全局**限流来节流请求。

        - 信号量控制**本**池内的并发数（同一时刻跑几个）
        - 全局限流器控制**跨所有池**的请求频率（全局时间节奏）

        这样即便同时有多个 Argus 实例（例如深度研究里），总请求速率也不会
        超出限制。
        """
        async with self.semaphore:
            # 使用全局限流器（所有 WorkerPool 共享）
            global_limiter = get_global_rate_limiter()
            await global_limiter.wait_if_needed()
            yield
