"""Argus 配置所用的枚举类型。"""

from enum import Enum


class ReportType(Enum):
    """研究输出可用的报告类型枚举。

    定义 Argus agent 能够生成的各类报告。

    属性：
        ResearchReport: 标准研究报告，含全面分析。
        ResourceReport: 侧重罗列并描述相关资源的报告。
        OutlineReport: 给出主题结构化大纲的报告。
        CustomReport: 用户自定义的报告格式。
        DetailedReport: 深入详尽的分析报告。
        SubtopicReport: 聚焦某个具体子主题的报告。
        DeepResearch: 深度研究模式，分析更为广泛。
    """
    ResearchReport = "research_report"
    ResourceReport = "resource_report"
    OutlineReport = "outline_report"
    CustomReport = "custom_report"
    DetailedReport = "detailed_report"
    SubtopicReport = "subtopic_report"
    DeepResearch = "deep"


class ReportSource(Enum):
    """研究可用的数据来源枚举。

    定义 researcher 生成报告时可以采集信息的各类来源。

    属性：
        Web: 从网络上搜索并抓取内容。
        Local: 使用本地文档与文件。
        LangChainDocuments: 使用 LangChain 的文档对象。
        LangChainVectorStore: 使用 LangChain 向量库进行检索。
        Static: 使用预置的静态内容。
        Hybrid: 组合多种来源类型。
    """
    Web = "web"
    Local = "local"
    LangChainDocuments = "langchain_documents"
    LangChainVectorStore = "langchain_vectorstore"
    Static = "static"
    Hybrid = "hybrid"


class Tone(Enum):
    """报告可用的写作语气枚举。

    定义生成研究报告时可选的各类语气，以匹配期望的风格与读者群。

    每个语气取值里都附带了对该写作风格的说明。
    """
    Objective = "Objective (impartial and unbiased presentation of facts and findings)"
    Formal = "Formal (adheres to academic standards with sophisticated language and structure)"
    Analytical = (
        "Analytical (critical evaluation and detailed examination of data and theories)"
    )
    Persuasive = (
        "Persuasive (convincing the audience of a particular viewpoint or argument)"
    )
    Informative = (
        "Informative (providing clear and comprehensive information on a topic)"
    )
    Explanatory = "Explanatory (clarifying complex concepts and processes)"
    Descriptive = (
        "Descriptive (detailed depiction of phenomena, experiments, or case studies)"
    )
    Critical = "Critical (judging the validity and relevance of the research and its conclusions)"
    Comparative = "Comparative (juxtaposing different theories, data, or methods to highlight differences and similarities)"
    Speculative = "Speculative (exploring hypotheses and potential implications or future research directions)"
    Reflective = "Reflective (considering the research process and personal insights or experiences)"
    Narrative = (
        "Narrative (telling a story to illustrate research findings or methodologies)"
    )
    Humorous = "Humorous (light-hearted and engaging, usually to make the content more relatable)"
    Optimistic = "Optimistic (highlighting positive findings and potential benefits)"
    Pessimistic = (
        "Pessimistic (focusing on limitations, challenges, or negative outcomes)"
    )
    Simple = "Simple (written for young readers, using basic vocabulary and clear explanations)"
    Casual = "Casual (conversational and relaxed style for easy, everyday reading)"


class PromptFamily(Enum):
    """按名称列出受支持的 prompt 家族"""
    Default = "default"
    Granite = "granite"
    Granite3 = "granite3"
    Granite31 = "granite3.1"
    Granite32 = "granite3.2"
    Granite33 = "granite3.3"
