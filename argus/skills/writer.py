"""Argus 的报告生成技能。

本模块提供 ReportGenerator 类，负责报告撰写，包括引言、结论与子主题管理。
"""

from typing import Dict, Optional

from ..actions import (
    generate_draft_section_titles,
    generate_report,
    stream_output,
    write_conclusion,
    write_report_introduction,
)
from ..utils.llm import construct_subtopics


class ReportGenerator:
    """基于研究数据生成报告。

    本类处理报告生成的各个环节，包括撰写引言、结论以及管理报告结构。

    属性：
        researcher: 持有该生成器的父级 Argus 实例。
        research_params: 报告生成所用的参数字典。
    """

    def __init__(self, researcher):
        """初始化 ReportGenerator。

        参数：
            researcher: 持有该生成器的 Argus 实例。
        """
        self.researcher = researcher
        self.research_params = {
            "query": self.researcher.query,
            "agent_role_prompt": self.researcher.cfg.agent_role or self.researcher.role,
            "report_type": self.researcher.report_type,
            "report_source": self.researcher.report_source,
            "tone": self.researcher.tone,
            "websocket": self.researcher.websocket,
            "cfg": self.researcher.cfg,
            "headers": self.researcher.headers,
        }

    async def write_report(self, existing_headers: list = [], relevant_written_contents: list = [], ext_context=None, custom_prompt="", available_images: list = None) -> str:
        """
        基于已有标题与相关内容撰写报告。

        参数：
            existing_headers (list): 已有标题列表。
            relevant_written_contents (list): 相关已写内容列表。
            ext_context (Optional): 外部上下文（若有）。
            custom_prompt (str): 报告的自定义 prompt。
            available_images (list): 可供嵌入的预生成图片。

        返回：
            str: 生成的报告。
        """
        available_images = available_images or []

        context = ext_context or self.researcher.context

        # 防止凭空捏造报告：若没有收集到任何研究内容（所有 retriever 都返回空、
        # 被拦截或被限流），不要默不作声地写出看起来证据充分、自信满满的报告 ——
        # 应当弃权，让这种情况暴露出来。
        _ctx = "\n".join(context) if isinstance(context, list) else str(context or "")
        if not _ctx.strip():
            return (
                f'未能为「{self.researcher.query}」获取到任何来源资料。'
                "本次检索没有返回结果（可能是搜索接口无响应、被限流或网络不可达），"
                "因此无法生成有据可依的报告。"
            )
        
        # 记录图片可用情况
        if available_images and self.researcher.verbose:
            await stream_output(
                "logs",
                "images_available",
                f"🖼️ {len(available_images)} pre-generated images available for embedding",
                self.researcher.websocket,
            )
        
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "writing_report",
                f"✍️ Writing report for '{self.researcher.query}'...",
                self.researcher.websocket,
            )

        report_params = self.research_params.copy()
        if not report_params["agent_role_prompt"]:
            report_params["agent_role_prompt"] = self.researcher.cfg.agent_role or self.researcher.role
        report_params["context"] = context
        report_params["custom_prompt"] = custom_prompt
        report_params["available_images"] = available_images  # 传入预生成的图片

        if self.researcher.report_type == "subtopic_report":
            report_params.update({
                "main_topic": self.researcher.parent_query,
                "existing_headers": existing_headers,
                "relevant_written_contents": relevant_written_contents,
                "cost_callback": self.researcher.add_costs,
            })
        else:
            report_params["cost_callback"] = self.researcher.add_costs

        report = await generate_report(**report_params, **self.researcher.kwargs)

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "report_written",
                f"📝 Report written for '{self.researcher.query}'",
                self.researcher.websocket,
            )

        return report

    async def write_report_conclusion(self, report_content: str) -> str:
        """
        撰写报告的结论。

        参数：
            report_content (str): 报告的正文内容。

        返回：
            str: 生成的结论。
        """
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "writing_conclusion",
                f"✍️ Writing conclusion for '{self.researcher.query}'...",
                self.researcher.websocket,
            )

        conclusion = await write_conclusion(
            query=self.researcher.query,
            context=report_content,
            config=self.researcher.cfg,
            agent_role_prompt=self.researcher.cfg.agent_role or self.researcher.role,
            cost_callback=self.researcher.add_costs,
            websocket=self.researcher.websocket,
            prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "conclusion_written",
                f"📝 Conclusion written for '{self.researcher.query}'",
                self.researcher.websocket,
            )

        return conclusion

    async def write_introduction(self):
        """撰写报告的引言部分。"""
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "writing_introduction",
                f"✍️ Writing introduction for '{self.researcher.query}'...",
                self.researcher.websocket,
            )

        introduction = await write_report_introduction(
            query=self.researcher.query,
            context=self.researcher.context,
            agent_role_prompt=self.researcher.cfg.agent_role or self.researcher.role,
            config=self.researcher.cfg,
            websocket=self.researcher.websocket,
            cost_callback=self.researcher.add_costs,
            prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "introduction_written",
                f"📝 Introduction written for '{self.researcher.query}'",
                self.researcher.websocket,
            )

        return introduction

    async def get_subtopics(self):
        """获取本次研究的子主题。"""
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "generating_subtopics",
                f"🌳 Generating subtopics for '{self.researcher.query}'...",
                self.researcher.websocket,
            )

        subtopics = await construct_subtopics(
            task=self.researcher.query,
            data=self.researcher.context,
            config=self.researcher.cfg,
            subtopics=self.researcher.subtopics,
            prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "subtopics_generated",
                f"📊 Subtopics generated for '{self.researcher.query}'",
                self.researcher.websocket,
            )

        return subtopics

    async def get_draft_section_titles(self, current_subtopic: str):
        """为报告生成草稿章节标题。"""
        if self.researcher.verbose:
            await stream_output(
                "logs",
                "generating_draft_sections",
                f"📑 Generating draft section titles for '{self.researcher.query}'...",
                self.researcher.websocket,
            )

        draft_section_titles = await generate_draft_section_titles(
            query=self.researcher.query,
            current_subtopic=current_subtopic,
            context=self.researcher.context,
            role=self.researcher.cfg.agent_role or self.researcher.role,
            websocket=self.researcher.websocket,
            config=self.researcher.cfg,
            cost_callback=self.researcher.add_costs,
            prompt_family=self.researcher.prompt_family,
            **self.researcher.kwargs
        )

        if self.researcher.verbose:
            await stream_output(
                "logs",
                "draft_sections_generated",
                f"🗂️ Draft section titles generated for '{self.researcher.query}'",
                self.researcher.websocket,
            )

        return draft_section_titles
