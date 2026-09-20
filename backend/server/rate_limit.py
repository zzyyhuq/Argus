"""研究请求的按客户端限流。

这里保护的是*服务器*的搜索额度，而不是访客的。自带 Tavily key 的访客花的是自己
的额度，不受限；其余人共用服务器那份很小的配额——Tavily 免费版每月 1000 次搜索，
而一次研究要发起 4-8 次，所以几十个访客一下午就能把它耗光。

刻意做成进程内的内存实现：应用只跑一个 uvicorn worker（`Dockerfile` 里 WORKERS
默认为 1，`main.py` 也就是普通的 `uvicorn.run`），所以引入共享存储为时过早。若日
后这一点变了，就得换成 Redis 之类——各进程自己的计数器会各限各的，等于没限。
"""

import asyncio
import os
import time
from typing import Dict, List, Tuple


class RateLimiter:
    """按客户端身份计数的滑动窗口请求计数器。"""

    def __init__(self, limit: int, window_seconds: int = 3600):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> Tuple[bool, int]:
        """为 ``key`` 记一次请求。

        参数：
            key: 客户端身份（见 ``client_key``）。

        返回：
            ``(allowed, retry_after_seconds)``。请求被放行时
            ``retry_after_seconds`` 为 0。
        """
        if self.limit <= 0:  # 0 表示完全不限流
            return True, 0

        now = time.monotonic()
        cutoff = now - self.window_seconds

        async with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False, int(hits[0] + self.window_seconds - now) + 1

            hits.append(now)
            self._hits[key] = hits

            # 丢掉已经没有有效记录的 key，这样访客来来去去时这张表也不会无限
            # 增长。
            if len(self._hits) > 1024:
                self._hits = {k: v for k, v in self._hits.items() if v}

            return True, 0


def client_key(websocket) -> str:
    """识别调用方，供限流使用。

    注意：这里取的是*直接对端*的地址。若身处反向代理之后（nginx、Cloudflare
    等），所有访客共用代理的 IP，会被当成同一个客户端来限流——到那时就必须改读
    可信的 X-Forwarded-For。
    """
    client = getattr(websocket, "client", None)
    return getattr(client, "host", None) or "unknown"


def build_limiter(env_var: str = "RATE_LIMIT_PER_HOUR", default: int = 3) -> RateLimiter:
    """从环境变量构造一个限流器。

    参数：
        env_var: 存放每小时限额的环境变量名。
        default: 变量未设置或不是整数时使用。

    返回：
        按该限额构造的限流器；值为 <= 0 时返回不限流的限流器。
    """
    raw = os.getenv(env_var, str(default)).strip()
    try:
        limit = int(raw)
    except ValueError:
        limit = default
    return RateLimiter(limit)
