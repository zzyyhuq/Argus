import asyncio
from typing import List, Dict, Any
from ..config.config import Config
from ..utils.llm import create_chat_completion
from ..utils.logger import get_formatted_logger
from ..prompts import PromptFamily, get_prompt_by_report_type
from ..utils.enum import Tone

logger = get_formatted_logger()


async def write_report_introduction(
    query: str,
    context: str,
    agent_role_prompt: str,
    config: Config,
    websocket=None,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> str:
    """
    为报告生成引言。

    参数：
        query (str): 研究查询。
        context (str): 报告使用的上下文。
        role (str): agent 的角色。
        config (Config): 配置对象。
        websocket: 用于流式输出的 WebSocket 连接。
        cost_callback (callable, optional): 计算 LLM 花费的回调。
        prompt_family: prompt 家族

    返回：
        str: 生成好的引言。
    """
    try:
        introduction = await create_chat_completion(
            model=config.smart_llm_model,
            messages=[
                {"role": "system", "content": f"{agent_role_prompt}"},
                {"role": "user", "content": prompt_family.generate_report_introduction(
                    question=query,
                    research_summary=context,
                    language=config.language
                )},
            ],
            temperature=0.25,
            llm_provider=config.smart_llm_provider,
            stream=True,
            websocket=websocket,
            max_tokens=config.smart_token_limit,
            llm_kwargs=config.llm_kwargs,
            cost_callback=cost_callback,
            **kwargs
        )
        return introduction
    except Exception as e:
        logger.error(f"Error in generating report introduction: {e}")
    return ""


async def write_conclusion(
    query: str,
    context: str,
    agent_role_prompt: str,
    config: Config,
    websocket=None,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> str:
    """
    为报告撰写结论。

    参数：
        query (str): 研究查询。
        context (str): 报告使用的上下文。
        role (str): agent 的角色。
        config (Config): 配置对象。
        websocket: 用于流式输出的 WebSocket 连接。
        cost_callback (callable, optional): 计算 LLM 花费的回调。
        prompt_family: prompt 家族

    返回：
        str: 生成好的结论。
    """
    try:
        conclusion = await create_chat_completion(
            model=config.smart_llm_model,
            messages=[
                {"role": "system", "content": f"{agent_role_prompt}"},
                {
                    "role": "user",
                    "content": prompt_family.generate_report_conclusion(query=query,
                                                                        report_content=context,
                                                                        language=config.language),
                },
            ],
            temperature=0.25,
            llm_provider=config.smart_llm_provider,
            stream=True,
            websocket=websocket,
            max_tokens=config.smart_token_limit,
            llm_kwargs=config.llm_kwargs,
            cost_callback=cost_callback,
            **kwargs
        )
        return conclusion
    except Exception as e:
        logger.error(f"Error in writing conclusion: {e}")
    return ""


async def summarize_url(
    url: str,
    content: str,
    role: str,
    config: Config,
    websocket=None,
    cost_callback: callable = None,
    **kwargs
) -> str:
    """
    对某个 URL 的内容做摘要。

    参数：
        url (str): 要摘要的 URL。
        content (str): 该 URL 的内容。
        role (str): agent 的角色。
        config (Config): 配置对象。
        websocket: 用于流式输出的 WebSocket 连接。
        cost_callback (callable, optional): 计算 LLM 花费的回调。

    返回：
        str: 摘要后的内容。
    """
    try:
        summary = await create_chat_completion(
            model=config.smart_llm_model,
            messages=[
                {"role": "system", "content": f"{role}"},
                {"role": "user", "content": f"Summarize the following content from {url}:\n\n{content}"},
            ],
            temperature=0.25,
            llm_provider=config.smart_llm_provider,
            stream=True,
            websocket=websocket,
            max_tokens=config.smart_token_limit,
            llm_kwargs=config.llm_kwargs,
            cost_callback=cost_callback,
            **kwargs
        )
        return summary
    except Exception as e:
        logger.error(f"Error in summarizing URL: {e}")
    return ""


async def generate_draft_section_titles(
    query: str,
    current_subtopic: str,
    context: str,
    role: str,
    config: Config,
    websocket=None,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> List[str]:
    """
    为报告生成草稿章节标题。

    参数：
        query (str): 研究查询。
        context (str): 报告使用的上下文。
        role (str): agent 的角色。
        config (Config): 配置对象。
        websocket: 用于流式输出的 WebSocket 连接。
        cost_callback (callable, optional): 计算 LLM 花费的回调。
        prompt_family: prompt 家族

    返回：
        List[str]: 生成的章节标题列表。
    """
    try:
        section_titles = await create_chat_completion(
            model=config.smart_llm_model,
            messages=[
                {"role": "system", "content": f"{role}"},
                {"role": "user", "content": prompt_family.generate_draft_titles_prompt(
                    current_subtopic, query, context)},
            ],
            temperature=0.25,
            llm_provider=config.smart_llm_provider,
            stream=True,
            websocket=None,
            max_tokens=config.smart_token_limit,
            llm_kwargs=config.llm_kwargs,
            cost_callback=cost_callback,
            **kwargs
        )
        return section_titles.split("\n")
    except Exception as e:
        logger.error(f"Error in generating draft section titles: {e}")
    return []


async def generate_report(
    query: str,
    context,
    agent_role_prompt: str,
    report_type: str,
    tone: Tone,
    report_source: str,
    websocket,
    cfg,
    main_topic: str = "",
    existing_headers: list = [],
    relevant_written_contents: list = [],
    cost_callback: callable = None,
    custom_prompt: str = "", # 可以是用户配合上下文自行选择的任意 prompt
    headers=None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    available_images: list = None,
    **kwargs
):
    """
    生成最终报告

    参数：
        query:
        context:
        agent_role_prompt:
        report_type:
        websocket:
        tone:
        cfg:
        main_topic:
        existing_headers:
        relevant_written_contents:
        cost_callback:
        prompt_family: prompt 家族
        available_images: 要嵌入报告的预生成图片

    返回：
        report:

    """
    available_images = available_images or []
    generate_prompt = get_prompt_by_report_type(report_type, prompt_family)
    report = ""

    if report_type == "subtopic_report":
        content = f"{generate_prompt(query, existing_headers, relevant_written_contents, main_topic, context, report_format=cfg.report_format, tone=tone, total_words=cfg.total_words, language=cfg.language)}"
    elif custom_prompt:
        content = f"{custom_prompt}\n\nContext: {context}"
    else:
        content = f"{generate_prompt(query, context, report_source, report_format=cfg.report_format, tone=tone, total_words=cfg.total_words, language=cfg.language)}"
    
    # 若图片是预生成的，则追加可用图片的使用说明
    if available_images:
        # 只嵌入带可用 URL 的图片字典。调用方（以及不完整的 LLM 元数据）
        # 可能传入 None 行、非字典、或缺少 ``url`` 的字典；裸写 ``img['url']``
        # 会抛 KeyError/TypeError，直接中断整条报告撰写流程。
        image_lines = []
        for i, img in enumerate(available_images):
            if not isinstance(img, dict):
                continue
            url = img.get("url") or ""
            if not url:
                continue
            alt = img.get("title") or img.get("alt_text") or "Illustration"
            hint = img.get("section_hint") or "General"
            image_lines.append(
                f"- Image {len(image_lines)+1}: ![{alt}]({url}) - {hint}"
            )
        if not image_lines:
            images_info = ""
        else:
            images_info = "\n".join(image_lines)
        if images_info:
            content += f"""

AVAILABLE IMAGES:
You have the following pre-generated images available. Embed them in relevant sections of your report using the exact markdown syntax provided:

{images_info}

Place each image on its own line after the relevant section header or paragraph. Use all available images where they add value to the content."""
    try:
        report = await create_chat_completion(
            model=cfg.smart_llm_model,
            messages=[
                {"role": "system", "content": f"{agent_role_prompt}"},
                {"role": "user", "content": content},
            ],
            temperature=0.35,
            llm_provider=cfg.smart_llm_provider,
            stream=True,
            websocket=websocket,
            max_tokens=cfg.smart_token_limit,
            llm_kwargs=cfg.llm_kwargs,
            cost_callback=cost_callback,
            **kwargs
        )
    except Exception:
        try:
            report = await create_chat_completion(
                model=cfg.smart_llm_model,
                messages=[
                    {"role": "user", "content": f"{agent_role_prompt}\n\n{content}"},
                ],
                temperature=0.35,
                llm_provider=cfg.smart_llm_provider,
                stream=True,
                websocket=websocket,
                max_tokens=cfg.smart_token_limit,
                llm_kwargs=cfg.llm_kwargs,
                cost_callback=cost_callback,
                **kwargs
            )
        except Exception as e:
            print(f"Error in generate_report: {e}")

    return report
