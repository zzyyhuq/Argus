import logging
import json
import os
from datetime import datetime
from pathlib import Path

class JSONResearchHandler:
    def __init__(self, json_file):
        self.json_file = json_file
        self.research_data = {
            "timestamp": datetime.now().isoformat(),
            "events": [],
            "content": {
                "query": "",
                "sources": [],
                "context": [],
                "report": "",
                "costs": 0.0
            }
        }

    def log_event(self, event_type: str, data: dict):
        self.research_data["events"].append({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data
        })
        self._save_json()

    def update_content(self, key: str, value):
        self.research_data["content"][key] = value
        self._save_json()

    def _save_json(self):
        with open(self.json_file, 'w') as f:
            json.dump(self.research_data, f, indent=2)

def setup_research_logging():
    # 若 logs 目录不存在则创建
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # 生成日志文件用的时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 拼出日志文件路径
    log_file = logs_dir / f"research_{timestamp}.log"
    json_file = logs_dir / f"research_{timestamp}.json"
    
    # 为研究日志配置文件 handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    # 取出 research logger 并配置
    research_logger = logging.getLogger('research')
    research_logger.setLevel(logging.INFO)
    
    # 清掉已有 handler，避免重复输出
    research_logger.handlers.clear()
    
    # 挂上文件 handler
    research_logger.addHandler(file_handler)
    
    # 再挂一个 stream handler 用于控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    research_logger.addHandler(console_handler)
    
    # 关闭向 root logger 的传播，避免同一行日志出现两次
    research_logger.propagate = False
    
    # 创建 JSON handler
    json_handler = JSONResearchHandler(json_file)
    
    return str(log_file), str(json_file), research_logger, json_handler

def get_research_logger():
    return logging.getLogger('research')

def get_json_handler():
    return getattr(logging.getLogger('research'), 'json_handler', None)
