import warnings
from datetime import date, datetime, timezone

from langchain_core.documents import Document

from .config import Config
from .utils.enum import ReportSource, ReportType, Tone
from .utils.enum import PromptFamily as PromptFamilyEnum
from typing import Callable, List, Dict, Any


## Prompt 家族 ###################################################################

class PromptFamily:
    """通用 prompt 格式化类。

    可以被模型相关的派生类覆盖。方法分成两组：

    1. Prompt 生成器：遵循统一格式，并与 ReportType 枚举对应。
        应通过 get_prompt_by_report_type 访问。

    2. Prompt 方法：面向具体场景，没有统一签名，
        在 agent 代码中直接调用。

    所有派生类都必须保留同一套方法名，但可以覆盖其中个别方法。
    """

    def __init__(self, config: Config):
        """用一个 config 实例初始化。派生类可以用它，根据所配置的模型
        和/或 provider 选择正确的 prompt 策略
        """
        self.cfg = config

    # MCP 专用 prompt
    @staticmethod
    def generate_mcp_tool_selection_prompt(query: str, tools_info: List[Dict], max_tools: int = 3) -> str:
        """
        生成让 LLM 挑选 MCP 工具的 prompt。

        参数：
            query: 研究查询
            tools_info: 可用工具及其元数据的列表
            max_tools: 最多选择多少个工具

        返回：
            str: 工具选择 prompt
        """
        import json
        
        return f"""You are a research assistant helping to select the most relevant tools for a research query.

RESEARCH QUERY: "{query}"

AVAILABLE TOOLS:
{json.dumps(tools_info, indent=2)}

TASK: Analyze the tools and select EXACTLY {max_tools} tools that are most relevant for researching the given query.

SELECTION CRITERIA:
- Choose tools that can provide information, data, or insights related to the query
- Prioritize tools that can search, retrieve, or access relevant content
- Consider tools that complement each other (e.g., different data sources)
- Exclude tools that are clearly unrelated to the research topic

Return a JSON object with this exact format:
{{
  "selected_tools": [
    {{
      "index": 0,
      "name": "tool_name",
      "relevance_score": 9,
      "reason": "Detailed explanation of why this tool is relevant"
    }}
  ],
  "selection_reasoning": "Overall explanation of the selection strategy"
}}

Select exactly {max_tools} tools, ranked by relevance to the research query.
"""

    @staticmethod
    def generate_mcp_research_prompt(query: str, selected_tools: List) -> str:
        """
        生成用选定工具执行 MCP 研究的 prompt。

        参数：
            query: 研究查询
            selected_tools: 选中的 MCP 工具列表

        返回：
            str: 研究执行 prompt
        """
        # selected_tools 里可能是字符串，也可能是带 .name 属性的对象
        tool_names = []
        for tool in selected_tools:
            if hasattr(tool, 'name'):
                tool_names.append(tool.name)
            else:
                tool_names.append(str(tool))
        
        return f"""You are a research assistant with access to specialized tools. Your task is to research the following query and provide comprehensive, accurate information.

RESEARCH QUERY: "{query}"

INSTRUCTIONS:
1. Use the available tools to gather relevant information about the query
2. Call multiple tools if needed to get comprehensive coverage
3. If a tool call fails or returns empty results, try alternative approaches
4. Synthesize information from multiple sources when possible
5. Focus on factual, relevant information that directly addresses the query

AVAILABLE TOOLS: {tool_names}

Please conduct thorough research and provide your findings. Use the tools strategically to gather the most relevant and comprehensive information."""

    # 图片生成 prompt
    @staticmethod
    def generate_image_analysis_prompt(
        query: str,
        sections: List[Dict[str, Any]],
        max_images: int = 3,
    ) -> str:
        """生成分析哪些报告章节最需要配图的 prompt。

        参数：
            query: 研究查询。
            sections: 报告章节列表，含标题与正文。
            max_images: 最多建议几张图片。

        返回：
            str: 该分析用的 prompt。
        """
        sections_text = "\n\n".join([
            f"### Section {i+1}: {s['header']}\n{s['content'][:500]}..."
            for i, s in enumerate(sections)
        ])
        
        return f"""Analyze the following research report sections and identify which {max_images} sections would benefit MOST from a visual illustration or diagram.

RESEARCH TOPIC: {query}

REPORT SECTIONS:
{sections_text}

For each recommended section, provide:
1. The section number (1-indexed)
2. A specific, detailed image prompt that would create an informative illustration
3. A brief explanation of why this section benefits from visualization

IMPORTANT GUIDELINES:
- Choose sections where visual representation would genuinely aid understanding
- Focus on concepts, processes, comparisons, data flows, or statistics that are inherently visual
- Avoid sections that are purely textual analysis, introductions, or conclusions
- The image prompt should be specific enough to generate a relevant, professional illustration
- Images should be informative and educational, not decorative
- Consider diagrams, flowcharts, comparison charts, or conceptual illustrations

Respond in JSON format:
{{
    "suggestions": [
        {{
            "section_number": 1,
            "section_header": "Section Title",
            "image_prompt": "Detailed prompt for generating an informative illustration...",
            "image_type": "diagram|flowchart|comparison|concept|data_visualization",
            "reason": "Why this section benefits from visualization"
        }}
    ]
}}

Return ONLY the JSON, no additional text."""

    @staticmethod
    def generate_image_prompt_enhancement(
        base_prompt: str,
        section_content: str,
        research_topic: str,
    ) -> str:
        """为图片 prompt 补充上下文，以获得更好的生成效果。

        参数：
            base_prompt: 基础的图片生成 prompt。
            section_content: 报告章节中的内容。
            research_topic: 主要研究主题。

        返回：
            str: 增强后的图片 prompt。
        """
        return f"""Create a professional, informative illustration for a research report.

RESEARCH TOPIC: {research_topic}

IMAGE DESCRIPTION: {base_prompt}

CONTEXT FROM REPORT:
{section_content[:800]}

STYLE REQUIREMENTS:
- Professional and clean design suitable for academic/business reports
- Clear, easy-to-understand visual elements
- Modern, minimalist aesthetic
- Use a professional color palette (blues, teals, grays)
- Avoid excessive text in the image
- High contrast for readability
- If showing data or comparisons, use clear labels and legends
- Suitable for both digital viewing and printing"""

    @staticmethod
    def generate_search_queries_prompt(
        question: str,
        parent_query: str,
        report_type: str,
        max_iterations: int = 3,
        context: List[Dict[str, Any]] = [],
        language: str = "english",
    ):
        """为给定问题生成搜索查询 prompt。
        参数：
            question (str): 要为其生成搜索查询 prompt 的问题
            parent_query (str): 主问题（仅详细报告时相关）
            language (str): 报告撰写所用的语言，查询也用该语言生成
                —— 搜索后端会用被查询的语言作答，因此用其他语言查询
                得到的来源与报告语言不匹配。
            report_type (str): 报告类型
            max_iterations (int): 最多生成多少条搜索查询
            context (str): 上下文，借助实时网络信息更好地理解任务

        返回： str: 给定问题的搜索查询 prompt
        """

        if (
            report_type == ReportType.DetailedReport.value
            or report_type == ReportType.SubtopicReport.value
        ):
            task = f"{parent_query} - {question}"
        else:
            task = question

        context_prompt = f"""
You are a seasoned research assistant tasked with generating search queries to find relevant information for the following task: "{task}".
Context: {context}

Use this context to inform and refine your search queries. The context provides real-time web information that can help you generate more specific and relevant queries. Consider any current events, recent developments, or specific details mentioned in the context that could enhance the search queries.
""" if context else ""

        dynamic_example = ", ".join([f'"query {i+1}"' for i in range(max_iterations)])

        return f"""Write {max_iterations} search queries to research the following task: "{task}"

Each query must be a plain natural language phrase. Do not use search operator syntax
such as site:, filetype:, inurl:, intitle:, OR, AND, or NOT — these operators are
not universally supported and will return empty results on many search backends.

Write every query in {language}. The report is written in {language}, and a search
backend answers in the language it is queried in — queries in another language come
back as sources that cannot be used.

Assume the current date is {datetime.now(timezone.utc).strftime('%B %d, %Y')} if required.

{context_prompt}
You must respond with a list of strings in the following format: [{dynamic_example}].
The response should contain ONLY the list.
"""

    @staticmethod
    def generate_report_prompt(
        question: str,
        context,
        report_source: str,
        report_format="apa",
        total_words=1000,
        tone=None,
        language="english",
    ):
        """为给定问题与研究摘要生成报告 prompt。
        参数： question (str): 要为其生成报告 prompt 的问题
                research_summary (str): 要为其生成报告 prompt 的研究摘要
        返回： str: 给定问题与研究摘要的报告 prompt
        """

        reference_prompt = ""
        if report_source == ReportSource.Web.value:
            reference_prompt = f"""
You MUST write all used source urls at the end of the report as references, and make sure to not add duplicated sources, but only one reference for each.
Every url should be hyperlinked: [url website](url)
Additionally, you MUST include hyperlinks to the relevant URLs wherever they are referenced in the report:

eg: Author, A. A. (Year, Month Date). Title of web page. Website Name. [url website](url)
"""
        else:
            reference_prompt = f"""
You MUST write all used source document names at the end of the report as references, and make sure to not add duplicated sources, but only one reference for each."
"""

        tone_prompt = f"Write the report in a {tone.value} tone." if tone else ""

        return f"""
Information: "{context}"
---
Using the above information, answer the following query or task: "{question}" in a detailed report --
The report should focus on the answer to the query, should be well structured, informative,
in-depth, and comprehensive, with facts and numbers if available and at least {total_words} words.
You should strive to write the report as long as you can using all relevant and necessary information provided.

Please follow all of the following guidelines in your report:
- You MUST determine your own concrete and valid opinion based on the given information. Do NOT defer to general and meaningless conclusions.
- You MUST write the report with markdown syntax and {report_format} format.
- Structure your report with clear markdown headers: use # for the main title, ## for major sections, and ### for subsections.
- Use markdown tables when presenting structured data or comparisons to enhance readability.
- You MUST prioritize the relevance, reliability, and significance of the sources you use. Choose trusted sources over less reliable ones.
- You must also prioritize new articles over older articles if the source can be trusted.
- You MUST NOT include a table of contents, but DO include proper markdown headers (# ## ###) to structure your report clearly.
- Use in-text citation references in {report_format} format and make it with markdown hyperlink placed at the end of the sentence or paragraph that references them like this: ([in-text citation](url)).
- Every substantive claim, figure or quote MUST carry an in-text citation to the source it came from. Do NOT cite sources that do not appear in the provided information.
- Don't forget to add a reference list at the end of the report in {report_format} format.
- {reference_prompt}
- {tone_prompt}
You MUST write the report in the following language: {language}.
Assume that the current date is {date.today()}.
"""

    @staticmethod
    def curate_sources(query, sources, max_results=10):
        return f"""Your goal is to evaluate and curate the provided scraped content for the research task: "{query}"
    while prioritizing the inclusion of relevant and high-quality information, especially sources containing statistics, numbers, or concrete data.

The final curated list will be used as context for creating a research report, so prioritize:
- Retaining as much original information as possible, with extra emphasis on sources featuring quantitative data or unique insights
- Including a wide range of perspectives and insights
- Filtering out only clearly irrelevant or unusable content

EVALUATION GUIDELINES:
1. Assess each source based on:
   - Relevance: Include sources directly or partially connected to the research query. Err on the side of inclusion.
   - Credibility: Favor authoritative sources but retain others unless clearly untrustworthy.
   - Currency: Prefer recent information unless older data is essential or valuable.
   - Objectivity: Retain sources with bias if they provide a unique or complementary perspective.
   - Quantitative Value: Give higher priority to sources with statistics, numbers, or other concrete data.
2. Source Selection:
   - Include as many relevant sources as possible, up to {max_results}, focusing on broad coverage and diversity.
   - Prioritize sources with statistics, numerical data, or verifiable facts.
   - Overlapping content is acceptable if it adds depth, especially when data is involved.
   - Exclude sources only if they are entirely irrelevant, severely outdated, or unusable due to poor content quality.
3. Content Retention:
   - DO NOT rewrite, summarize, or condense any source content.
   - Retain all usable information, cleaning up only clear garbage or formatting issues.
   - Keep marginally relevant or incomplete sources if they contain valuable data or insights.

SOURCES LIST TO EVALUATE:
{sources}

You MUST return your response in the EXACT sources JSON list format as the original sources.
The response MUST not contain any markdown format or additional text (like ```json), just the JSON list!
"""

    @staticmethod
    def generate_resource_report_prompt(
        question, context, report_source: str, report_format="apa", tone=None, total_words=1000, language="english"
    ):
        """为给定问题与研究摘要生成资源报告 prompt。

        参数：
            question (str): 要为其生成资源报告 prompt 的问题。
            context (str): 要为其生成资源报告 prompt 的研究摘要。

        返回：
            str: 给定问题与研究摘要的资源报告 prompt。
        """

        reference_prompt = ""
        if report_source == ReportSource.Web.value:
            reference_prompt = f"""
            You MUST include all relevant source urls.
            Every url should be hyperlinked: [url website](url)
            """
        else:
            reference_prompt = f"""
            You MUST write all used source document names at the end of the report as references, and make sure to not add duplicated sources, but only one reference for each."
        """

        return (
            f'"""{context}"""\n\nBased on the above information, generate a bibliography recommendation report for the following'
            f' question or topic: "{question}". The report should provide a detailed analysis of each recommended resource,'
            " explaining how each source can contribute to finding answers to the research question.\n"
            "Focus on the relevance, reliability, and significance of each source.\n"
            "Ensure that the report is well-structured, informative, in-depth, and follows Markdown syntax.\n"
            "Use markdown tables and other formatting features when appropriate to organize and present information clearly.\n"
            "Include relevant facts, figures, and numbers whenever available.\n"
            f"The report should have a minimum length of {total_words} words.\n"
            f"You MUST write the report in the following language: {language}.\n"
            "You MUST include all relevant source urls."
            "Every url should be hyperlinked: [url website](url)"
            f"{reference_prompt}"
        )

    @staticmethod
    def generate_custom_report_prompt(
        query_prompt, context, report_source: str, report_format="apa", tone=None, total_words=1000, language: str = "english"
    ):
        return f'"{context}"\n\n{query_prompt}'

    @staticmethod
    def generate_outline_report_prompt(
        question, context, report_source: str, report_format="apa", tone=None,  total_words=1000, language: str = "english"
    ):
        """为给定问题与研究摘要生成大纲报告 prompt。
        参数： question (str): 要为其生成大纲报告 prompt 的问题
                research_summary (str): 要为其生成大纲报告 prompt 的研究摘要
        返回： str: 给定问题与研究摘要的大纲报告 prompt
        """

        return (
            f'"""{context}""" Using the above information, generate an outline for a research report in Markdown syntax'
            f' for the following question or topic: "{question}". The outline should provide a well-structured framework'
            " for the research report, including the main sections, subsections, and key points to be covered."
            f" The research report should be detailed, informative, in-depth, and a minimum of {total_words} words."
            " Use appropriate Markdown syntax to format the outline and ensure readability."
            " Consider using markdown tables and other formatting features where they would enhance the presentation of information."
        )

    @staticmethod
    def generate_deep_research_prompt(
        question: str,
        context: str,
        report_source: str,
        report_format="apa",
        tone=None,
        total_words=2000,
        language: str = "english"
    ):
        """生成深度研究报告 prompt，专门用于处理分层的研究结果。
        参数：
            question (str): 研究问题
            context (str): 研究上下文，含带引用的研究成果
            report_source (str): 研究来源（web 等）
            report_format (str): 报告格式风格
            tone: 撰写时使用的语气
            total_words (int): 最小字数
            language (str): 输出语言
        返回：
            str: 深度研究报告 prompt
        """
        reference_prompt = ""
        if report_source == ReportSource.Web.value:
            reference_prompt = f"""
You MUST write all used source urls at the end of the report as references, and make sure to not add duplicated sources, but only one reference for each.
Every url should be hyperlinked: [url website](url)
Additionally, you MUST include hyperlinks to the relevant URLs wherever they are referenced in the report:

eg: Author, A. A. (Year, Month Date). Title of web page. Website Name. [url website](url)
"""
        else:
            reference_prompt = f"""
You MUST write all used source document names at the end of the report as references, and make sure to not add duplicated sources, but only one reference for each."
"""

        tone_prompt = f"Write the report in a {tone.value} tone." if tone else ""

        return f"""
Using the following hierarchically researched information and citations:

"{context}"

Write a comprehensive research report answering the query: "{question}"

The report should:
1. Synthesize information from multiple levels of research depth
2. Integrate findings from various research branches
3. Present a coherent narrative that builds from foundational to advanced insights
4. Maintain proper citation of sources throughout
5. Be well-structured with clear sections and subsections
6. Have a minimum length of {total_words} words
7. Follow {report_format} format with markdown syntax
8. Use markdown tables, lists and other formatting features when presenting comparative data, statistics, or structured information

Additional requirements:
- Prioritize insights that emerged from deeper levels of research
- Highlight connections between different research branches
- Include relevant statistics, data, and concrete examples
- You MUST determine your own concrete and valid opinion based on the given information. Do NOT defer to general and meaningless conclusions.
- You MUST prioritize the relevance, reliability, and significance of the sources you use. Choose trusted sources over less reliable ones.
- You must also prioritize new articles over older articles if the source can be trusted.
- Use in-text citation references in {report_format} format and make it with markdown hyperlink placed at the end of the sentence or paragraph that references them like this: ([in-text citation](url)).
- {tone_prompt}
- Write in {language}

{reference_prompt}

Please write a thorough, well-researched report that synthesizes all the gathered information into a cohesive whole.
Assume the current date is {datetime.now(timezone.utc).strftime('%B %d, %Y')}.
"""

    @staticmethod
    def auto_agent_instructions():
        return """
This task involves researching a given topic, regardless of its complexity or the availability of a definitive answer. The research is conducted by a specific server, defined by its type and role, with each server requiring distinct instructions.
Agent
The server is determined by the field of the topic and the specific name of the server that could be utilized to research the topic provided. Agents are categorized by their area of expertise, and each server type is associated with a corresponding emoji.

examples:
task: "should I invest in apple stocks?"
response:
{
    "server": "💰 Finance Agent",
    "agent_role_prompt": "You are a seasoned finance analyst AI assistant. Your primary goal is to compose comprehensive, astute, impartial, and methodically arranged financial reports based on provided data and trends."
}
task: "could reselling sneakers become profitable?"
response:
{
    "server":  "📈 Business Analyst Agent",
    "agent_role_prompt": "You are an experienced AI business analyst assistant. Your main objective is to produce comprehensive, insightful, impartial, and systematically structured business reports based on provided business data, market trends, and strategic analysis."
}
task: "what are the most interesting sites in Tel Aviv?"
response:
{
    "server":  "🌍 Travel Agent",
    "agent_role_prompt": "You are a world-travelled AI tour guide assistant. Your main purpose is to draft engaging, insightful, unbiased, and well-structured travel reports on given locations, including history, attractions, and cultural insights."
}
"""

    @staticmethod
    def generate_summary_prompt(query, data):
        """为给定问题与文本生成摘要 prompt。
        参数： question (str): 要为其生成摘要 prompt 的问题
                text (str): 要为其生成摘要 prompt 的文本
        返回： str: 给定问题与文本的摘要 prompt
        """

        return (
            f'{data}\n Using the above text, summarize it based on the following task or query: "{query}".\n If the '
            f"query cannot be answered using the text, YOU MUST summarize the text in short.\n Include all factual "
            f"information such as numbers, stats, quotes, etc if available. "
        )

    @staticmethod
    def generate_quick_summary_prompt(query: str, context: str) -> str:
        """为给定问题与上下文生成快速摘要 prompt。
        参数：
            query (str): 要为其生成摘要的查询
            context (str): 要摘要的搜索结果
        返回：
            str: 快速摘要 prompt
        """
        return f"""
Synthesize a comprehensive answer to the following query based ONLY on the provided search results.
Query: "{query}"

Search Results:
{context}

Instructions:
1. Provide a single, continuous narrative summary.
2. Cite your sources using numbers [1], [2], etc., corresponding to the search results.
3. If the results are insufficient to answer the query, state that clearly.
4. Focus on accuracy and relevance.
"""

    @staticmethod
    def pretty_print_docs(docs: list[Document], top_n: int | None = None) -> str:
        """把文档列表压缩成一个上下文字符串"""
        return f"\n".join(f"Source: {d.metadata.get('source')}\n"
                          f"Title: {d.metadata.get('title')}\n"
                          f"Content: {d.page_content}\n"
                          for i, d in enumerate(docs)
                          if top_n is None or i < top_n)

    @staticmethod
    def join_local_web_documents(docs_context: str, web_context: str) -> str:
        """把本地文档与从互联网抓取的上下文拼接起来"""
        return f"Context from local documents: {docs_context}\n\nContext from web sources: {web_context}"

    ################################################################################################

    # 详细报告 prompt

    @staticmethod
    def generate_subtopics_prompt() -> str:
        return """
Provided the main topic:

{task}

and research data:

{data}

- Construct a list of subtopics which indicate the headers of a report document to be generated on the task.
- These are a possible list of subtopics : {subtopics}.
- There should NOT be any duplicate subtopics.
- Limit the number of subtopics to a maximum of {max_subtopics}
- Finally order the subtopics by their tasks, in a relevant and meaningful order which is presentable in a detailed report

"IMPORTANT!":
- Every subtopic MUST be relevant to the main topic and provided research data ONLY!

{format_instructions}
"""

    @staticmethod
    def generate_subtopic_report_prompt(
        current_subtopic,
        existing_headers: list,
        relevant_written_contents: list,
        main_topic: str,
        context,
        report_format: str = "apa",
        max_subsections=5,
        total_words=800,
        tone: Tone = Tone.Objective,
        language: str = "english",
    ) -> str:
        return f"""
Context:
"{context}"

Main Topic and Subtopic:
Using the latest information available, construct a detailed report on the subtopic: {current_subtopic} under the main topic: {main_topic}.
You must limit the number of subsections to a maximum of {max_subsections}.

Content Focus:
- The report should focus on answering the question, be well-structured, informative, in-depth, and include facts and numbers if available.
- Use markdown syntax and follow the {report_format.upper()} format.
- When presenting data, comparisons, or structured information, use markdown tables to enhance readability.

IMPORTANT:Content and Sections Uniqueness:
- This part of the instructions is crucial to ensure the content is unique and does not overlap with existing reports.
- Carefully review the existing headers and existing written contents provided below before writing any new subsections.
- Prevent any content that is already covered in the existing written contents.
- Do not use any of the existing headers as the new subsection headers.
- Do not repeat any information already covered in the existing written contents or closely related variations to avoid duplicates.
- If you have nested subsections, ensure they are unique and not covered in the existing written contents.
- Ensure that your content is entirely new and does not overlap with any information already covered in the previous subtopic reports.

"Existing Subtopic Reports":
- Existing subtopic reports and their section headers:

    {existing_headers}

- Existing written contents from previous subtopic reports:

    {relevant_written_contents}

"Structure and Formatting":
- As this sub-report will be part of a larger report, include only the main body divided into suitable subtopics without any introduction or conclusion section.

- You MUST include markdown hyperlinks to relevant source URLs wherever referenced in the report, for example:

    ### Section Header

    This is a sample text ([in-text citation](url)).

- Use H2 for the main subtopic header (##) and H3 for subsections (###).
- Use smaller Markdown headers (e.g., H2 or H3) for content structure, avoiding the largest header (H1) as it will be used for the larger report's heading.
- Organize your content into distinct sections that complement but do not overlap with existing reports.
- When adding similar or identical subsections to your report, you should clearly indicate the differences between and the new content and the existing written content from previous subtopic reports. For example:

    ### New header (similar to existing header)

    While the previous section discussed [topic A], this section will explore [topic B]."

"Date":
Assume the current date is {datetime.now(timezone.utc).strftime('%B %d, %Y')} if required.

"IMPORTANT!":
- You MUST write the report in the following language: {language}.
- The focus MUST be on the main topic! You MUST Leave out any information un-related to it!
- Must NOT have any introduction, conclusion, summary or reference section.
- You MUST use in-text citation references in {report_format.upper()} format and make it with markdown hyperlink placed at the end of the sentence or paragraph that references them like this: ([in-text citation](url)).
- You MUST mention the difference between the existing content and the new content in the report if you are adding the similar or same subsections wherever necessary.
- The report should have a minimum length of {total_words} words.
- Use an {tone.value} tone throughout the report.

Do NOT add a conclusion section.
"""

    @staticmethod
    def generate_draft_titles_prompt(
        current_subtopic: str,
        main_topic: str,
        context: str,
        max_subsections: int = 5
    ) -> str:
        return f"""
"Context":
"{context}"

"Main Topic and Subtopic":
Using the latest information available, construct a draft section title headers for a detailed report on the subtopic: {current_subtopic} under the main topic: {main_topic}.

"Task":
1. Create a list of draft section title headers for the subtopic report.
2. Each header should be concise and relevant to the subtopic.
3. The header should't be too high level, but detailed enough to cover the main aspects of the subtopic.
4. Use markdown syntax for the headers, using H3 (###) as H1 and H2 will be used for the larger report's heading.
5. Ensure the headers cover main aspects of the subtopic.

"Structure and Formatting":
Provide the draft headers in a list format using markdown syntax, for example:

### Header 1
### Header 2
### Header 3

"IMPORTANT!":
- The focus MUST be on the main topic! You MUST Leave out any information un-related to it!
- Must NOT have any introduction, conclusion, summary or reference section.
- Focus solely on creating headers, not content.
"""

    @staticmethod
    def generate_report_introduction(question: str, research_summary: str = "", language: str = "english", report_format: str = "apa") -> str:
        return f"""{research_summary}\n
Using the above latest information, Prepare a detailed report introduction on the topic -- {question}.
- The introduction should be succinct, well-structured, informative with markdown syntax.
- As this introduction will be part of a larger report, do NOT include any other sections, which are generally present in a report.
- The introduction should be preceded by an H1 heading with a suitable topic for the entire report.
- You must use in-text citation references in {report_format.upper()} format and make it with markdown hyperlink placed at the end of the sentence or paragraph that references them like this: ([in-text citation](url)).
Assume that the current date is {datetime.now(timezone.utc).strftime('%B %d, %Y')} if required.
- The output must be in {language} language.
"""


    @staticmethod
    def generate_report_conclusion(query: str, report_content: str, language: str = "english", report_format: str = "apa") -> str:
        """
        生成一段简洁的结论，概括研究报告的主要发现与启示。

        参数：
            query (str): 研究任务或问题。
            report_content (str): 研究报告的内容。
            language (str): 结论应当使用的语言。

        返回：
            str: 概括报告主要发现与启示的简洁结论。
        """
        prompt = f"""
    Based on the research report below and research task, please write a concise conclusion that summarizes the main findings and their implications:

    Research task: {query}

    Research Report: {report_content}

    Your conclusion should:
    1. Recap the main points of the research
    2. Highlight the most important findings
    3. Discuss any implications or next steps
    4. Be approximately 2-3 paragraphs long

    If there is no "## Conclusion" section title written at the end of the report, please add it to the top of your conclusion.
    You must use in-text citation references in {report_format.upper()} format and make it with markdown hyperlink placed at the end of the sentence or paragraph that references them like this: ([in-text citation](url)).

    IMPORTANT: The entire conclusion MUST be written in {language} language.

    Write the conclusion:
    """

        return prompt


class GranitePromptFamily(PromptFamily):
    """IBM granite 模型使用的 prompt"""


    def _get_granite_class(self) -> type[PromptFamily]:
        """根据版本号选出正确的 granite prompt 家族"""
        if "3.3" in self.cfg.smart_llm:
            return Granite33PromptFamily
        if "3" in self.cfg.smart_llm:
            return Granite3PromptFamily
        # 不是已知版本则返回默认实现
        return PromptFamily

    def pretty_print_docs(self, *args, **kwargs) -> str:
        return self._get_granite_class().pretty_print_docs(*args, **kwargs)

    def join_local_web_documents(self, *args, **kwargs) -> str:
        return self._get_granite_class().join_local_web_documents(*args, **kwargs)


class Granite3PromptFamily(PromptFamily):
    """IBM granite 3.X 模型（3.3 之前）使用的 prompt"""

    _DOCUMENTS_PREFIX = "<|start_of_role|>documents<|end_of_role|>\n"
    _DOCUMENTS_SUFFIX = "\n<|end_of_text|>"

    @classmethod
    def pretty_print_docs(cls, docs: list[Document], top_n: int | None = None) -> str:
        if not docs:
            return ""
        all_documents = "\n\n".join([
            f"Document {doc.metadata.get('source', i)}\n" + \
            f"Title: {doc.metadata.get('title')}\n" + \
            doc.page_content
            for i, doc in enumerate(docs)
            if top_n is None or i < top_n
        ])
        return "".join([cls._DOCUMENTS_PREFIX, all_documents, cls._DOCUMENTS_SUFFIX])

    @classmethod
    def join_local_web_documents(cls, docs_context: str | list, web_context: str | list) -> str:
        """按 Granite 偏好的格式拼接本地与网络文档"""
        if isinstance(docs_context, str) and docs_context.startswith(cls._DOCUMENTS_PREFIX):
            docs_context = docs_context[len(cls._DOCUMENTS_PREFIX):]
        if isinstance(web_context, str) and web_context.endswith(cls._DOCUMENTS_SUFFIX):
            web_context = web_context[:-len(cls._DOCUMENTS_SUFFIX)]
        all_documents = "\n\n".join([docs_context, web_context])
        return "".join([cls._DOCUMENTS_PREFIX, all_documents, cls._DOCUMENTS_SUFFIX])


class Granite33PromptFamily(PromptFamily):
    """IBM granite 3.3 模型使用的 prompt"""

    _DOCUMENT_TEMPLATE = """<|start_of_role|>document {{"document_id": "{document_id}"}}<|end_of_role|>
{document_content}<|end_of_text|>
"""

    @staticmethod
    def _get_content(doc: Document) -> str:
        doc_content = doc.page_content
        if title := doc.metadata.get("title"):
            doc_content = f"Title: {title}\n{doc_content}"
        return doc_content.strip()

    @classmethod
    def pretty_print_docs(cls, docs: list[Document], top_n: int | None = None) -> str:
        return "\n".join([
            cls._DOCUMENT_TEMPLATE.format(
                document_id=doc.metadata.get("source", i),
                document_content=cls._get_content(doc),
            )
            for i, doc in enumerate(docs)
            if top_n is None or i < top_n
        ])

    @classmethod
    def join_local_web_documents(cls, docs_context: str | list, web_context: str | list) -> str:
        """按 Granite 偏好的格式拼接本地与网络文档"""
        return "\n\n".join([docs_context, web_context])

## 工厂 ###########################################################################

# 这是各类 prompt 生成函数的签名
PROMPT_GENERATOR = Callable[
    [
        str,        # 问题
        str,        # 上下文
        str,        # 报告来源
        str,        # 报告格式
        str | None, # 语气
        int,        # 总字数
        str,        # 语言
    ],
    str,
]

report_type_mapping = {
    ReportType.ResearchReport.value: "generate_report_prompt",
    ReportType.ResourceReport.value: "generate_resource_report_prompt",
    ReportType.OutlineReport.value: "generate_outline_report_prompt",
    ReportType.CustomReport.value: "generate_custom_report_prompt",
    ReportType.SubtopicReport.value: "generate_subtopic_report_prompt",
    ReportType.DeepResearch.value: "generate_deep_research_prompt",
}


def get_prompt_by_report_type(
    report_type: str,
    prompt_family: type[PromptFamily] | PromptFamily,
):
    prompt_by_type = getattr(prompt_family, report_type_mapping.get(report_type, ""), None)
    default_report_type = ReportType.ResearchReport.value
    if not prompt_by_type:
        warnings.warn(
            f"Invalid report type: {report_type}.\n"
            f"Please use one of the following: {', '.join([enum_value for enum_value in report_type_mapping.keys()])}\n"
            f"Using default report type: {default_report_type} prompt.",
            UserWarning,
        )
        prompt_by_type = getattr(prompt_family, report_type_mapping.get(default_report_type))
    return prompt_by_type


prompt_family_mapping = {
    PromptFamilyEnum.Default.value: PromptFamily,
    PromptFamilyEnum.Granite.value: GranitePromptFamily,
    PromptFamilyEnum.Granite3.value: Granite3PromptFamily,
    PromptFamilyEnum.Granite31.value: Granite3PromptFamily,
    PromptFamilyEnum.Granite32.value: Granite3PromptFamily,
    PromptFamilyEnum.Granite33.value: Granite33PromptFamily,
}


def get_prompt_family(
    prompt_family_name: PromptFamilyEnum | str, config: Config,
) -> PromptFamily:
    """按名称或取值获取 prompt 家族。"""
    if isinstance(prompt_family_name, PromptFamilyEnum):
        prompt_family_name = prompt_family_name.value
    if prompt_family := prompt_family_mapping.get(prompt_family_name):
        return prompt_family(config)
    warnings.warn(
        f"Invalid prompt family: {prompt_family_name}.\n"
        f"Please use one of the following: {', '.join([enum_value for enum_value in prompt_family_mapping.keys()])}\n"
        f"Using default prompt family: {PromptFamilyEnum.Default.value} prompt.",
        UserWarning,
    )
    return PromptFamily()
