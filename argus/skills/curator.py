"""Argus 的来源筛选技能。

本模块提供 SourceCurator 类，按相关性、可信度与可靠性评估并排序研究来源。
"""

from typing import Dict, List, Optional

import json_repair
from langchain_core.utils.json import parse_json_markdown

from ..actions import stream_output
from ..config.config import Config
from ..utils.llm import create_chat_completion


class SourceCurator:
    """按相关性、可信度与可靠性对来源进行排序与筛选。

    本类借助 LLM 评估研究来源，挑选最适合用于生成报告的那些来源。

    属性：
        researcher: 持有该筛选器的父级 Argus 实例。
    """

    def __init__(self, researcher):
        """初始化 SourceCurator。

        参数：
            researcher: 持有该筛选器的 Argus 实例。
        """
        self.researcher = researcher

    async def curate_sources(
        self,
        source_data: List,
        max_results: int = 10,
    ) -> List:
        """
        依据研究数据与评判准则对来源排序。

        参数：
            query: 研究查询/任务
            source_data: 待排序的来源文档列表
            max_results: 最多返回的优质来源数量

        返回：
            str: 带理由说明的已排序来源 URL 列表
        """
        print(f"\n\nCurating {len(source_data)} sources: {source_data}")
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "research_plan",
                f"⚖️ Evaluating and curating sources by credibility and relevance...",
                self.researcher.websocket,
            )

        response = ""
        try:
            response = await create_chat_completion(
                model=self.researcher.cfg.smart_llm_model,
                messages=[
                    {"role": "system", "content": f"{self.researcher.role}"},
                    {"role": "user", "content": self.researcher.prompt_family.curate_sources(
                        self.researcher.query, source_data, max_results)},
                ],
                temperature=0.2,
                max_tokens=8000,
                llm_provider=self.researcher.cfg.smart_llm_provider,
                llm_kwargs=self.researcher.cfg.llm_kwargs,
                cost_callback=self.researcher.add_costs,
            )

            # LLM 常常无视 prompt 中的要求，把 JSON 包在 ```json 围栏里或另加散文，
            # 这种情况 json.loads 解析不了。这里沿用代码库其他位置的恢复方式
            # （参见 actions/query_processing.py、multi_agents/agents/utils/
            # llms.py），以免格式正确但被围栏包裹的响应被直接丢弃。
            curated_sources = parse_json_markdown(response, parser=json_repair.loads)
            # json_repair 从不抛异常：输出不可用时返回的是 "" 或 dict 而非 list。
            # 这里做个校验，让这类结果仍能回退到下方未筛选的来源，
            # 而不是把上下文清空。
            if not isinstance(curated_sources, list):
                raise ValueError(
                    f"expected a JSON list of sources, got "
                    f"{type(curated_sources).__name__}"
                )
            print(f"\n\nFinal Curated sources {len(source_data)} sources: {curated_sources}")

            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "research_plan",
                    f"🏅 Verified and ranked top {len(curated_sources)} most reliable sources",
                    self.researcher.websocket,
                )

            return curated_sources

        except Exception as e:
            print(f"Error in curate_sources from LLM response: {response}")
            if self.researcher.verbose:
                await stream_output(
                    "logs",
                    "research_plan",
                    f"🚫 Source verification failed: {str(e)}",
                    self.researcher.websocket,
                )
            return source_data
