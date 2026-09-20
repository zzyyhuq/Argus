"""Argus 的配置管理。

本模块提供 Config 类，统一管理 Argus 的全部配置项，包括 LLM 服务商、
embedding、retriever 以及各类运行参数。
"""

import json
import json_repair
import os
import warnings
from typing import Any, Dict, List, Type, Union, get_args, get_origin

from argus.llm_provider.generic.base import ReasoningEfforts

from .variables.base import BaseConfig
from .variables.default import DEFAULT_CONFIG


class Config:
    """Argus 的配置管理器。

    负责从配置文件、环境变量与默认值中加载、解析并管理全部配置项。

    属性：
        CONFIG_DIR: 存放配置文件的目录。
        config_path: 配置文件的路径。
        llm_kwargs: LLM 的额外关键字参数。
        embedding_kwargs: embedding 的额外关键字参数。
    """

    CONFIG_DIR = os.path.join(os.path.dirname(__file__), "variables")

    def __init__(self, config_path: str | None = None):
        """初始化配置类。

        参数：
            config_path: 可选的 JSON 配置文件路径。
        """
        self.config_path = config_path
        self.llm_kwargs: Dict[str, Any] = {}
        self.embedding_kwargs: Dict[str, Any] = {}

        config_to_use = self.load_config(config_path)
        self._set_attributes(config_to_use)

        # 这里把 kwargs 字典复制一份私有副本。未指定配置文件时，load_config
        # 返回的就是 DEFAULT_CONFIG 本身而非副本，其内部嵌套的字典会被所有
        # Config 实例共享。而 Config 是每个 researcher 各建一份的，于是某次
        # 请求的写入（set_verbose 会写进 llm_kwargs，访客传入的 API key 也在
        # 这里）就会渗到之后的所有请求里。
        self.llm_kwargs = dict(self.llm_kwargs)
        self.embedding_kwargs = dict(self.embedding_kwargs)

        self._set_embedding_attributes()
        self._set_llm_attributes()
        self._handle_deprecated_attributes()
        if config_to_use['REPORT_SOURCE'] != 'web':
          self._set_doc_path(config_to_use)

        # MCP 支持相关配置
        self.mcp_servers = []  # MCP 服务器配置列表
        self.mcp_allowed_root_paths = []  # MCP 服务器允许使用的根路径

        # 从配置中读取
        if hasattr(self, 'mcp_servers'):
            self.mcp_servers = self.mcp_servers
        if hasattr(self, 'mcp_allowed_root_paths'):
            self.mcp_allowed_root_paths = self.mcp_allowed_root_paths

    def _set_attributes(self, config: Dict[str, Any]) -> None:
        """用配置字典设置各项配置属性。

        把环境变量与配置文件里的值合并，其中环境变量优先。

        参数：
            config: 配置键值对字典。
        """
        for key, value in config.items():
            env_value = os.getenv(key)
            if env_value is not None:
                value = self.convert_env_value(key, env_value, BaseConfig.__annotations__[key])
            setattr(self, key.lower(), value)

        # RETRIEVER 带默认值，单独处理
        retriever_env = os.environ.get("RETRIEVER", config.get("RETRIEVER", "tavily"))
        try:
            self.retrievers = self.parse_retrievers(retriever_env)
        except ValueError as e:
            print(f"Warning: {str(e)}. Defaulting to 'tavily' retriever.")
            self.retrievers = ["tavily"]

    def _set_embedding_attributes(self) -> None:
        """解析并设置 embedding 的服务商与模型属性。"""
        self.embedding_provider, self.embedding_model = self.parse_embedding(
            self.embedding
        )

    def _set_llm_attributes(self) -> None:
        """解析并设置各类 LLM 的服务商与模型属性。"""
        self.fast_llm_provider, self.fast_llm_model = self.parse_llm(self.fast_llm)
        self.smart_llm_provider, self.smart_llm_model = self.parse_llm(self.smart_llm)
        self.strategic_llm_provider, self.strategic_llm_model = self.parse_llm(self.strategic_llm)
        self.reasoning_effort = self.parse_reasoning_effort(os.getenv("REASONING_EFFORT"))

    def _handle_deprecated_attributes(self) -> None:
        """处理已废弃的配置项，并发出警告。"""
        _deprecation_warning = (
            "LLM_PROVIDER, FAST_LLM_MODEL and SMART_LLM_MODEL are deprecated and "
            "will be removed soon. Use FAST_LLM and SMART_LLM instead."
        )
        if os.getenv("LLM_PROVIDER") is not None:
            warnings.warn(_deprecation_warning, FutureWarning, stacklevel=2)
            self.fast_llm_provider = (
                os.environ["LLM_PROVIDER"] or self.fast_llm_provider
            )
            self.smart_llm_provider = (
                os.environ["LLM_PROVIDER"] or self.smart_llm_provider
            )
        if os.getenv("FAST_LLM_MODEL") is not None:
            warnings.warn(_deprecation_warning, FutureWarning, stacklevel=2)
            self.fast_llm_model = os.environ["FAST_LLM_MODEL"] or self.fast_llm_model
        if os.getenv("SMART_LLM_MODEL") is not None:
            warnings.warn(_deprecation_warning, FutureWarning, stacklevel=2)
            self.smart_llm_model = os.environ["SMART_LLM_MODEL"] or self.smart_llm_model

    def _set_doc_path(self, config: Dict[str, Any]) -> None:
        self.doc_path = config['DOC_PATH']
        if self.doc_path:
            try:
                self.validate_doc_path()
            except Exception as e:
                print(f"Warning: Error validating doc_path: {str(e)}. Using default doc_path.")
                self.doc_path = DEFAULT_CONFIG['DOC_PATH']

    @classmethod
    def load_config(cls, config_path: str | None) -> Dict[str, Any]:
        """按名称加载一份配置。"""
        config_path = config_path or os.environ.get("CONFIG_PATH")
        if not config_path:
            return DEFAULT_CONFIG

        # config_path = os.path.join(cls.CONFIG_DIR, config_path)
        if not os.path.exists(config_path):
            if config_path and config_path != "default":
                print(f"Warning: Configuration not found at '{config_path}'. Using default configuration.")
                if not config_path.endswith(".json"):
                    print(f"Do you mean '{config_path}.json'?")
            return DEFAULT_CONFIG

        with open(config_path, "r") as f:
            custom_config = json.load(f)

        # 与默认配置合并，确保所有键都存在
        merged_config = DEFAULT_CONFIG.copy()
        merged_config.update(custom_config)
        return merged_config

    @classmethod
    def list_available_configs(cls) -> List[str]:
        """列出所有可用的配置名称。"""
        configs = ["default"]
        for file in os.listdir(cls.CONFIG_DIR):
            if file.endswith(".json"):
                configs.append(file[:-5])  # 去掉 .json 后缀
        return configs

    def parse_retrievers(self, retriever_str: str) -> List[str]:
        """把 retriever 字符串解析成列表并逐个校验。"""
        from ..retrievers.utils import get_all_retriever_names
        
        retrievers = [retriever.strip()
                      for retriever in retriever_str.split(",")]
        valid_retrievers = get_all_retriever_names() or []
        invalid_retrievers = [r for r in retrievers if r not in valid_retrievers]
        if invalid_retrievers:
            raise ValueError(
                f"Invalid retriever(s) found: {', '.join(invalid_retrievers)}. "
                f"Valid options are: {', '.join(valid_retrievers)}."
            )
        return retrievers

    @staticmethod
    def parse_llm(llm_str: str | None) -> tuple[str | None, str | None]:
        """把 LLM 字符串解析成 (llm_provider, llm_model)。"""
        from argus.llm_provider.generic.base import _SUPPORTED_PROVIDERS

        if llm_str is None:
            return None, None
        try:
            llm_provider, llm_model = llm_str.split(":", 1)
            assert llm_provider in _SUPPORTED_PROVIDERS, (
                f"Unsupported {llm_provider}.\nSupported llm providers are: "
                + ", ".join(_SUPPORTED_PROVIDERS)
            )
            return llm_provider, llm_model
        except ValueError:
            raise ValueError(
                "Set SMART_LLM or FAST_LLM = '<llm_provider>:<llm_model>' "
                "Eg 'openai:gpt-4o-mini'"
            )

    @staticmethod
    def parse_reasoning_effort(reasoning_effort_str: str | None) -> str | None:
        """把 reasoning effort 字符串解析成 reasoning_effort。"""
        if reasoning_effort_str is None:
            return ReasoningEfforts.Medium.value
        if reasoning_effort_str not in [effort.value for effort in ReasoningEfforts]:
            raise ValueError(f"Invalid reasoning effort: {reasoning_effort_str}. Valid options are: {', '.join([effort.value for effort in ReasoningEfforts])}")
        return reasoning_effort_str

    @staticmethod
    def parse_embedding(embedding_str: str | None) -> tuple[str | None, str | None]:
        """把 embedding 字符串解析成 (embedding_provider, embedding_model)。"""
        from argus.memory.embeddings import _SUPPORTED_PROVIDERS

        if embedding_str is None:
            return None, None
        try:
            embedding_provider, embedding_model = embedding_str.split(":", 1)
            assert embedding_provider in _SUPPORTED_PROVIDERS, (
                f"Unsupported {embedding_provider}.\nSupported embedding providers are: "
                + ", ".join(_SUPPORTED_PROVIDERS)
            )
            return embedding_provider, embedding_model
        except ValueError:
            raise ValueError(
                "Set EMBEDDING = '<embedding_provider>:<embedding_model>' "
                "Eg 'openai:text-embedding-3-large'"
            )

    def validate_doc_path(self):
        """确保 doc_path 指向的目录存在"""
        os.makedirs(self.doc_path, exist_ok=True)

    @staticmethod
    def convert_env_value(key: str, env_value: str, type_hint: Type) -> Any:
        """依据类型提示，把环境变量的值转换成合适的类型。"""
        origin = get_origin(type_hint)
        args = get_args(type_hint)

        if origin is Union:
            # 处理 Union 类型（如 Union[str, None] / Optional[str]）。
            # 先判断 None 哨兵值，再尝试非 None 的分支：对于 Optional[str]，
            # 转成 str 永远不会抛异常，若先遍历 str 分支，none/null/"" →
            # None 这条路就永远走不到（见 issue #1899）。
            if type(None) in args and env_value.lower() in ("none", "null", ""):
                return None
            for arg in args:
                if arg is type(None):
                    continue
                try:
                    return Config.convert_env_value(key, env_value, arg)
                except ValueError:
                    continue
            raise ValueError(f"Cannot convert {env_value} to any of {args}")

        if type_hint is bool:
            return env_value.lower() in ("true", "1", "yes", "on")
        elif type_hint is int:
            return int(env_value)
        elif type_hint is float:
            return float(env_value)
        elif type_hint in (str, Any):
            return env_value
        elif type_hint is list or origin is list or origin is List:
            # 环境变量里的值常是手工改的（多余逗号、单引号）。
            # 裸 `list` 的 get_origin 为 None；typing.List[...] 的 origin 是 list。
            try:
                value = json_repair.loads(env_value)
            except Exception as exc:
                raise ValueError(f"Cannot convert {env_value} to list") from exc
            if not isinstance(value, list):
                raise ValueError(f"Cannot convert {env_value} to list")
            return value
        elif type_hint is dict:
            try:
                value = json_repair.loads(env_value)
            except Exception as exc:
                raise ValueError(f"Cannot convert {env_value} to dict") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Cannot convert {env_value} to dict")
            return value
        else:
            raise ValueError(f"Unsupported type {type_hint} for key {key}")


    def set_verbose(self, verbose: bool) -> None:
        """设置日志详细程度。"""
        self.llm_kwargs["verbose"] = verbose

    def get_mcp_server_config(self, name: str) -> dict:
        """
        获取某个 MCP 服务器的配置。
        
        参数：
            name (str): 要取配置的 MCP 服务器名称。
                
        返回：
            dict: 该服务器的配置；找不到时返回空字典。
        """
        if not name or not self.mcp_servers:
            return {}
        
        for server in self.mcp_servers:
            if isinstance(server, dict) and server.get("name") == name:
                return server
            
        return {}
