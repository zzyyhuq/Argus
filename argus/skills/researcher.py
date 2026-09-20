"""Argus 的研究编排技能。

本模块提供 ResearchConductor 类，管理与编排整个研究流程，
包括查询规划、网络搜索与上下文收集。
"""

import asyncio
import inspect
import logging
import os
import random

from ..actions.agent_creator import choose_agent
from ..actions.query_processing import get_search_results, plan_research_outline
from ..actions.utils import stream_output
from ..document import DocumentLoader, LangChainDocumentLoader, OnlineDocumentLoader
from ..utils.enum import ReportSource, ReportType
from ..utils.logging_config import get_json_handler


class ResearchConductor:
    """管理与编排研究流程。

    本类承接主要的研究工作流：规划研究查询、执行网络搜索、
    管理 MCP retriever，以及从各类来源收集上下文。

    属性：
        researcher: 持有该编排器的父级 Argus 实例。
        logger: 研究事件所用的 logger。
        json_handler: JSON 日志的 handler。
    """

    def __init__(self, researcher):
        """初始化 ResearchConductor。

        参数：
            researcher: 持有该编排器的 Argus 实例。
        """
        self.researcher = researcher
        self.logger = logging.getLogger('research')
        self.json_handler = get_json_handler()
        # 缓存 MCP 结果，避免重复调用
        self._mcp_results_cache = None
        # 研究流程并发执行时，用它保证缓存只被填充一次
        self._mcp_cache_lock = asyncio.Lock()
        # 统计 MCP 查询次数，供 balanced 模式使用
        self._mcp_query_count = 0

    async def plan_research(self, query, query_domains=None):
        """从查询里拆出子查询
        参数：
            query: 原始查询
        返回：
            查询列表
        """
        await stream_output(
            "logs",
            "planning_research",
            f"🌐 Browsing the web to learn more about the task: {query}...",
            self.researcher.websocket,
        )

        search_results = await get_search_results(
            query,
            self.researcher.retrievers[0],
            query_domains,
            researcher=self.researcher,
            max_results=self.researcher.cfg.max_search_results_per_query,
        )
        self.logger.info(f"Initial search results obtained: {len(search_results)} results")

        await stream_output(
            "logs",
            "planning_research",
            f"🤔 Planning the research strategy and subtasks...",
            self.researcher.websocket,
        )

        retriever_names = [r.__name__ for r in self.researcher.retrievers]
        # 不再重复打日志 —— 该信息统一在 conduct_research 中记录一次

        outline = await plan_research_outline(
            query=query,
            search_results=search_results,
            agent_role_prompt=self.researcher.role,
            cfg=self.researcher.cfg,
            parent_query=self.researcher.parent_query,
            report_type=self.researcher.report_type,
            cost_callback=self.researcher.add_costs,
            retriever_names=retriever_names,  # 传入 retriever 名称，用于 MCP 优化
            **self.researcher.kwargs
        )
        self.logger.info(f"Research outline planned: {outline}")
        return outline

    async def conduct_research(self):
        """驱动 Argus 执行研究"""
        if self.json_handler:
            self.json_handler.update_content("query", self.researcher.query)
        
        self.logger.info(f"Starting research for query: {self.researcher.query}")
        
        # 在研究开始时记录一次当前生效的 retriever
        retriever_names = [r.__name__ for r in self.researcher.retrievers]
        self.logger.info(f"Active retrievers: {retriever_names}")

        # 注意：这里刻意不清空 visited_urls。它可能与父级研究器共享
        # （例如详细报告会把已累积的 URL 传给每个子主题研究器），
        # 以免已经抓取过的 URL 被重复抓取。
        research_data = []

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "starting_research",
                f"🔍 Starting the research task for '{self.researcher.query}'...",
                self.researcher.websocket,
            )
            await stream_output(
                "logs",
                "agent_generated",
                self.researcher.agent,
                self.researcher.websocket
            )

        # 尚未定义时，才选择 agent 与角色
        if not (self.researcher.agent and self.researcher.role):
            self.researcher.agent, self.researcher.role = await choose_agent(
                query=self.researcher.query,
                cfg=self.researcher.cfg,
                parent_query=self.researcher.parent_query,
                cost_callback=self.researcher.add_costs,
                headers=self.researcher.headers,
                prompt_family=self.researcher.prompt_family
            )
                
        # 检查是否配置了 MCP retriever
        has_mcp_retriever = any("mcpretriever" in r.__name__.lower() for r in self.researcher.retrievers)
        if has_mcp_retriever:
            self.logger.info("MCP retrievers configured and will be used with standard research flow")

        # 按来源类型分别开展研究
        if self.researcher.source_urls:
            self.logger.info("Using provided source URLs")
            research_data = await self._get_context_by_urls(self.researcher.source_urls)
            # `research_data and len(research_data) == 0` 永远不可能为真 ——
            # 真值不可能为空 —— 所以这条提示以前从未触发过。
            if not research_data and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "answering_from_memory",
                    f"🧐 I was unable to find relevant context in the provided sources...",
                    self.researcher.websocket,
                )
            if self.researcher.complement_source_urls:
                self.logger.info("Complementing with web search")
                additional_research = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
                research_data += ' '.join(additional_research)
        elif self.researcher.report_source == ReportSource.Web.value:
            self.logger.info("Using web search with all configured retrievers")
            research_data = await self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains)
        elif self.researcher.report_source == ReportSource.Local.value:
            self.logger.info("Using local search")
            document_data = await DocumentLoader(self.researcher.cfg.doc_path).load()
            self.logger.info(f"Loaded {len(document_data)} documents")
            if self.researcher.vector_store:
                self.researcher.vector_store.load(document_data)

            research_data = await self._get_context_by_web_search(self.researcher.query, document_data, self.researcher.query_domains)
        # 混合检索：同时使用本地文档与网络来源
        elif self.researcher.report_source == ReportSource.Hybrid.value:
            if self.researcher.document_urls:
                document_data = await OnlineDocumentLoader(self.researcher.document_urls).load()
            else:
                document_data = await DocumentLoader(self.researcher.cfg.doc_path).load()
            if self.researcher.vector_store:
                self.researcher.vector_store.load(document_data)
            # 本地文档与网络这两遍检索彼此独立，因此并发执行；
            # visited_urls 仍会在两者之间完成去重。
            docs_context, web_context = await asyncio.gather(
                self._get_context_by_web_search(self.researcher.query, document_data, self.researcher.query_domains),
                self._get_context_by_web_search(self.researcher.query, [], self.researcher.query_domains),
            )
            research_data = self.researcher.prompt_family.join_local_web_documents(docs_context, web_context)
        elif self.researcher.report_source == ReportSource.LangChainDocuments.value:
            langchain_documents_data = await LangChainDocumentLoader(
                self.researcher.documents
            ).load()
            if self.researcher.vector_store:
                self.researcher.vector_store.load(langchain_documents_data)
            research_data = await self._get_context_by_web_search(
                self.researcher.query, langchain_documents_data, self.researcher.query_domains
            )
        elif self.researcher.report_source == ReportSource.LangChainVectorStore.value:
            research_data = await self._get_context_by_vectorstore(self.researcher.query, self.researcher.vector_store_filter)

        # 对来源进行排序与筛选
        self.researcher.context = research_data
        if self.researcher.cfg.curate_sources:
            self.logger.info("Curating sources")
            curated = await self.researcher.source_curator.curate_sources(research_data)
            # curate_sources() 返回带 Title/Content/Source 键的 List[dict]。
            # 这里统一转成 str，避免下游那些认定 researcher.context 是字符串的代码
            # （如 "\n".join、.split()、len()）报错。
            if isinstance(curated, list):
                self.researcher.context = "\n\n".join(
                    "Title: {title}\nContent: {content}\nSource: {source}".format(
                        title=s.get("Title", ""),
                        content=s.get("Content", ""),
                        source=s.get("Source", ""),
                    ) if isinstance(s, dict) else str(s)
                    for s in curated
                )
            else:
                self.researcher.context = curated

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "research_step_finalized",
                f"Finalized research step.\n💸 Total Research Costs: ${self.researcher.get_costs()}",
                self.researcher.websocket,
            )
            if self.json_handler:
                self.json_handler.update_content("costs", self.researcher.get_costs())
                self.json_handler.update_content("context", self.researcher.context)

        self.logger.info(f"Research completed. Context size: {len(str(self.researcher.context))}")
        return self.researcher.context

    async def _get_context_by_urls(self, urls):
        """抓取并压缩给定 url 的上下文"""
        self.logger.info(f"Getting context from URLs: {urls}")
        
        new_search_urls = await self._get_new_urls(urls)
        self.logger.info(f"New URLs to process: {new_search_urls}")

        scraped_content = await self.researcher.scraper_manager.browse_urls(new_search_urls)
        self.logger.info(f"Scraped content from {len(scraped_content)} URLs")

        if self.researcher.vector_store:
            self.researcher.vector_store.load(scraped_content)

        context = await self.researcher.context_manager.get_similar_content_by_query(
            self.researcher.query, scraped_content
        )
        return context

    # 其余方法可照此方式补充日志……

    async def _get_context_by_vectorstore(self, query, filter: dict | None = None):
        """
        通过检索 vectorstore 生成研究任务所需的上下文
        返回：
            context: 上下文列表
        """
        self.logger.info(f"Starting vectorstore search for query: {query}")
        context = []
        # 生成子查询，并把原始查询一并纳入
        sub_queries = await self.plan_research(query)
        # 若不是子研究器的一部分，则把原始查询也加进来以获得更好的结果
        if self.researcher.report_type != "subtopic_report":
            sub_queries.append(query)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "subqueries",
                f"🗂️  I will conduct my research based on the following queries: {sub_queries}...",
                self.researcher.websocket,
                True,
                sub_queries,
            )

        # 用 asyncio.gather 并发处理这些子查询
        context = await asyncio.gather(
            *[
                self._process_sub_query_with_vectorstore(sub_query, filter)
                for sub_query in sub_queries
            ]
        )
        return context

    async def _get_context_by_web_search(self, query, scraped_data: list | None = None, query_domains: list | None = None):
        """
        通过检索查询并抓取结果，生成研究任务所需的上下文
        返回：
            context: 上下文列表
        """
        self.logger.info(f"Starting web search for query: {query}")
        
        if scraped_data is None:
            scraped_data = []
        if query_domains is None:
            query_domains = []

        # **可配置的 MCP 优化：控制 MCP 策略**
        mcp_retrievers = [r for r in self.researcher.retrievers if "mcpretriever" in r.__name__.lower()]

        # 读取 MCP 策略配置
        mcp_strategy = self._get_mcp_strategy()

        # 加锁，使并发的多轮研究（如 hybrid 模式）只填充一次 MCP 缓存，
        # 而不是抢着把同一份 MCP 研究跑两遍。
        async with self._mcp_cache_lock:
            if mcp_retrievers and self._mcp_results_cache is None:
                if mcp_strategy == "disabled":
                    # MCP 已禁用 —— 完全跳过 MCP 研究
                    self.logger.info("MCP disabled by strategy, skipping MCP research")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_disabled",
                            f"⚡ MCP research disabled by configuration",
                            self.researcher.websocket,
                        )
                elif mcp_strategy == "fast":
                    # fast：只用原始查询跑一次 MCP
                    self.logger.info("MCP fast strategy: Running once with original query")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_optimization",
                            f"🚀 MCP Fast: Running once for main query (performance mode)",
                            self.researcher.websocket,
                        )

                    # 用原始查询执行一次 MCP 研究
                    mcp_context = await self._execute_mcp_research_for_queries([query], mcp_retrievers)
                    self._mcp_results_cache = mcp_context
                    self.logger.info(f"MCP results cached: {len(mcp_context)} total context entries")
                elif mcp_strategy == "deep":
                    # deep：所有查询都跑 MCP（原有行为）—— 交给每个查询各自执行
                    self.logger.info("MCP deep strategy: Will run for all queries")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_comprehensive",
                            f"🔍 MCP Deep: Will run for each sub-query (thorough mode)",
                            self.researcher.websocket,
                        )
                    # 不缓存 —— 让每个子查询各自跑 MCP
                else:
                    # 策略无法识别 —— 默认按 fast 处理
                    self.logger.warning(f"Unknown MCP strategy '{mcp_strategy}', defaulting to fast")
                    mcp_context = await self._execute_mcp_research_for_queries([query], mcp_retrievers)
                    self._mcp_results_cache = mcp_context
                    self.logger.info(f"MCP results cached: {len(mcp_context)} total context entries")

        # 生成子查询，并把原始查询一并纳入
        sub_queries = await self.plan_research(query, query_domains)
        self.logger.info(f"Generated sub-queries: {sub_queries}")

        # 若不是子研究器的一部分，则把原始查询也加进来以获得更好的结果
        if self.researcher.report_type != "subtopic_report":
            sub_queries.append(query)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "subqueries",
                f"🗂️ I will conduct my research based on the following queries: {sub_queries}...",
                self.researcher.websocket,
                True,
                sub_queries,
            )

        # 用 asyncio.gather 并发处理这些子查询
        try:
            context = await asyncio.gather(
                *[
                    self._process_sub_query(sub_query, scraped_data, query_domains)
                    for sub_query in sub_queries
                ]
            )
            self.logger.info(f"Gathered context from {len(context)} sub-queries")
            # 过滤掉空结果，再把上下文拼接起来
            context = [c for c in context if c]
            if context:
                combined_context = " ".join(context)
                self.logger.info(f"Combined context size: {len(combined_context)}")
                return combined_context
            return []
        except Exception as e:
            self.logger.error(f"Error during web search: {e}", exc_info=True)
            return []

    def _get_mcp_strategy(self) -> str:
        """
        读取 MCP 策略配置。

        优先级：
        1. 实例级设置（self.researcher.mcp_strategy）
        2. 配置文件设置（self.researcher.cfg.mcp_strategy）
        3. 默认值（"fast"）

        返回：
            str: MCP 策略
                "disabled" = 完全跳过 MCP
                "fast" = 只用原始查询跑一次 MCP（默认）
                "deep" = 所有子查询都跑 MCP
        """
        # 先看实例级设置
        if hasattr(self.researcher, 'mcp_strategy') and self.researcher.mcp_strategy is not None:
            return self.researcher.mcp_strategy

        # 再看配置项
        if hasattr(self.researcher.cfg, 'mcp_strategy'):
            return self.researcher.cfg.mcp_strategy

        # 默认走 fast 模式
        return "fast"

    async def _execute_mcp_research_for_queries(self, queries: list, mcp_retrievers: list) -> list:
        """
        对一组查询执行 MCP 研究。

        参数：
            queries: 待研究的查询列表
            mcp_retrievers: MCP retriever 类的列表

        返回：
            list: 汇总所有查询得到的 MCP 上下文条目
        """
        all_mcp_context = []
        
        for i, query in enumerate(queries, 1):
            self.logger.info(f"Executing MCP research for query {i}/{len(queries)}: {query}")
            
            for retriever in mcp_retrievers:
                try:
                    mcp_results = await self._execute_mcp_research(retriever, query)
                    if mcp_results:
                        for result in mcp_results:
                            content = result.get("body", "")
                            url = result.get("href", "")
                            title = result.get("title", "")
                            
                            if content:
                                context_entry = {
                                    "content": content,
                                    "url": url,
                                    "title": title,
                                    "query": query,
                                    "source_type": "mcp"
                                }
                                all_mcp_context.append(context_entry)
                        
                        self.logger.info(f"Added {len(mcp_results)} MCP results for query: {query}")
                        
                        if self.researcher.verbose:
                            await stream_output(
                                "logs",
                                "mcp_results_cached",
                                f"✅ Cached {len(mcp_results)} MCP results from query {i}/{len(queries)}",
                                self.researcher.websocket,
                            )
                except Exception as e:
                    self.logger.error(f"Error in MCP research for query '{query}': {e}")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_cache_error",
                            f"⚠️ MCP research error for query {i}, continuing with other sources",
                            self.researcher.websocket,
                        )
        
        return all_mcp_context

    def _tavily_mcp_redundant_with_direct(self, mcp_retrievers, non_mcp_retrievers) -> bool:
        """当直连 Tavily 已在生效、MCP 只会重复查询 Tavily 时返回 True。

        前端的 Tavily Web Search MCP 预设与 `TavilySearch` 打的是同一套 API，
        两者同时运行时并不会带来新数据，反而额外增加 LLM 选择工具的开销（#1875）。
        """
        if not mcp_retrievers or not non_mcp_retrievers:
            return False
        has_direct_tavily = any(
            getattr(r, "__name__", "").lower() == "tavilysearch" for r in non_mcp_retrievers
        )
        if not has_direct_tavily:
            return False
        configs = getattr(self.researcher, "mcp_configs", None) or []
        if not configs:
            return False
        # 若配置的每个 MCP server 都是 Tavily 的 MCP 包，就视为冗余。
        def _is_tavily_mcp(cfg: dict) -> bool:
            name = str(cfg.get("name", "")).lower()
            args = " ".join(str(a) for a in (cfg.get("args") or [])).lower()
            command = str(cfg.get("command", "")).lower()
            blob = f"{name} {args} {command}"
            return "tavily" in blob

        return all(isinstance(c, dict) and _is_tavily_mcp(c) for c in configs)


    async def _process_sub_query(self, sub_query: str, scraped_data: list = [], query_domains: list = []):
        """接收一个子查询，据此抓取 url 并汇总上下文。"""
        if self.json_handler:
            self.json_handler.log_event("sub_query", {
                "query": sub_query,
                "scraped_data_size": len(scraped_data)
            })
        
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "running_subquery_research",
                f"\n🔍 Running research for '{sub_query}'...",
                self.researcher.websocket,
            )

        try:
            # 区分出 MCP retriever
            mcp_retrievers = [r for r in self.researcher.retrievers if "mcpretriever" in r.__name__.lower()]
            non_mcp_retrievers = [r for r in self.researcher.retrievers if "mcpretriever" not in r.__name__.lower()]

            # 在默认 RETRIEVER=tavily 下，避免走上双份 Tavily 的路径（直连 retriever + tavily-mcp）。
            if self._tavily_mcp_redundant_with_direct(mcp_retrievers, non_mcp_retrievers):
                self.logger.warning(
                    "Skipping LLM MCP Tavily path because TavilySearch is already configured as a direct retriever; set RETRIEVER without tavily or use non-Tavily MCP servers to keep MCP."
                )
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_tavily_deduped",
                        "⚠️ Skipping Tavily MCP (redundant with direct Tavily retriever) to avoid double API cost",
                        self.researcher.websocket,
                    )
                mcp_retrievers = []
            
            # 初始化上下文的各个组成部分
            mcp_context = []
            web_context = ""

            # 读取 MCP 策略配置
            mcp_strategy = self._get_mcp_strategy()

            # **可配置的 MCP 处理**
            if mcp_retrievers:
                if mcp_strategy == "disabled":
                    # MCP 已禁用 —— 完全跳过
                    self.logger.info(f"MCP disabled for sub-query: {sub_query}")
                elif mcp_strategy == "fast" and self._mcp_results_cache is not None:
                    # fast：直接复用缓存结果
                    mcp_context = self._mcp_results_cache.copy()
                    
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_cache_reuse",
                            f"♻️ Reusing cached MCP results ({len(mcp_context)} sources) for: {sub_query}",
                            self.researcher.websocket,
                        )
                    
                    self.logger.info(f"Reused {len(mcp_context)} cached MCP results for sub-query: {sub_query}")
                elif mcp_strategy == "deep":
                    # deep：每个子查询都跑一遍 MCP
                    self.logger.info(f"Running deep MCP research for: {sub_query}")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_comprehensive_run",
                            f"🔍 Running deep MCP research for: {sub_query}",
                            self.researcher.websocket,
                        )
                    
                    mcp_context = await self._execute_mcp_research_for_queries([sub_query], mcp_retrievers)
                else:
                    # 兜底：没有缓存且不是 deep 模式时，就为当前查询跑一次 MCP
                    self.logger.warning("MCP cache not available, falling back to per-sub-query execution")
                    if self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_fallback",
                            f"🔌 MCP cache unavailable, running MCP research for: {sub_query}",
                            self.researcher.websocket,
                        )
                    
                    mcp_context = await self._execute_mcp_research_for_queries([sub_query], mcp_retrievers)
            
            # 用非 MCP 的 retriever 获取网络搜索上下文（未提供抓取数据时）
            if not scraped_data:
                scraped_data = await self._scrape_data_by_urls(sub_query, query_domains)
                self.logger.info(f"Scraped data size: {len(scraped_data)}")

            # 基于抓取到的数据取出相似内容
            if scraped_data:
                web_context = await self.researcher.context_manager.get_similar_content_by_query(sub_query, scraped_data)
                self.logger.info(f"Web content found for sub-query: {len(str(web_context)) if web_context else 0} chars")

            # 智能合并 MCP 上下文与网络上下文
            combined_context = self._combine_mcp_and_web_context(mcp_context, web_context, sub_query)
            
            # 记录上下文合并结果
            if combined_context:
                context_length = len(str(combined_context))
                self.logger.info(f"Combined context for '{sub_query}': {context_length} chars")
                
                if self.researcher.verbose:
                    mcp_count = len(mcp_context)
                    web_available = bool(web_context)
                    cache_used = self._mcp_results_cache is not None and mcp_retrievers and mcp_strategy != "deep"
                    cache_status = " (cached)" if cache_used else ""
                    await stream_output(
                        "logs",
                        "context_combined",
                        f"📚 Combined research context: {mcp_count} MCP sources{cache_status}, {'web content' if web_available else 'no web content'}",
                        self.researcher.websocket,
                    )
            else:
                self.logger.warning(f"No combined context found for sub-query: {sub_query}")
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "subquery_context_not_found",
                        f"🤷 No content found for '{sub_query}'...",
                        self.researcher.websocket,
                    )
            
            if combined_context and self.json_handler:
                self.json_handler.log_event("content_found", {
                    "sub_query": sub_query,
                    "content_size": len(str(combined_context)),
                    "mcp_sources": len(mcp_context),
                    "web_content": bool(web_context)
                })
                
            return combined_context
            
        except Exception as e:
            self.logger.error(f"Error processing sub-query {sub_query}: {e}", exc_info=True)
            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "subquery_error",
                    f"❌ Error processing '{sub_query}': {str(e)}",
                    self.researcher.websocket,
                )
            return ""

    async def _execute_mcp_research(self, retriever, query):
        """
        用新的两阶段方式执行 MCP 研究。

        参数：
            retriever: MCP retriever 类
            query: 搜索查询

        返回：
            list: MCP 研究结果
        """
        retriever_name = retriever.__name__
        
        self.logger.info(f"Executing MCP research with {retriever_name} for query: {query}")
        
        try:
            # 用合适的参数实例化 MCP retriever
            # 传入 researcher 实例（self.researcher），它同时持有 cfg 与 mcp_configs
            retriever_instance = retriever(
                query=query, 
                headers=self.researcher.headers,
                query_domains=self.researcher.query_domains,
                websocket=self.researcher.websocket,
                researcher=self.researcher  # 传入整个 researcher 实例
            )
            
            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_retrieval_stage1",
                    f"🧠 Stage 1: Selecting optimal MCP tools for: {query}",
                    self.researcher.websocket,
                )
            
            # 执行两阶段的 MCP 搜索
            results = retriever_instance.search(
                max_results=self.researcher.cfg.max_search_results_per_query
            )
            
            if results:
                result_count = len(results)
                self.logger.info(f"MCP research completed: {result_count} results from {retriever_name}")
                
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_research_complete",
                        f"🎯 MCP research completed: {result_count} intelligent results obtained",
                        self.researcher.websocket,
                    )
                
                return results
            else:
                self.logger.info(f"No results returned from MCP research with {retriever_name}")
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "mcp_no_results",
                        f"ℹ️ No relevant information found via MCP for: {query}",
                        self.researcher.websocket,
                    )
                return []
                
        except Exception as e:
            self.logger.error(f"Error in MCP research with {retriever_name}: {str(e)}")
            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_research_error",
                    f"⚠️ MCP research error: {str(e)} - continuing with other sources",
                    self.researcher.websocket,
                )
            return []

    def _combine_mcp_and_web_context(self, mcp_context: list, web_context: str, sub_query: str) -> str:
        """
        智能合并 MCP 与网络两路研究上下文。

        参数：
            mcp_context: MCP 上下文条目列表
            web_context: 网络研究上下文字符串
            sub_query: 当前正在处理的子查询

        返回：
            str: 合并后的上下文字符串
        """
        combined_parts = []

        # 有网络上下文就先放进去
        if web_context and web_context.strip():
            combined_parts.append(web_context.strip())
            self.logger.debug(f"Added web context: {len(web_context)} chars")

        # 再按统一格式加入 MCP 上下文
        if mcp_context:
            mcp_formatted = []
            
            for i, item in enumerate(mcp_context):
                content = item.get("content", "")
                url = item.get("url", "")
                title = item.get("title", f"MCP Result {i+1}")
                
                if content and content.strip():
                    # 构造格式规整的上下文条目
                    if url and url != f"mcp://llm_analysis":
                        citation = f"\n\n*Source: {title} ({url})*"
                    else:
                        citation = f"\n\n*Source: {title}*"
                    
                    formatted_content = f"{content.strip()}{citation}"
                    mcp_formatted.append(formatted_content)
            
            if mcp_formatted:
                # 用明显的分隔符拼接 MCP 结果
                mcp_section = "\n\n---\n\n".join(mcp_formatted)
                combined_parts.append(mcp_section)
                self.logger.debug(f"Added {len(mcp_context)} MCP context entries")
        
        # 把各部分组合起来
        if combined_parts:
            final_context = "\n\n".join(combined_parts)
            self.logger.info(f"Combined context for '{sub_query}': {len(final_context)} total chars")
            return final_context
        else:
            self.logger.warning(f"No context to combine for sub-query: {sub_query}")
            return ""

    async def _process_sub_query_with_vectorstore(self, sub_query: str, filter: dict | None = None):
        """接收一个子查询，从用户提供的 vector store 中汇总上下文

        参数：
            sub_query (str): 由原始查询生成的子查询

        返回：
            str: 从检索中汇总到的上下文
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "running_subquery_with_vectorstore_research",
                f"\n🔍 Running research for '{sub_query}'...",
                self.researcher.websocket,
            )

        context = await self.researcher.context_manager.get_similar_content_by_query_with_vectorstore(sub_query, filter)

        return context

    async def _get_new_urls(self, url_set_input):
        """从给定的 url 集合中取出尚未处理过的 url。
        参数：url_set_input (set[str]): 用来取新 url 的 url 集合
        返回：list[str]: 取自该 url 集合的新 url
        """

        new_urls = []
        for url in url_set_input:
            if url not in self.researcher.visited_urls:
                self.researcher.visited_urls.add(url)
                new_urls.append(url)
                if self.researcher.verbose:
                    await stream_output(
                        "logs",
                        "added_source_url",
                        f"✅ Added source url to research: {url}\n",
                        self.researcher.websocket,
                        True,
                        url,
                    )

        return new_urls

    async def _search_relevant_source_urls(self, query, query_domains: list | None = None):
        new_search_urls = []
        prefetched_content = []
        if query_domains is None:
            query_domains = []

        # 遍历当前生效的 retriever
        # 这样即使 retriever 被临时改动，本方法依然可用
        for retriever_class in self.researcher.retrievers:
            # 跳过 MCP retriever，它们不提供可供抓取的 URL
            if "mcpretriever" in retriever_class.__name__.lower():
                continue

            try:
                # 用子查询实例化 retriever。传入请求级的 headers，
                # 这样接受该参数的 retriever（如 Tavily）会优先使用访问者提供的 key，
                # 而不是环境变量里的 key。并非所有 retriever 都接受 headers 参数
                # —— Duckduckgo 与 Bocha 只接受 (query, query_domains) ——
                # 所以先做检查，而不是强行统一各调用点。
                if "headers" in inspect.signature(retriever_class.__init__).parameters:
                    retriever = retriever_class(
                        query, headers=self.researcher.headers, query_domains=query_domains
                    )
                else:
                    retriever = retriever_class(query, query_domains=query_domains)

                # 用当前 retriever 执行搜索
                search_results = await asyncio.to_thread(
                    retriever.search, max_results=self.researcher.cfg.max_search_results_per_query
                )

                if not search_results:
                    continue

                # 这个 retriever 返回的是待抓取的 URL，还是它自己已经取回的正文？
                # 优先采用显式声明（BaseRetriever.requires_scraping）；
                # 当 retriever 没有声明时，回退到旧的按长度判断的做法，
                # 这样第三方与用户自定义的 retriever 不受影响。
                requires_scraping = getattr(retriever, "requires_scraping", None)

                # 把已有正文的结果与仍需抓取的结果分开
                for result in search_results:
                    url = result.get("href") or result.get("url")
                    raw_content = result.get("raw_content")

                    if not url:
                        continue

                    if requires_scraping is True:
                        # 已声明该行为：随 URL 一起返回的内容一律只是预览，
                        # 无论多长，页面仍需抓取。这样才不会把长摘要误当成正文，
                        # 也就不会把引用来源弄丢。
                        new_search_urls.append(url)
                    elif requires_scraping is False:
                        # 已声明该行为：正文由 retriever 自己取回。
                        if raw_content:
                            prefetched_content.append({
                                "url": url,
                                "raw_content": raw_content,
                            })
                            self.researcher.add_research_sources([{"url": url}])
                        else:
                            new_search_urls.append(url)
                    elif raw_content and len(raw_content) > 100:
                        # 未声明该行为：沿用旧逻辑，不做改动。
                        prefetched_content.append({
                            "url": url,
                            "raw_content": raw_content,
                        })
                        self.researcher.add_research_sources([{"url": url}])
                    else:
                        new_search_urls.append(url)
            except Exception as e:
                self.logger.error(f"Error searching with {retriever_class.__name__}: {e}")

        # 取得去重后的 URL
        new_search_urls = await self._get_new_urls(new_search_urls)
        random.shuffle(new_search_urls)

        return new_search_urls, prefetched_content

    async def _scrape_data_by_urls(self, sub_query, query_domains: list | None = None):
        """
        在多个 retriever 上执行子查询，并抓取得到的 URL。
        对已经提供完整正文的 retriever（如 PubMed Central），
        其内容直接透传，不再重复抓取。

        参数：
            sub_query (str): 待检索的子查询。

        返回：
            list: 抓取结果列表。
        """
        if query_domains is None:
            query_domains = []

        new_search_urls, prefetched_content = await self._search_relevant_source_urls(sub_query, query_domains)

        # 开启 verbose 模式时记录研究过程
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "researching",
                f"🤔 Researching for relevant information across multiple sources...\n",
                self.researcher.websocket,
            )

        # 只抓取需要获取正文的 URL（跳过 retriever 已提供内容的那些）
        scraped_content = await self.researcher.scraper_manager.browse_urls(new_search_urls)

        # 合并那些已提供完整正文的 retriever 预取到的内容
        scraped_content.extend(prefetched_content)

        if self.researcher.vector_store:
            self.researcher.vector_store.load(scraped_content)

        return scraped_content

    async def _search(self, retriever, query):
        """
        用指定的 retriever 执行一次搜索。

        参数：
            retriever: 要使用的 retriever 类
            query: 搜索查询

        返回：
            list: 搜索结果
        """
        retriever_name = retriever.__name__
        is_mcp_retriever = "mcpretriever" in retriever_name.lower()
        
        self.logger.info(f"Searching with {retriever_name} for query: {query}")
        
        try:
            # 实例化 retriever
            retriever_instance = retriever(
                query=query, 
                headers=self.researcher.headers,
                query_domains=self.researcher.query_domains,
                websocket=self.researcher.websocket if is_mcp_retriever else None,
                researcher=self.researcher if is_mcp_retriever else None
            )
            
            # 使用 MCP retriever 时记录 MCP server 配置
            if is_mcp_retriever and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_retrieval",
                    f"🔌 Consulting MCP server(s) for information on: {query}",
                    self.researcher.websocket,
                )
            
            # 执行搜索
            if hasattr(retriever_instance, 'search'):
                results = retriever_instance.search(
                    max_results=self.researcher.cfg.max_search_results_per_query
                )
                
                # 记录结果信息
                if results:
                    result_count = len(results)
                    self.logger.info(f"Received {result_count} results from {retriever_name}")
                    
                    # MCP retriever 的专门日志
                    if is_mcp_retriever:
                        if self.researcher.verbose:
                            await stream_output(
                                "logs",
                                "mcp_results",
                                f"✓ Retrieved {result_count} results from MCP server",
                                self.researcher.websocket,
                            )
                        
                        # 记录结果明细
                        for i, result in enumerate(results[:3]):  # 只记录前 3 条结果
                            title = result.get("title", "No title")
                            url = result.get("href", "No URL")
                            content_length = len(result.get("body", "")) if result.get("body") else 0
                            self.logger.info(f"MCP result {i+1}: '{title}' from {url} ({content_length} chars)")
                            
                        if result_count > 3:
                            self.logger.info(f"... and {result_count - 3} more MCP results")
                else:
                    self.logger.info(f"No results returned from {retriever_name}")
                    if is_mcp_retriever and self.researcher.verbose:
                        await stream_output(
                            "logs",
                            "mcp_no_results",
                            f"ℹ️ No relevant information found from MCP server for: {query}",
                            self.researcher.websocket,
                        )
                
                return results
            else:
                self.logger.error(f"Retriever {retriever_name} does not have a search method")
                return []
        except Exception as e:
            self.logger.error(f"Error searching with {retriever_name}: {str(e)}")
            if is_mcp_retriever and self.researcher.verbose:
                await stream_output(
                    "logs",
                    "mcp_error",
                    f"❌ Error retrieving information from MCP server: {str(e)}",
                    self.researcher.websocket,
                )
            return []
            
    async def _extract_content(self, results):
        """
        借助 browser manager 从搜索结果中提取正文。

        参数：
            results: 搜索结果

        返回：
            list: 提取到的正文
        """
        self.logger.info(f"Extracting content from {len(results)} search results")

        # 从搜索结果里取出 URL
        urls = []
        for result in results:
            if isinstance(result, dict) and "href" in result:
                urls.append(result["href"])

        # 没有 URL 就直接跳过
        if not urls:
            return []

        # 确保不去访问已经访问过的 URL
        new_urls = [url for url in urls if url not in self.researcher.visited_urls]

        # 没有新 URL 就返回空
        if not new_urls:
            return []

        # 从这些 URL 抓取正文
        scraped_content = await self.researcher.scraper_manager.browse_urls(new_urls)

        # 把这些 URL 记入 visited_urls
        self.researcher.visited_urls.update(new_urls)
        
        return scraped_content
        
    async def _summarize_content(self, query, content):
        """
        对提取到的内容做摘要。

        参数：
            query: 搜索查询
            content: 提取到的内容

        返回：
            str: 摘要后的内容
        """
        self.logger.info(f"Summarizing content for query: {query}")

        # 没有内容就跳过
        if not content:
            return ""

        # 借助 context manager 对内容做摘要
        summary = await self.researcher.context_manager.get_similar_content_by_query(
            query, content
        )
        
        return summary
        
    async def _update_search_progress(self, current, total):
        """
        更新检索进度。

        参数：
            current: 当前已处理的子查询数量
            total: 子查询总数
        """
        if self.researcher.verbose and self.researcher.websocket:
            progress = int((current / total) * 100)
            await stream_output(
                "logs",
                "research_progress",
                f"📊 Research Progress: {progress}%",
                self.researcher.websocket,
                True,
                {
                    "current": current,
                    "total": total,
                    "progress": progress
                }
            )

