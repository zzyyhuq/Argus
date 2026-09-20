"""Argus 的 URL 安全工具。

当 URL 来自不可信输入时（例如 API 与 WebSocket 端点接收的 ``source_urls`` /
``document_urls`` 参数），这些辅助函数用来保护抓取与文档加载链路，抵御服务端
请求伪造（SSRF）和任意本地文件读取。

默认只放行主机解析到公网 IP 的 ``http`` / ``https`` URL，因此可拦下：

* 非 HTTP 协议，例如 ``file://``、``ftp://``、``gopher://``。
* 本地文件系统路径（没有 scheme/host），否则某些文档加载器会直接从磁盘读取
  它们（即任意本地文件读取）。
* 指向私有、环回、链路本地、保留或其他内网地址的请求（例如 ``127.0.0.1``、
  ``10.0.0.0/8``，以及云元数据端点 ``169.254.169.254``）。

如果有意抓取内网或自托管资源，可以设置环境变量 ``ALLOW_PRIVATE_URLS=true``
（或传入 ``allow_private=True``）跳过私有地址检查。

注意：在这里解析主机名、之后又让 HTTP 客户端重新解析一遍，会留下一个很小的
TOCTOU/DNS 重绑定窗口。要彻底堵住它，必须把校验过的 IP 固定到连接上；本防护
的定位是纵深防御，用于消除那些最省事的、无需认证的 SSRF 与本地文件读取原语。
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")

_TRUTHY = ("1", "true", "yes", "on")


class UnsafeURLError(ValueError):
    """当 URL 被 SSRF / 本地文件防护拒绝时抛出。"""


def _private_urls_allowed() -> bool:
    return os.getenv("ALLOW_PRIVATE_URLS", "").strip().lower() in _TRUTHY


def _is_disallowed_ip(ip) -> bool:
    """地址不安全（即属于内网）时返回 True。"""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str, *, allow_private: bool | None = None) -> str:
    """校验 ``url`` 可以安全抓取，并原样返回。

    参数：
        url: 待校验的 URL。
        allow_private: 为 ``True`` 时跳过私有/内网地址检查；为 ``None``
            （默认）时回退到 ``ALLOW_PRIVATE_URLS`` 环境变量。

    返回：
        通过全部检查时返回原始的 ``url``。

    异常：
        UnsafeURLError: URL 使用了不允许的协议、缺少主机名，或解析到非公网
            地址时抛出。
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeURLError("URL must be a non-empty string.")

    parsed = urlparse(url.strip())

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"URL scheme {scheme or '(none)'!r} is not allowed; "
            "only http and https URLs may be fetched."
        )

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL must include a valid host.")

    if allow_private is None:
        allow_private = _private_urls_allowed()
    if allow_private:
        return url

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host {host!r}: {exc}") from exc

    for info in addrinfo:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise UnsafeURLError(
                f"Host {host!r} resolved to an invalid address {ip_str!r}."
            ) from exc
        if _is_disallowed_ip(ip):
            raise UnsafeURLError(
                f"URL host {host!r} resolves to a non-public address ({ip_str}); "
                "set ALLOW_PRIVATE_URLS=true to allow internal targets."
            )

    return url


def is_safe_url(url: str, *, allow_private: bool | None = None) -> bool:
    """``url`` 通过 :func:`validate_url` 时返回 ``True``，否则返回 ``False``。"""
    try:
        validate_url(url, allow_private=allow_private)
        return True
    except UnsafeURLError:
        return False
