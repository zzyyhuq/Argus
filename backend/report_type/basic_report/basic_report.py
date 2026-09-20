import hashlib
import time
from fastapi import WebSocket
from typing import Any

from argus import Argus


class BasicReport:
    def __init__(
        self,
        query: str,
        query_domains: list,
        report_type: str,
        report_source: str,
        source_urls,
        document_urls,
        tone: Any,
        config_path: str,
        websocket: WebSocket,
        headers=None,
        mcp_configs=None,
        mcp_strategy=None,
        max_search_results=None,
        api_keys=None,
    ):
        self.query = query
        self.query_domains = query_domains
        self.report_type = report_type
        self.report_source = report_source
        self.source_urls = source_urls
        self.document_urls = document_urls
        self.tone = tone
        self.config_path = config_path
        self.websocket = websocket
        self.headers = headers or {}
        
        # 为本次报告生成唯一的研究 ID
        self.research_id = self._generate_research_id(query)

        # 初始化 researcher，MCP 参数是可选的
        argus_params = {
            "query": self.query,
            "query_domains": self.query_domains,
            "report_type": self.report_type,
            "report_source": self.report_source,
            "source_urls": self.source_urls,
            "document_urls": self.document_urls,
            "tone": self.tone,
            "config_path": self.config_path,
            "websocket": self.websocket,
            "headers": self.headers,
        }

        # 提供了 MCP 参数才加进去
        if mcp_configs is not None:
            argus_params["mcp_configs"] = mcp_configs
        if mcp_strategy is not None:
            argus_params["mcp_strategy"] = mcp_strategy

        # 访客提供的凭据，作用范围仅限本次请求
        if api_keys:
            argus_params["api_keys"] = api_keys

        self.argus = Argus(**argus_params)

        # 用户传了 max_search_results 就覆盖默认值
        if max_search_results is not None:
            self.argus.cfg.max_search_results_per_query = int(max_search_results)

    def _generate_research_id(self, query: str) -> str:
        """根据 query 与时间戳生成唯一的研究 ID。"""
        timestamp = str(int(time.time()))
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        return f"research_{timestamp}_{query_hash}"

    async def run(self):
        await self.argus.conduct_research()
        report = await self.argus.write_report()
        return report
