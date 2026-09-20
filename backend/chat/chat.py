import logging
import os
import uuid
import json
from fastapi import WebSocket
from typing import List, Dict, Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import InMemoryVectorStore
from argus.memory import Memory
from argus.config.config import Config
from argus.utils.llm import create_chat_completion
from argus.utils.tools import create_chat_completion_with_tools, create_search_tool
try:
    from tavily import TavilyClient
except ImportError:  # chat 的联网搜索是可选依赖
    TavilyClient = None
from datetime import datetime

# 配置日志
# 获取 logger 实例
logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # 只输出到控制台
    ]
)

# 注意：LLM 客户端现在统一走 Argus 的 LLM 体系
# 因此所有已配置的服务商（OpenAI、Google Gemini、Anthropic 等）都受支持

def get_tools():
    """定义供 LLM function calling 使用的工具（主要面向 OpenAI 兼容的服务商）"""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "quick_search",
                "description": "Search for current events or online information when you need new knowledge that doesn't exist in the current context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    return tools

class ChatAgentWithMemory:
    def __init__(
        self,
        report: str,
        config_path="default",
        headers=None,
        vector_store=None,
        api_keys=None
    ):
        self.report = report
        self.headers = headers
        self.config = Config(config_path)

        # 访客为本次 chat 会话提供的凭据。Config 是每个实例各建一份，所以在这里
        # 注入只会影响当前请求。
        if api_keys and api_keys.get("llm"):
            self.config.llm_kwargs["api_key"] = api_keys["llm"]

        self.vector_store = vector_store
        self.retriever = None
        self.search_metadata = None

        # 初始化 Tavily 客户端（可选——只有拿到 API key 才创建）。
        # 访客自己的 key 优先，这样他的 chat 搜索计在自己账上，而不是消耗站点的
        # 额度。
        tavily_api_key = (api_keys or {}).get("tavily") or os.environ.get("TAVILY_API_KEY")
        if tavily_api_key and TavilyClient is not None:
            self.tavily_client = TavilyClient(api_key=tavily_api_key)
        else:
            self.tavily_client = None
            if TavilyClient is None:
                logger.warning("tavily package not installed - web search in chat will be disabled")
            else:
                logger.warning("TAVILY_API_KEY not set - web search in chat will be disabled")
        
        # 未提供 vector store 时，自行处理文档并创建
        if not self.vector_store and self.report:
            self._setup_vector_store()
        elif self.vector_store is not None and self.retriever is None:
            # 调用方可以直接注入 vector store；这里用受支持的 kwargs 建一个 retriever。
            try:
                self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 4})
            except TypeError:
                self.retriever = self.vector_store.as_retriever()
    
    def _setup_vector_store(self):
        """为文档检索建立 vector store"""
        # 把文档切块
        documents = self._process_document(self.report)
        if not documents:
            return
        
        # 生成唯一的 thread ID
        self.thread_id = str(uuid.uuid4())
        
        # 用 agent 的 config_path 建立 embedding 与 vector store。
        # embedding 的构造可能一开始就失败（例如 OPENAI_API_KEY 未设置时，OpenAI 的
        # embedding 在 init 阶段就抛异常），所以退回到"无 RAG／整篇报告"模式，而不是
        # 让这一轮 chat 直接不可用。
        cfg = self.config
        try:
            self.embedding = Memory(
                cfg.embedding_provider,
                cfg.embedding_model,
                **cfg.embedding_kwargs
            ).get_embeddings()

            # 创建 vector store 与 retriever
            self.vector_store = InMemoryVectorStore(self.embedding)
            self.vector_store.add_texts(documents)
            try:
                self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 4})
            except TypeError:
                # 较老的 langchain API 直接接受 k=；优先用 kwargs 形式。
                self.retriever = self.vector_store.as_retriever(k=4)
        except Exception as exc:  # noqa: BLE001 - embedding 失败不能拖垮 chat
            logger.warning(
                f"Vector store setup failed, using full report (no RAG): {exc}"
            )
            self.embedding = None
            self.vector_store = None
            self.retriever = None
        
    def _process_document(self, report):
        """把报告切分成块"""
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1024,
            chunk_overlap=20,
            length_function=len,
            is_separator_regex=False,
        )
        documents = text_splitter.split_text(report)
        return documents

    def quick_search(self, query):
        """用 Tavily 搜索最新信息"""
        try:
            # 检查 Tavily 客户端是否可用
            if self.tavily_client is None:
                logger.warning(f"Tavily client not available, skipping web search for: {query}")
                self.search_metadata = {
                    "query": query,
                    "sources": [],
                    "error": "Web search is disabled - TAVILY_API_KEY not configured"
                }
                return {
                    "error": "Web search is disabled - TAVILY_API_KEY not configured",
                    "results": []
                }
            
            logger.info(f"Performing web search for: {query}")
            results = self.tavily_client.search(query=query, max_results=5)
            
            # 保存搜索元数据，供前端使用
            self.search_metadata = {
                "query": query,
                "sources": [
                    {"title": result.get("title", ""), 
                     "url": result.get("url", ""),
                     "content": result.get("content", "")[:200] + "..." if len(result.get("content", "")) > 200 else result.get("content", "")}
                    for result in results.get("results", [])
                ]
            }
            
            return results
        except Exception as e:
            logger.error(f"Error performing web search: {str(e)}", exc_info=True)
            return {
                "error": str(e),
                "results": []
            }


    async def process_chat_completion(self, messages: List[Dict[str, str]]):
        """用已配置的 LLM 服务商处理 chat completion，并启用 tool calling 支持"""
        # 用工具函数创建搜索工具
        search_tool = create_search_tool(self.quick_search)
        
        # 走支持工具的 chat completion 工具函数
        response, tool_calls_metadata = await create_chat_completion_with_tools(
            messages=messages,
            tools=[search_tool],
            model=self.config.smart_llm_model,
            llm_provider=self.config.smart_llm_provider,
            llm_kwargs=self.config.llm_kwargs,
        )
        
        # 整理元数据，使其符合 chat 系统预期的格式
        processed_metadata = []
        for metadata in tool_calls_metadata:
            if metadata.get("tool") == "search_tool":
                # 从 args 里取出 query
                query = metadata.get("args", {}).get("query", "")
                
                # 再触发一次搜索以拿到元数据（搜索本身 LangChain 已经执行过了）
                if query:
                    self.quick_search(query)  # 这里会填充 self.search_metadata
                    
                processed_metadata.append({
                    "tool": "quick_search",
                    "query": query,
                    "search_metadata": self.search_metadata
                })
        
        return response, processed_metadata



    def _retrieve_context(self, user_message: str) -> str:
        """针对最新一条用户消息，返回检索到的最相关的报告片段。

        检索不可用时退回整篇报告，这样离线／没有 embedding 时 chat 依然可用。
        """
        if not self.retriever or not user_message:
            return self.report or ""
        try:
            docs = self.retriever.invoke(user_message)
        except Exception as exc:  # noqa: BLE001 - 检索失败不能拖垮 chat
            logger.warning(f"Report retrieval failed, using full report: {exc}")
            return self.report or ""
        chunks = []
        for doc in docs or []:
            content = getattr(doc, "page_content", None)
            if content is None and isinstance(doc, dict):
                content = doc.get("page_content") or doc.get("content")
            if content:
                chunks.append(str(content))
        if not chunks:
            return self.report or ""
        return "\n\n".join(chunks)

    async def chat(self, messages, websocket=None):
        """与已配置的 LLM 服务商对话（支持 OpenAI、Google Gemini、Anthropic 等）
        
        参数：
            messages: chat 消息列表，每条含 role 与 content
            websocket: 可选的 websocket，用于流式返回
        
        返回：
            tuple: (str: AI 回复内容, dict: 工具使用情况的元数据)
        """
        try:
            
            # 优先使用检索到的报告片段，而不是每轮都把整篇报告塞进上下文
            last_user = ""
            for msg in reversed(messages or []):
                if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content"):
                    last_user = str(msg.get("content"))
                    break
            report_context = self._retrieve_context(last_user)

            # 把报告上下文填进 system prompt
            system_prompt = f"""
            You are an autonomous research assistant, chatting with the user about a research report you produced earlier.
            Answer based on the given context and report.
            You must include citations to your answer based on the report.

            You may use the quick_search tool when the user asks about information that might require current data
            not found in the report, such as recent events, updated statistics, or news. If there's no report available,
            you can use the quick_search tool to find information online.

            You must respond in markdown format. You must make it readable with paragraphs, tables, etc when possible.
            Remember that you're answering in a chat not a report.

            You must respond in Simplified Chinese (简体中文).

            Assume the current time is: {datetime.now()}.

            Report: {report_context}

            """
            
            # 整理消息历史，作为 OpenAI 格式的输入
            formatted_messages = []
            
            # 先把 system 消息放进去
            formatted_messages.append({
                "role": "system", 
                "content": system_prompt
            })
            
            # 追加 user/assistant 消息历史——过滤掉无关字段
            for msg in messages:
                if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
                else:
                    logger.warning(f"Skipping message with missing role or content: {msg}")
            
            # 用已配置的 LLM 服务商处理这次 chat
            ai_message, tool_calls_metadata = await self.process_chat_completion(formatted_messages)
            
            # 回复为空时给一个兜底文案
            if not ai_message:
                logger.warning("No AI message content found in response, using fallback message")
                ai_message = "I apologize, but I couldn't generate a proper response. Please try asking your question again."
            
            logger.info(f"Generated response: {ai_message[:100]}..." if len(ai_message) > 100 else f"Generated response: {ai_message}")
            
            # 同时返回回复内容与工具使用情况的元数据
            return ai_message, tool_calls_metadata
            
        except Exception as e:
            logger.error(f"Error in chat: {str(e)}", exc_info=True)
            raise

    def get_context(self):
        """返回当前 chat 的上下文"""
        return self.report
