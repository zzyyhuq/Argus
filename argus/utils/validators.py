"""Argus 的 Pydantic 校验模型。"""

from typing import List

from pydantic import BaseModel, Field


class Subtopic(BaseModel):
    """表示单个研究子主题的模型。

    属性：
        task: 子主题任务的名称或描述。
    """
    task: str = Field(description="Task name", min_length=1)


class Subtopics(BaseModel):
    """表示一组研究子主题的模型。

    用于解析并校验 LLM 在研究规划阶段生成的子主题列表。

    属性：
        subtopics: Subtopic 对象列表。
    """
    subtopics: List[Subtopic] = []
