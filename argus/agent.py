"""Argus agent 模块。

本模块提供 Argus 主类，负责用 LLM 与网络搜索编排自主研究
与报告生成。
"""

import asyncio
import json
import os
from typing import Any, Optional

from .actions import (
    add_references,
    choose_agent,
    extract_headers,
    extract_sections,
    get_retrievers,
    get_search_results,
    table_of_contents,
)
from .config import Config
from .llm_provider import GenericLLMProvider
from .memory import Memory
from .prompts import get_prompt_family
from .skills.browser import BrowserManager
from .skills.context_manager import ContextManager
from .skills.curator import SourceCurator
from .skills.deep_research import DeepResearchSkill
from .skills.researcher import ResearchConductor
from .skills.writer import ReportGenerator
from .utils.enum import ReportSource, ReportType, Tone
from .utils.llm import create_chat_completion
from .vector_store import VectorStoreWrapper


class Argus:
    """Argus 主 agent 类。

    本类编排整个研究流程：网络搜索、内容抓取、上下文管理，
    以及基于 LLM 的报告生成。

    属性：
        query: 研究查询或问题。
        report_type: 要生成的报告类型。
        cfg: 配置对象。
        context: 累积的研究上下文。
        research_costs: 累积的 API 总花费。
        step_costs: 按步骤拆分花费的字典。
    """

    def __init__(
        self,
        query: str,
        report_type: str = ReportType.ResearchReport.value,
        report_format: str = "markdown",
        report_source: str = ReportSource.Web.value,
        tone: Tone = Tone.Objective,
        source_urls: list[str] | None = None,
        document_urls: list[str] | None = None,
        complement_source_urls: bool = False,
        query_domains: list[str] | None = None,
        documents=None,
        vector_store=None,
        vector_store_filter=None,
        config_path=None,
        websocket=None,
        agent=None,
        role=None,
        parent_query: str = "",
        subtopics: list | None = None,
        visited_urls: set | None = None,
        verbose: bool = True,
        context=None,
        headers: dict | None = None,
        max_subtopics: int = 5,
        log_handler=None,
        prompt_family: str | None = None,
        mcp_configs: list[dict] | None = None,
        mcp_max_iterations: int | None = None,
        mcp_strategy: str | None = None,
        api_keys: dict | None = None,
        **kwargs
    ):
        """
        初始化一个 Argus 实例。

        参数：
            query (str): 研究查询或问题。
            report_type (str): 要生成的报告类型。
            report_format (str): 报告格式（markdown、apa 等）。
            report_source (str): 报告的信息来源（web、local 等）。
            tone (Tone): 报告的语气。
            source_urls (list[str], optional): 用作来源的指定 URL 列表。
            document_urls (list[str], optional): 用作来源的文档 URL 列表。
            complement_source_urls (bool): 是否用网络搜索补充来源 URL。
            query_domains (list[str], optional): 限定搜索范围的域名列表。
            documents: 供 LangChain 集成的文档对象。
            vector_store: 用于文档检索的向量库。
            vector_store_filter: 向量库查询的过滤条件。
            config_path: 配置文件路径。
            websocket: 用于流式输出的 WebSocket。
            agent: 预先指定的 agent 类型。
            role: 预先指定的 agent 角色。
            parent_query: 子主题报告的父查询。
            subtopics: 要研究的子主题列表。
            visited_urls: 已访问 URL 的集合。
            verbose (bool): 是否输出详细日志。
            context: 预加载的研究上下文。
            headers (dict, optional): 请求与配置使用的附加 header。
            max_subtopics (int): 最多生成多少个子主题。
            log_handler: 日志事件处理器。
            prompt_family: 使用的 prompt 家族。
            mcp_configs (list[dict], optional): MCP 服务器配置列表。
                每个字典可包含：
                - name (str): MCP 服务器名称
                - command (str): 启动服务器的命令
                - args (list[str]): 服务器命令的参数
                - tool_name (str): 在 MCP 服务器上使用的具体工具
                - env (dict): 服务器的环境变量
                - connection_url (str): WebSocket 或 HTTP 连接地址
                - connection_type (str): 连接类型（stdio、websocket、http）
                - connection_token (str): 远程连接用的认证 token

                示例：
                ```python
                mcp_configs=[{
                    "command": "python",
                    "args": ["my_mcp_server.py"],
                    "name": "search"
                }]
                ```
            mcp_strategy (str, optional): MCP 执行策略。可选值：
                - "fast"（默认）：只对原始查询跑一次 MCP，性能最好
                - "deep": 对所有子查询都跑 MCP，覆盖最全
                - "disabled": 完全跳过 MCP，只用网络 retriever
            api_keys (dict, optional): 由访问者提供、仅本次请求有效的凭证。
                可识别的键：``llm``（以 ``api_key`` 注入
                ``cfg.llm_kwargs``）与 ``tavily``（注入 ``headers``，
                让 retriever 在环境变量之前取到它）。
        """
        self.kwargs = kwargs
        self.query = query
        self.report_type = report_type
        self.cfg = Config(config_path)
        self.cfg.set_verbose(verbose)
        self.report_source = report_source if report_source else getattr(self.cfg, 'report_source', None)
        self.report_format = report_format
        self.max_subtopics = max_subtopics
        self.tone = tone if isinstance(tone, Tone) else Tone.Objective
        self.source_urls = source_urls
        self.document_urls = document_urls
        self.complement_source_urls = complement_source_urls
        self.query_domains = query_domains or []
        self.research_sources = []  # 抓取到的来源列表，含标题与正文
        self.documents = documents
        self.vector_store = VectorStoreWrapper(vector_store) if vector_store else None
        self.vector_store_filter = vector_store_filter
        self.websocket = websocket
        self.agent = agent
        self.role = role
        self.parent_query = parent_query
        self.subtopics = subtopics or []
        self.visited_urls = visited_urls or set()
        self.verbose = verbose
        self.context = context or []
        # 这里必须拷贝：下面会合并进访问者提供的 key，若直接共享调用方的
        # dict，就可能把一个请求的 key 带到另一个请求里。
        self.headers = dict(headers) if headers else {}

        # 访问者提供的凭证，作用域限于本次请求。Config 是按实例构造的（见上一行），
        # 所以写入 cfg.llm_kwargs 只影响当前这个 researcher——与 MCP 采用的
        # 非全局做法一致。刻意不用 os.environ，否则会在并发会话之间泄漏（#1676）。
        if api_keys:
            if api_keys.get("llm"):
                self.cfg.llm_kwargs["api_key"] = api_keys["llm"]
            if api_keys.get("tavily"):
                self.headers["tavily_api_key"] = api_keys["tavily"]

        self.research_costs = 0.0
        self.step_costs: dict[str, float] = {}
        self._current_step: str = "general"
        self.log_handler = log_handler
        self.prompt_family = get_prompt_family(prompt_family or self.cfg.prompt_family, self.cfg)

        # 若提供了 MCP 配置则处理它们
        self.mcp_configs = mcp_configs
        if mcp_configs:
            self._process_mcp_configs(mcp_configs)

        self.retrievers = get_retrievers(self.headers, self.cfg)
        self.memory = Memory(
            self.cfg.embedding_provider, self.cfg.embedding_model, **self.cfg.embedding_kwargs
        )

        # 默认编码设为 utf-8
        self.encoding = kwargs.get('encoding', 'utf-8')
        self.kwargs.pop('encoding', None)  # 从 kwargs 中移除 encoding，避免传给 LLM 调用

        # 初始化各个组件
        self.research_conductor: ResearchConductor = ResearchConductor(self)
        self.report_generator: ReportGenerator = ReportGenerator(self)
        self.context_manager: ContextManager = ContextManager(self)
        self.scraper_manager: BrowserManager = BrowserManager(self)
        self.source_curator: SourceCurator = SourceCurator(self)
        self.deep_researcher: Optional[DeepResearchSkill] = None
        if report_type == ReportType.DeepResearch.value:
            self.deep_researcher = DeepResearchSkill(self)

        self.available_images: list = []  # 为报告挑选出的来源图片
        self._research_id: str = ""  # 本次研究会话的唯一 ID

        # 解析 MCP 策略配置，同时保持向后兼容
        self.mcp_strategy = self._resolve_mcp_strategy(mcp_strategy, mcp_max_iterations)

    def _generate_research_id(self) -> str:
        """为本次会话生成唯一的研究 ID。

        返回：
            本次研究会话的唯一字符串标识。
        """
        if not self._research_id:
            import hashlib
            import time
            # 用 query + 时间戳生成唯一 ID
            unique_str = f"{self.query}_{time.time()}"
            self._research_id = f"research_{hashlib.md5(unique_str.encode()).hexdigest()[:12]}"
        return self._research_id

    def _resolve_mcp_strategy(self, mcp_strategy: str | None, mcp_max_iterations: int | None) -> str:
        """
        从多个来源解析 MCP 策略，并保持向后兼容。

        优先级：
        1. 参数 mcp_strategy（新方式）
        2. 参数 mcp_max_iterations（向后兼容）
        3. 配置项 MCP_STRATEGY
        4. 默认 "fast"

        参数：
            mcp_strategy: 新的策略参数
            mcp_max_iterations: 为向后兼容保留的旧参数

        返回：
            str: 解析出的策略（"fast"、"deep" 或 "disabled"）
        """
        # 优先级 1：若提供了 mcp_strategy 参数则优先使用
        if mcp_strategy is not None:
            # 支持新的策略名
            if mcp_strategy in ["fast", "deep", "disabled"]:
                return mcp_strategy
            # 为向后兼容，同时支持旧的策略名
            elif mcp_strategy == "optimized":
                import logging
                logging.getLogger(__name__).warning("mcp_strategy 'optimized' is deprecated, use 'fast' instead")
                return "fast"
            elif mcp_strategy == "comprehensive":
                import logging
                logging.getLogger(__name__).warning("mcp_strategy 'comprehensive' is deprecated, use 'deep' instead")
                return "deep"
            else:
                import logging
                logging.getLogger(__name__).warning(f"Invalid mcp_strategy '{mcp_strategy}', defaulting to 'fast'")
                return "fast"

        # 优先级 2：为向后兼容转换 mcp_max_iterations
        if mcp_max_iterations is not None:
            import logging
            logging.getLogger(__name__).warning("mcp_max_iterations is deprecated, use mcp_strategy instead")

            if mcp_max_iterations == 0:
                return "disabled"
            elif mcp_max_iterations == 1:
                return "fast"
            elif mcp_max_iterations == -1:
                return "deep"
            else:
                # 其余数值一律按 fast 模式处理
                return "fast"

        # 优先级 3：使用配置项
        if hasattr(self.cfg, 'mcp_strategy'):
            config_strategy = self.cfg.mcp_strategy
            # 支持新的策略名
            if config_strategy in ["fast", "deep", "disabled"]:
                return config_strategy
            # 为向后兼容，同时支持旧的策略名
            elif config_strategy == "optimized":
                return "fast"
            elif config_strategy == "comprehensive":
                return "deep"

        # 优先级 4：默认 fast
        return "fast"

    def _process_mcp_configs(self, mcp_configs: list[dict]) -> None:
        """
        从配置字典列表中处理 MCP 配置。

        通过直接修改 self.cfg.retrievers，把 MCP retriever 加入当前启用的
        retriever 列表。刻意不碰 os.environ，这样并发或后续请求都不会被本
        会话的 MCP 设置影响（修复 issue #1676 —— 进程级环境变量污染）。

        参数：
            mcp_configs (list[dict]): MCP 服务器配置字典列表。
        """
        # 通过 cfg（而不是 os.environ）把 MCP 加入 retrievers，避免污染环境变量
        if hasattr(self.cfg, 'retrievers') and self.cfg.retrievers:
            current_retrievers = (
                list(self.cfg.retrievers)
                if isinstance(self.cfg.retrievers, list)
                else [r.strip() for r in str(self.cfg.retrievers).split(",") if r.strip()]
            )
            if "mcp" not in current_retrievers:
                current_retrievers.append("mcp")
                self.cfg.retrievers = current_retrievers
        else:
            self.cfg.retrievers = ["mcp"]

        # 保存 mcp_configs，供 MCP retriever 使用
        self.mcp_configs = mcp_configs

    async def _log_event(self, event_type: str, **kwargs):
        """辅助方法，用于处理日志事件"""
        if self.log_handler:
            try:
                if event_type == "tool":
                    await self.log_handler.on_tool_start(kwargs.get('tool_name', ''), **kwargs)
                elif event_type == "action":
                    await self.log_handler.on_agent_action(kwargs.get('action', ''), **kwargs)
                elif event_type == "research":
                    await self.log_handler.on_research_step(kwargs.get('step', ''), kwargs.get('details', {}))

                # 额外直接写一条日志作为兜底
                import logging
                research_logger = logging.getLogger('research')
                research_logger.info(f"{event_type}: {json.dumps(kwargs, default=str)}")

            except Exception as e:
                import logging
                logging.getLogger('research').error(f"Error in _log_event: {e}", exc_info=True)

    async def conduct_research(self, on_progress=None):
        """执行研究流程。

        本方法编排主要的研究工作流：agent 选择、网络搜索与上下文收集。

        参数：
            on_progress: 可选回调，用于深度研究过程中的进度更新。

        返回：
            累积得到的研究上下文。
        """
        await self._log_event("research", step="start", details={
            "query": self.query,
            "report_type": self.report_type,
            "agent": self.agent,
            "role": self.role
        })

        # 深度研究单独处理
        if self.report_type == ReportType.DeepResearch.value and self.deep_researcher:
            self._current_step = "deep_research"
            return await self._handle_deep_research(on_progress)

        if not (self.agent and self.role):
            self._current_step = "agent_selection"
            await self._log_event("action", action="choose_agent")
            # 过滤掉 encoding 参数，LLM API 不支持它
            # filtered_kwargs = {k: v for k, v in self.kwargs.items() if k != 'encoding'}
            self.agent, self.role = await choose_agent(
                query=self.query,
                cfg=self.cfg,
                parent_query=self.parent_query,
                cost_callback=self.add_costs,
                headers=self.headers,
                prompt_family=self.prompt_family,
                **self.kwargs,
                # **filtered_kwargs
            )
            await self._log_event("action", action="agent_selected", details={
                "agent": self.agent,
                "role": self.role
            })

        await self._log_event("research", step="conducting_research", details={
            "agent": self.agent,
            "role": self.role
        })
        self._current_step = "research"
        self.context = await self.research_conductor.conduct_research()

        await self._log_event("research", step="research_completed", details={
            "context_length": len(self.context)
        })

        return self.context

    async def _handle_deep_research(self, on_progress=None):
        """处理深度研究的执行与日志记录。

        参数：
            on_progress: 可选回调，用于进度更新。

        返回：
            深度研究累积得到的研究上下文。
        """
        # 记录深度研究配置
        await self._log_event("research", step="deep_research_initialize", details={
            "type": "deep_research",
            "breadth": self.deep_researcher.breadth,
            "depth": self.deep_researcher.depth,
            "concurrency": self.deep_researcher.concurrency_limit
        })

        # 记录深度研究开始
        await self._log_event("research", step="deep_research_start", details={
            "query": self.query,
            "breadth": self.deep_researcher.breadth,
            "depth": self.deep_researcher.depth,
            "concurrency": self.deep_researcher.concurrency_limit
        })

        # 运行深度研究并获取上下文
        self.context = await self.deep_researcher.run(on_progress=on_progress)

        # 获取研究总花费
        total_costs = self.get_costs()

        # 记录深度研究完成，并带上花费
        await self._log_event("research", step="deep_research_complete", details={
            "context_length": len(self.context),
            "visited_urls": len(self.visited_urls),
            "total_costs": total_costs
        })

        # 记录最终花费更新
        await self._log_event("research", step="cost_update", details={
            "cost": total_costs,
            "total_cost": total_costs,
            "research_type": "deep_research"
        })

        # 返回研究上下文
        return self.context

    async def write_report(
        self,
        existing_headers: list = [],
        relevant_written_contents: list = [],
        ext_context=None,
        custom_prompt="",
    ) -> str:
        """撰写研究报告。

        参数：
            existing_headers: 已有标题的列表，用于避免重复。
            relevant_written_contents: 此前已撰写的内容列表，作为上下文。
            ext_context: 使用外部上下文替代内部上下文。
            custom_prompt: 引导报告生成的自定义 prompt。

        返回：
            生成好的报告字符串。
        """
        has_available_images = bool(self.available_images)
        self._current_step = "report_writing"
        await self._log_event("research", step="writing_report", details={
            "existing_headers": existing_headers,
            "context_source": "external" if ext_context else "internal",
            "available_images_count": len(self.available_images),
        })

        # 生成报告，并嵌入可用的图片
        report = await self.report_generator.write_report(
            existing_headers=existing_headers,
            relevant_written_contents=relevant_written_contents,
            ext_context=ext_context or self.context,
            custom_prompt=custom_prompt,
            available_images=self.available_images,  # 传入预生成的图片
        )

        await self._log_event("research", step="report_completed", details={
            "report_length": len(report),
            "images_embedded": len(self.available_images) if has_available_images else 0,
        })
        return report

    async def write_report_conclusion(self, report_body: str) -> str:
        """撰写报告的结论部分。

        参数：
            report_body: 报告正文，用于撰写结论。

        返回：
            生成好的结论文本。
        """
        await self._log_event("research", step="writing_conclusion")
        conclusion = await self.report_generator.write_report_conclusion(report_body)
        await self._log_event("research", step="conclusion_completed")
        return conclusion

    async def write_introduction(self) -> str:
        """撰写报告的引言部分。

        返回：
            生成好的引言文本。
        """
        await self._log_event("research", step="writing_introduction")
        intro = await self.report_generator.write_introduction()
        await self._log_event("research", step="introduction_completed")
        return intro

    async def quick_search(
        self,
        query: str,
        query_domains: list[str] = None,
        aggregated_summary: bool = False,
        all_retrievers: bool = False,
    ) -> list[Any] | str:
        """执行快速搜索，不跑完整的研究流程。

        参数：
            query: 搜索查询。
            query_domains: 可选的域名列表，用于限定搜索范围。
            aggregated_summary: 是否返回搜索结果的聚合摘要。
            all_retrievers: 若为 True，则并发查询所有已配置的 retriever，
                并合并结果（按 URL 去重）。默认 False，即只用主 retriever，
                以保持向后兼容。

        返回：
            搜索结果列表，或综合后的摘要字符串。
        """
        if all_retrievers and len(self.retrievers) > 1:
            search_results = await self._search_all_retrievers(query, query_domains)
        else:
            search_results = await get_search_results(
                query, self.retrievers[0], query_domains=query_domains, researcher=self
            )

        if not aggregated_summary:
            return search_results

        # 为生成摘要而整理结果。搜索 retriever 返回的记录以 "href"（URL）与
        # "body"（正文）为键；这里回退到备用键名，好让传入已归一化记录的
        # 调用方也能正常工作。
        context = ""
        for i, result in enumerate(search_results, 1):
            title = result.get("title", "")
            body = result.get("body") or result.get("content", "")
            url = result.get("href") or result.get("url", "")
            context += f"[{i}] {title}: {body} ({url})\n\n"

        prompt = self.prompt_family.generate_quick_summary_prompt(query, context)

        summary = await create_chat_completion(
            model=self.cfg.smart_llm_model,
            messages=[{"role": "user", "content": prompt}],
            llm_provider=self.cfg.smart_llm_provider,
            max_tokens=self.cfg.smart_token_limit,
            llm_kwargs=self.cfg.llm_kwargs,
            cost_callback=self.add_costs
        )

        return summary

    async def _search_all_retrievers(
        self, query: str, query_domains: list[str] = None
    ) -> list[dict[str, Any]]:
        """并发查询所有已配置的 retriever，并合并结果。

        结果按 URL 去重（同时检查 ``url`` 与 ``href`` 两个键，不同 retriever
        用的键不一样）。抛异常的 retriever 会被跳过，因此单个 provider 失败
        不会中断整次搜索。

        参数：
            query: 搜索查询。
            query_domains: 可选的域名列表，用于限定搜索范围。

        返回：
            合并并去重后的搜索结果列表。
        """
        tasks = [
            get_search_results(query, retriever, query_domains=query_domains, researcher=self)
            for retriever in self.retrievers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for result in results:
            if isinstance(result, Exception) or not result:
                continue
            for item in result:
                url = item.get("url") or item.get("href") or ""
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                merged.append(item)
        return merged

    async def get_subtopics(self):
        """为研究查询生成子主题。

        返回：
            生成的子主题列表。
        """
        return await self.report_generator.get_subtopics()

    async def get_draft_section_titles(self, current_subtopic: str) -> list[str]:
        """为某个子主题生成草稿章节标题。

        参数：
            current_subtopic: 要为其生成章节的子主题。

        返回：
            章节标题字符串列表。
        """
        return await self.report_generator.get_draft_section_titles(current_subtopic)

    async def get_similar_written_contents_by_draft_section_titles(
        self,
        current_subtopic: str,
        draft_section_titles: list[str],
        written_contents: list[dict],
        max_results: int = 10
    ) -> list[str]:
        """根据章节标题找出相似的、此前已撰写的内容。

        参数：
            current_subtopic: 当前正在撰写的子主题。
            draft_section_titles: 草稿章节标题列表。
            written_contents: 用于检索的此前已撰写的内容。
            max_results: 最多返回的结果数。

        返回：
            相似内容字符串列表。
        """
        return await self.context_manager.get_similar_written_contents_by_draft_section_titles(
            current_subtopic,
            draft_section_titles,
            written_contents,
            max_results
        )

    # 工具方法
    def get_research_sources(self) -> list[dict[str, Any]]:
        """获取研究过程中收集到的全部来源。

        返回：
            来源字典列表，包含标题、正文与图片。
        """
        return self.research_sources

    def add_research_sources(self, sources: list[dict[str, Any]]) -> None:
        """把来源加入研究来源集合。

        参数：
            sources: 要添加的来源字典列表。
        """
        self.research_sources.extend(sources)

    def add_references(self, report_markdown: str, visited_urls: set) -> str:
        """为 markdown 报告追加参考文献小节。

        参数：
            report_markdown: markdown 报告文本。
            visited_urls: 要作为参考文献收录的 URL 集合。

        返回：
            追加了参考文献的报告。
        """
        return add_references(report_markdown, visited_urls)

    def extract_headers(self, markdown_text: str) -> list[dict]:
        """从 markdown 文本中提取标题。

        参数：
            markdown_text: 要解析的 markdown 文本。

        返回：
            标题字典列表。
        """
        return extract_headers(markdown_text)

    def extract_sections(self, markdown_text: str) -> list[dict]:
        """从 markdown 文本中提取章节。

        参数：
            markdown_text: 要解析的 markdown 文本。

        返回：
            章节字典列表。
        """
        return extract_sections(markdown_text)

    def table_of_contents(self, markdown_text: str) -> str:
        """为 markdown 文本生成目录。

        参数：
            markdown_text: 要生成目录的 markdown 文本。

        返回：
            目录，markdown 字符串。
        """
        return table_of_contents(markdown_text)

    def get_source_urls(self) -> list:
        """获取所有已访问的来源 URL。

        返回：
            已访问 URL 字符串列表。
        """
        return list(self.visited_urls)

    def get_research_context(self) -> list:
        """获取累积的研究上下文。

        返回：
            研究过程中收集的上下文条目列表。
        """
        return self.context

    def get_costs(self) -> float:
        """获取累积的 API 总花费。

        返回：
            总花费，单位为 USD。
        """
        return self.research_costs

    def get_step_costs(self) -> dict[str, float]:
        """获取按研究步骤拆分的 API 花费。

        返回：
            步骤名到花费（USD）的字典。
        """
        return dict(self.step_costs)

    def set_verbose(self, verbose: bool) -> None:
        """设置详细输出模式。

        参数：
            verbose: 是否启用详细输出。
        """
        self.verbose = verbose

    def add_costs(self, cost: float) -> None:
        """累加 API 花费。

        花费会记到通过 ``_current_step`` 设置的当前步骤上。

        参数：
            cost: 要累加的金额，单位为 USD。

        异常：
            ValueError: cost 不是数字时抛出。
        """
        if not isinstance(cost, (float, int)):
            raise ValueError("Cost must be an integer or float")
        self.research_costs += cost
        step = self._current_step
        self.step_costs[step] = self.step_costs.get(step, 0.0) + cost
        if self.log_handler:
            self._log_event("research", step="cost_update", details={
                "cost": cost,
                "total_cost": self.research_costs,
                "step_name": step,
            })
