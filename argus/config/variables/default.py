from .base import BaseConfig

DEFAULT_CONFIG: BaseConfig = {
    "RETRIEVER": "tavily",
    "EMBEDDING": "dashscope:text-embedding-v3",
    "SIMILARITY_THRESHOLD": 0.42,
    "FAST_LLM": "openai:gpt-5.4-mini",
    "SMART_LLM": "openai:gpt-5.4",  # 支持生成长篇回复（2000 字以上）。
    "STRATEGIC_LLM": "openai:gpt-5.4",  # 用于规划的 reasoning 模型；可通过 REASONING_EFFORT 权衡速度与深度。
    # 输出 token 上限。对 reasoning 模型（默认的 gpt-5.x 系列）来说，这些值
    # 会映射到 max_completion_tokens，而该上限也把 reasoning token 计入 ——
    # 所以要在可见输出之外留出足够余量。
    "FAST_TOKEN_LIMIT": 6000,
    "SMART_TOKEN_LIMIT": 12000,
    "STRATEGIC_TOKEN_LIMIT": 8000,
    "BROWSE_CHUNK_MAX_LENGTH": 8192,
    "CURATE_SOURCES": False,
    "SUMMARY_TOKEN_LIMIT": 700,
    "TEMPERATURE": 0.4,
    "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "MAX_SEARCH_RESULTS_PER_QUERY": 5,
    "MEMORY_BACKEND": "local",
    "TOTAL_WORDS": 1200,
    "REPORT_FORMAT": "APA",
    "MAX_ITERATIONS": 3,
    "AGENT_ROLE": None,
    "SCRAPER": "bs",
    "MAX_SCRAPER_WORKERS": 15,
    "SCRAPER_RATE_LIMIT_DELAY": 0.0,  # 抓取请求之间的最小间隔秒数（0 表示不限流，用于配合 API 限流）
    "MAX_SUBTOPICS": 3,
    # 会以 "write the report in the following language: {LANGUAGE}" 的形式
    # 注入报告 prompt。只写 "chinese" 无法区分简体与繁体，取材自台湾/香港
    # 来源的报告会输出繁体字，因此这里把具体字形写清楚。
    "LANGUAGE": "Simplified Chinese (简体中文)",
    "REPORT_SOURCE": "web",
    "DOC_PATH": "./my-docs",
    "PROMPT_FAMILY": "default",
    "LLM_KWARGS": {},
    # DashScope 的那些坑（兼容 base URL、chunk_size、上下文长度校验）已在
    # Memory 内部设好默认值；只有需要覆盖时才在这里设置相应的键。
    "EMBEDDING_KWARGS": {},
    "VERBOSE": False,
    # 深度研究相关设置
    "DEEP_RESEARCH_BREADTH": 3,
    "DEEP_RESEARCH_DEPTH": 2,
    "DEEP_RESEARCH_CONCURRENCY": 4,
    
    # MCP retriever 相关设置
    "MCP_SERVERS": [],  # 预置的 MCP 服务器配置列表
    "MCP_AUTO_TOOL_SELECTION": True,  # 是否自动为查询挑选最合适的工具
    "MCP_ALLOWED_ROOT_PATHS": [],  # 允许访问本地文件的根路径列表
    "MCP_STRATEGY": "fast",  # MCP 执行策略："fast"、"deep"、"disabled"
    "REASONING_EFFORT": "medium",
}
