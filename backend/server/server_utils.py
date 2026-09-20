import asyncio
import json
import os
import re
import secrets
import time
import shutil
import traceback
from typing import Awaitable, Dict, List, Any
from fastapi.responses import JSONResponse, FileResponse
from argus.document.document import DocumentLoader
from argus import Argus
# 本模块会以两个不同的包名被导入：`backend.server.server_utils`（main.py／
# Procfile 入口）与 `server.server_utils`（backend/server/app.py 把 backend/ 塞进了
# sys.path）。只有前者能解析出 `backend.utils`，所以这里退回到裸模块名。
try:
    from backend.utils import write_md_to_word, write_text_to_md
except ImportError:  # pragma: no cover - 历史遗留的 sys.path 垫片导入
    from utils import write_md_to_word, write_text_to_md
from pathlib import Path
from datetime import datetime
from fastapi import HTTPException
import logging

from .multi_agent_runner import run_multi_agent_task
from .rate_limit import build_limiter, client_key

# 导入 chat agent
try:
    import sys
    backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from chat.chat import ChatAgentWithMemory
except ImportError:
    ChatAgentWithMemory = None

logger = logging.getLogger(__name__)

class CustomLogsHandler:
    """捕获研究过程流式日志的自定义 handler"""
    def __init__(self, websocket, task: str):
        self.logs = []
        self.websocket = websocket
        sanitized_filename = sanitize_filename(f"task_{int(time.time())}_{task}")
        self.log_file = os.path.join("outputs", f"{sanitized_filename}.json")
        self.timestamp = datetime.now().isoformat()
        # 用元数据初始化日志文件
        os.makedirs("outputs", exist_ok=True)
        with open(self.log_file, 'w') as f:
            json.dump({
                "timestamp": self.timestamp,
                "events": [],
                "content": {
                    "query": "",
                    "sources": [],
                    "context": [],
                    "report": "",
                    "costs": 0.0
                }
            }, f, indent=2)

    async def send_json(self, data: Dict[str, Any]) -> None:
        """保存日志数据，并发送给 websocket"""
        # 发给 websocket 以便实时展示
        if self.websocket:
            await self.websocket.send_json(data)
            
        # 读取当前的日志文件
        with open(self.log_file, 'r') as f:
            log_data = json.load(f)
            
        # 按数据类型更新对应的区块
        if data.get('type') == 'logs':
            log_data['events'].append({
                "timestamp": datetime.now().isoformat(),
                "type": "event",
                "data": data
            })
        else:
            # 其他类型的数据更新到 content 区块
            log_data['content'].update(data)
            
        # 写回更新后的日志文件
        with open(self.log_file, 'w') as f:
            json.dump(log_data, f, indent=2)


class Researcher:
    def __init__(self, query: str, report_type: str = "research_report"):
        self.query = query
        self.report_type = report_type
        # 为本次研究任务生成唯一 ID
        self.research_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(query)}"
        # 用该 research ID 初始化日志处理器
        self.logs_handler = CustomLogsHandler(None, self.research_id)
        self.researcher = Argus(
            query=query,
            report_type=report_type,
            websocket=self.logs_handler
        )

    async def research(self) -> dict:
        """执行研究，并返回生成文件的路径"""
        await self.researcher.conduct_research()
        report = await self.researcher.write_report()
        
        # 生成文件
        sanitized_filename = sanitize_filename(f"task_{int(time.time())}_{self.query}")
        file_paths = await generate_report_files(report, sanitized_filename)
        
        # 取出 CustomLogsHandler 创建的 JSON 日志路径
        json_relative_path = os.path.relpath(self.logs_handler.log_file)
        
        return {
            "output": {
                **file_paths,  # 包含 DOCX 与 MD 的路径
                "json": json_relative_path
            }
        }

def sanitize_filename(filename: str) -> str:
    """构造一个后缀无法由 query 推导出来的文件名。

    后缀原本是 ``md5(query)[:10]``，于是只要知道别人问了什么，就能拼出 ``/outputs``
    的 URL 去读他的报告——那个目录是不做任何鉴权直接对外提供的。改成随机后缀后，
    这个名字只有被回传路径的那个客户端才知道。

    注意 query 文本是有意不再使用的；调用方仍然按它期望的
    ``task_<timestamp>_<query>`` 形式把 query 传进来。
    """
    prefix, timestamp, *_ = filename.split('_')
    # 40 位的随机量
    token = secrets.token_hex(5)
    sanitized = f"{prefix}_{timestamp}_{token}"
    return re.sub(r"[^\w\s-]", "", sanitized).strip()


# 入站帧里可能携带的凭据字段。打日志之前先做脱敏：帧只截取前 50 个字符再记录，
# 但字段顺序由访客控制，所以光靠截断并不足以保证密钥不会落进 logs/app.log
#（那是个持久文件，在 Docker 下还做了 bind mount）。
_SECRET_FIELD_PATTERN = re.compile(
    r'("(?:api_keys|llm|tavily|tavily_api_key|api_key)"\s*:\s*)"[^"]*"'
)


def _redact_secrets(raw: str) -> str:
    """把原始帧里的凭据值替换成占位符。"""
    return _SECRET_FIELD_PATTERN.sub(r'\1"[redacted]"', raw)


# 两套额度，因为两者的形态不同：启动一次研究是一次昂贵的调用，而一轮 chat 是场
# 对话，其中的搜索只是偶尔触发。自带 Tavily key 的访客两者都会跳过。
_research_limiter = build_limiter("RATE_LIMIT_PER_HOUR", 3)
_chat_limiter = build_limiter("RATE_LIMIT_CHAT_PER_HOUR", 20)


async def handle_start_command(websocket, data: str, manager):
    json_data = json.loads(data[6:])
    (
        task,
        report_type,
        source_urls,
        document_urls,
        tone,
        headers,
        report_source,
        query_domains,
        mcp_enabled,
        mcp_strategy,
        mcp_configs,
        max_search_results,
        api_keys,
    ) = extract_command_data(json_data)

    if not task or not report_type:
        print("Error: Missing task or report_type")
        return

    llm_key = (api_keys or {}).get("llm")
    tavily_key = (api_keys or {}).get("tavily")

    # 无条件执行：本站不承接匿名流量。一次研究大约要花掉运营方 1.4 元，背后的搜索
    # 额度只会更紧，所以没有免费额度可以送。
    if not llm_key:
        await websocket.send_json({
            "type": "logs",
            "content": "error",
            "output": "请先填入你的 DeepSeek 密钥 —— 本站要求使用访客自己的密钥。",
        })
        return

    # 只有自带搜索 key 的访客之外的人才会动用到服务器的 Tavily 额度，所以也只对
    # 他们限流。
    if not tavily_key:
        allowed, retry_after = await _research_limiter.check(client_key(websocket))
        if not allowed:
            minutes = max(1, (retry_after + 59) // 60)
            await websocket.send_json({
                "type": "logs",
                "content": "error",
                "output": (
                    f"请求过于频繁。本站的搜索额度有限，请约 {minutes} 分钟后再试；"
                    "填入你自己的 Tavily 密钥即可解除此限制。"
                ),
            })
            return

    # 用 websocket 与 task 创建日志处理器
    logs_handler = CustomLogsHandler(websocket, task)
    # 用 query 初始化日志内容
    await logs_handler.send_json({
        "query": task,
        "sources": [],
        "context": [],
        "report": ""
    })

    sanitized_filename = sanitize_filename(f"task_{int(time.time())}_{task}")

    report = await manager.start_streaming(
        task,
        report_type,
        report_source,
        source_urls,
        document_urls,
        tone,
        websocket,
        headers,
        query_domains,
        mcp_enabled,
        mcp_strategy,
        mcp_configs,
        max_search_results,
        api_keys=api_keys,
    )
    report = str(report)
    file_paths = await generate_report_files(report, sanitized_filename)
    # 把 JSON 日志路径也加进 file_paths
    file_paths["json"] = os.path.relpath(logs_handler.log_file)
    await send_file_paths(websocket, file_paths)


async def handle_human_feedback(data: str):
    feedback_data = json.loads(data[14:])  # 去掉 "human_feedback" 前缀
    print(f"Received human feedback: {feedback_data}")
    # TODO: 补上把反馈转给对应 agent 或更新研究状态的逻辑


async def handle_chat_command(websocket, data: str):
    """处理来自 WebSocket 的 chat 命令。"""
    try:
        # 解析 chat 数据——格式为 "chat {json_data}"
        json_str = data[5:].strip()  # 去掉 "chat " 前缀
        chat_data = json.loads(json_str)
        
        message = chat_data.get("message", "")
        report = chat_data.get("report", "")
        messages = chat_data.get("messages", [])
        api_keys = chat_data.get("api_keys") or {}

        # 只给了 message 的话，转成 messages 格式
        if message and not messages:
            messages = [{"role": "user", "content": message}]

        if not messages:
            await websocket.send_json({
                "type": "chat",
                "content": "No message provided.",
                "role": "assistant"
            })
            return

        # 检查 ChatAgentWithMemory 是否可用
        if ChatAgentWithMemory is None:
            await websocket.send_json({
                "type": "chat",
                "content": "Chat functionality is not available. Please check the server configuration.",
                "role": "assistant"
            })
            return

        # 与研究同一条规则：没有访客 key 就不提供服务。否则 chat 会成为一条白嫖
        # 运营方余额与搜索额度的通道。
        if not api_keys.get("llm"):
            await websocket.send_json({
                "type": "chat",
                "content": "请先填入你的 DeepSeek 密钥 —— 本站要求使用访客自己的密钥。",
                "role": "assistant"
            })
            return

        # 动用本站 Tavily 额度的对话轮次，与研究启动分开计额度。自带 key 的访客花
        # 自己的，自然跳过这一步。
        if not api_keys.get("tavily"):
            allowed, retry_after = await _chat_limiter.check(client_key(websocket))
            if not allowed:
                minutes = max(1, (retry_after + 59) // 60)
                await websocket.send_json({
                    "type": "chat",
                    "content": (
                        f"对话过于频繁。本站的搜索额度有限，请约 {minutes} 分钟后再试；"
                        "填入你自己的 Tavily 密钥即可解除此限制。"
                    ),
                    "role": "assistant"
                })
                return

        # 带着报告上下文创建 chat agent
        chat_agent = ChatAgentWithMemory(
            report=report,
            config_path="default",
            headers=None,
            api_keys=api_keys,
        )
        
        # 处理这次 chat
        response_content, tool_calls_metadata = await chat_agent.chat(messages, websocket)
        
        # 通过 WebSocket 把回复发回去
        await websocket.send_json({
            "type": "chat",
            "content": response_content,
            "role": "assistant",
            "metadata": {
                "tool_calls": tool_calls_metadata
            } if tool_calls_metadata else None
        })
        
        logger.info(f"Chat response sent successfully")
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse chat data: {e}")
        await websocket.send_json({
            "type": "chat",
            "content": f"Error: Invalid message format - {str(e)}",
            "role": "assistant"
        })
    except Exception as e:
        logger.error(f"Error handling chat command: {e}\n{traceback.format_exc()}")
        await websocket.send_json({
            "type": "chat",
            "content": f"Error processing your message: {str(e)}",
            "role": "assistant"
        })

async def generate_report_files(report: str, filename: str) -> Dict[str, str]:
    docx_path = await write_md_to_word(report, filename)
    md_path = await write_text_to_md(report, filename)
    return {"docx": docx_path, "md": md_path}


async def send_file_paths(websocket, file_paths: Dict[str, str]):
    await websocket.send_json({"type": "path", "output": file_paths})


def get_config_dict(
    langchain_api_key: str, openai_api_key: str, tavily_api_key: str,
    google_api_key: str, google_cx_key: str, bing_api_key: str,
    searchapi_api_key: str, serpapi_api_key: str, serper_api_key: str, searx_url: str
) -> Dict[str, str]:
    return {
        "LANGCHAIN_API_KEY": langchain_api_key or os.getenv("LANGCHAIN_API_KEY", ""),
        "OPENAI_API_KEY": openai_api_key or os.getenv("OPENAI_API_KEY", ""),
        "TAVILY_API_KEY": tavily_api_key or os.getenv("TAVILY_API_KEY", ""),
        "GOOGLE_API_KEY": google_api_key or os.getenv("GOOGLE_API_KEY", ""),
        "GOOGLE_CX_KEY": google_cx_key or os.getenv("GOOGLE_CX_KEY", ""),
        "BING_API_KEY": bing_api_key or os.getenv("BING_API_KEY", ""),
        "SEARCHAPI_API_KEY": searchapi_api_key or os.getenv("SEARCHAPI_API_KEY", ""),
        "SERPAPI_API_KEY": serpapi_api_key or os.getenv("SERPAPI_API_KEY", ""),
        "SERPER_API_KEY": serper_api_key or os.getenv("SERPER_API_KEY", ""),
        "SEARX_URL": searx_url or os.getenv("SEARX_URL", ""),
        "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2", "true"),
        "DOC_PATH": os.getenv("DOC_PATH", "./my-docs"),
        "RETRIEVER": os.getenv("RETRIEVER", "")
    }


def update_environment_variables(config: Dict[str, str]):
    for key, value in config.items():
        os.environ[key] = value


async def handle_file_upload(file, DOC_PATH: str) -> Dict[str, str]:
    file_path = os.path.join(DOC_PATH, os.path.basename(file.filename))
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    print(f"File uploaded to {file_path}")

    document_loader = DocumentLoader(DOC_PATH)
    await document_loader.load()

    return {"filename": file.filename, "path": file_path}


async def handle_file_deletion(filename: str, DOC_PATH: str) -> JSONResponse:
    file_path = os.path.join(DOC_PATH, os.path.basename(filename))
    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"File deleted: {file_path}")
        return JSONResponse(content={"message": "File deleted successfully"})
    else:
        print(f"File not found: {file_path}")
        return JSONResponse(status_code=404, content={"message": "File not found"})


async def execute_multi_agents(manager) -> Any:
    websocket = manager.active_connections[0] if manager.active_connections else None
    if websocket:
        report = await run_multi_agent_task("Is AI in a hype cycle?", websocket, stream_output)
        return {"report": report}
    else:
        return JSONResponse(status_code=400, content={"message": "No active WebSocket connection"})


async def handle_websocket_communication(websocket, manager):
    running_task: asyncio.Task | None = None

    def run_long_running_task(awaitable: Awaitable) -> asyncio.Task:
        async def safe_run():
            try:
                await awaitable
            except asyncio.CancelledError:
                logger.info("Task cancelled.")
                raise
            except Exception as e:
                logger.error(f"Error running task: {e}\n{traceback.format_exc()}")
                await websocket.send_json(
                    {
                        "type": "logs",
                        "content": "error",
                        "output": f"Error: {e}",
                    }
                )

        return asyncio.create_task(safe_run())

    try:
        while True:
            try:
                data = await websocket.receive_text()
                preview = _redact_secrets(data)
                logger.info(f"Received WebSocket message: {preview[:50]}..." if len(preview) > 50 else preview)
                
                if data == "ping":
                    await websocket.send_text("pong")
                elif running_task and not running_task.done():
                    # 已有任务在跑，新请求直接丢弃
                    logger.warning(
                        f"Received request while task is already running. Request data preview: {preview[: min(20, len(preview))]}..."
                    )
                    await websocket.send_json(
                        {
                            "type": "logs",
                            "content": "warning",
                            "output": "Task already running. Please wait.",
                        }
                    )
                # 先去空白再用 startswith 判断，让命令识别更统一
                elif data.strip().startswith("start"):
                    logger.info(f"Processing start command")
                    running_task = run_long_running_task(
                        handle_start_command(websocket, data, manager)
                    )
                elif data.strip().startswith("human_feedback"):
                    logger.info(f"Processing human_feedback command")
                    running_task = run_long_running_task(handle_human_feedback(data))
                elif data.strip().startswith("chat"):
                    logger.info(f"Processing chat command")
                    running_task = run_long_running_task(handle_chat_command(websocket, data))
                else:
                    error_msg = f"Error: Unknown command or not enough parameters provided. Received: '{preview[:100]}...'" if len(preview) > 100 else f"Error: Unknown command or not enough parameters provided. Received: '{preview}'"
                    logger.error(error_msg)
                    print(error_msg)
                    await websocket.send_json({
                        "type": "error",
                        "content": "error",
                        "output": "Unknown command received by server"
                    })
            except Exception as e:
                logger.error(f"WebSocket error: {str(e)}\n{traceback.format_exc()}")
                print(f"WebSocket error: {e}")
                break
    finally:
        if running_task and not running_task.done():
            running_task.cancel()

def extract_command_data(json_data: Dict) -> tuple:
    return (
        json_data.get("task"),
        json_data.get("report_type"),
        json_data.get("source_urls"),
        json_data.get("document_urls"),
        json_data.get("tone"),
        json_data.get("headers", {}),
        json_data.get("report_source"),
        json_data.get("query_domains", []),
        json_data.get("mcp_enabled", False),
        json_data.get("mcp_strategy", "fast"),
        json_data.get("mcp_configs", []),
        json_data.get("max_search_results"),
        json_data.get("api_keys", {}),
    )
