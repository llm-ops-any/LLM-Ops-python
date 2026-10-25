#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : stream_adapter.py
@Desc    : 大语言模型流式输出适配层

背景（不同平台/模型的报文形态差异）：
    - OpenAI / 多数中转平台：tool_calls 直接出现在 chunk 中，可能在首包，也可能在尾包；
    - DeepSeek 系列：先流式输出一段铺垫文本（如“我这就帮你查查”），随后才返回 tool_calls；
    - 通义千问：部分版本把工具调用以 <tool_call>{...}</tool_call> 文本形式返回；
    - Ollama：工具调用在最后一个 chunk 一次性返回；
    - 推理模型：额外返回 reasoning_content 字段，不能计入答案。

处理策略：
    1. 通用处理优先：所有模型先走 DefaultStreamAdapter，判定“本轮是工具调用还是最终答案”
       一律以【整段输出】为准（accumulated tool_calls），绝不依据首个 chunk 定性；
    2. 差异化适配后置：仅当某平台/模型确实存在报文差异时，在 providers.py 中新增适配器，
       并通过 PROVIDER_ADAPTERS / MODEL_ADAPTER_RULES 登记，Agent 节点逻辑保持不变；
    3. 可通过模型配置 metadata.stream_adapter 或环境变量 LLM_STREAM_ADAPTER 强制指定适配器，
       便于线上快速切换排查。
"""
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StreamEvent(str, Enum):
    """流式输出归一化后的事件类型"""
    MESSAGE = "message"  # 面向用户的答案文本
    THOUGHT = "thought"  # 推理/工具调用（不进入答案）


@dataclass
class StreamSignal:
    """流式输出归一化信号"""
    event: StreamEvent
    content: str = ""


class BaseStreamAdapter:
    """流式输出适配器基类（通用处理，适用于任意平台/模型）"""

    # 适配器名字，用于日志与 metadata.stream_adapter 覆盖
    name: str = "default"
    # 是否把流式文本先缓存，确认本轮没有工具调用后再统一输出。
    # 关闭(默认)时：文本边生成边输出，遇到工具调用就停止输出答案(保留“稍等”体验)
    buffer_preamble: bool = False
    # 是否把 reasoning_content 计入思考内容（不进入答案）
    reasoning_as_thought: bool = True

    def __init__(self, provider: str = "", model: str = "") -> None:
        self.provider = provider
        self.model = model
        self._buffer: list[str] = []
        self._reasoning: list[str] = []
        self._tool_call_seen = False
        self._text_seen = False
        self.preamble_detected = False
        self.tool_calls: list[dict] = []

    # ------------------------------------------------------------------ 报文提取
    def extract_text(self, chunk: Any) -> str:
        """提取一个 chunk 中的文本内容（兼容多模态 list 结构）"""
        content = getattr(chunk, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text") or "")
            return "".join(parts)
        return ""

    def extract_tool_calls(self, chunk: Any) -> list[dict]:
        """提取一个 chunk 中的工具调用（仅用于判断“本轮是否出现工具调用”）"""
        calls = list(getattr(chunk, "tool_calls", None) or [])
        if calls:
            return calls

        # 兜底：部分平台走 OpenAI 老协议的 function_call 字段
        additional = getattr(chunk, "additional_kwargs", None) or {}
        function_call = additional.get("function_call")
        if function_call:
            return [{
                "id": "",
                "type": "tool_call",
                "name": function_call.get("name") or "",
                "args": function_call.get("arguments") or {},
            }]
        return []

    def extract_reasoning(self, chunk: Any) -> str:
        """提取推理内容（推理模型可能返回 reasoning_content/reasoning 字段）"""
        additional = getattr(chunk, "additional_kwargs", None) or {}
        reasoning = (
                additional.get("reasoning_content")
                or additional.get("reasoning")
                or ""
        )
        return reasoning if isinstance(reasoning, str) else ""

    # ------------------------------------------------------------------ 文本/工具清洗
    def normalize_text(self, text: str) -> str:
        """清洗平台特有的文本标记，默认为原文"""
        return text

    def normalize_tool_name(self, name: str) -> str:
        """规范化工具名，去掉平台可能追加的前缀/标记"""
        name = (name or "").strip().strip('"\'')
        for prefix in ("functions.", "function.", "tools.", "tool."):
            if name.startswith(prefix):
                name = name[len(prefix):]
        for tag in ("<|python_tag|>", "<|eom_id|>", "<tool_call>", "</tool_call>"):
            name = name.replace(tag, "")
        return name.strip()

    def normalize_tool_args(self, args: Any) -> dict:
        """规范化工具参数，字符串形式的 JSON 统一转成字典"""
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            args = args.strip()
            if not args or args == "null":
                return {}
            try:
                parsed = json.loads(args)
                return parsed if isinstance(parsed, dict) else {"value": parsed}
            except Exception:
                return {}
        return {}

    def clean_tool_calls(self, gathered: Any) -> list[dict]:
        """基于整段输出清洗工具调用列表（决定本轮是否为工具调用轮）"""
        raw_calls = list(getattr(gathered, "tool_calls", None) or [])
        cleaned: list[dict] = []
        for index, call in enumerate(raw_calls):
            name = self.normalize_tool_name(call.get("name") or "")
            if not name:
                continue
            cleaned.append({
                "id": call.get("id") or f"call_{index}",
                "type": call.get("type") or "tool_call",
                "name": name,
                "args": self.normalize_tool_args(call.get("args")),
            })
        return cleaned

    def apply_tool_calls(self, gathered: Any, tool_calls: list[dict]) -> Any:
        """把清洗后的工具调用写回消息，保证 _tools_node 能用名字匹配到工具"""
        raw_calls = list(getattr(gathered, "tool_calls", None) or [])
        if raw_calls == tool_calls:
            return gathered
        try:
            return gathered.copy(update={"tool_calls": tool_calls})
        except Exception:
            try:
                gathered.tool_calls = tool_calls
            except Exception:
                logging.exception("流式适配器回写工具调用失败, adapter=%(adapter)s", {"adapter": self.name})
            return gathered

    # ------------------------------------------------------------------ 状态机
    def feed(self, chunk: Any) -> list[StreamSignal]:
        """处理单个 chunk，返回需要立即推送的事件"""
        signals: list[StreamSignal] = []

        # 1.记录推理内容（不进入答案）
        reasoning = self.extract_reasoning(chunk)
        if reasoning:
            self._reasoning.append(reasoning)

        # 2.本轮是否出现工具调用（出现后，后续文本都不再当作答案）
        if self.extract_tool_calls(chunk):
            if not self._tool_call_seen and self._text_seen:
                self.preamble_detected = True
            self._tool_call_seen = True

        # 3.提取并清洗文本
        text = self.normalize_text(self.extract_text(chunk))
        if not text:
            return signals
        self._text_seen = True

        # 4.工具调用轮的铺垫文本：直接丢弃，避免被拼进答案
        if self._tool_call_seen and self.buffer_preamble:
            return signals

        # 5.缓存模式：确认没有工具调用后再统一输出
        if self.buffer_preamble:
            self._buffer.append(text)
            return signals

        signals.append(StreamSignal(StreamEvent.MESSAGE, text))
        return signals

    def finish(self, gathered: Any) -> tuple[list[StreamSignal], bool]:
        """整段输出结束，返回剩余事件以及本轮是否为工具调用轮"""
        # 1.以整段输出为准判定本轮类型
        tool_calls = self.clean_tool_calls(gathered)
        has_tool_calls = len(tool_calls) > 0
        self.tool_calls = tool_calls

        # 2.缓存模式：没有工具调用才把缓存的文本一次性输出
        signals: list[StreamSignal] = []
        if self.buffer_preamble:
            if has_tool_calls:
                self._buffer.clear()
            elif self._buffer:
                signals.append(StreamSignal(StreamEvent.MESSAGE, "".join(self._buffer)))
                self._buffer.clear()

        # 3.输出适配日志：出现“先文本后工具调用”时用info(需调低日志级别可见)，便于发现
        #   需要新增适配的平台/模型；普通轮次用debug，避免刷屏。
        log_payload = {
            "adapter": self.name, "provider": self.provider, "model": self.model,
            "has_tool_calls": has_tool_calls, "preamble": self.preamble_detected,
            "reasoning": len("".join(self._reasoning)),
        }
        if self.preamble_detected:
            logging.info(
                "检测到“先文本后工具调用”形态, adapter=%(adapter)s, provider=%(provider)s, model=%(model)s, "
                "has_tool_calls=%(has_tool_calls)s, reasoning_len=%(reasoning)d", log_payload,
            )
        else:
            logging.debug("流式适配器完成, 适配信息: %(payload)s", {"payload": log_payload})

        return signals, has_tool_calls


class DefaultStreamAdapter(BaseStreamAdapter):
    """通用适配器，所有平台/模型的默认实现"""
    name = "default"


def _build_registry() -> dict[str, type[BaseStreamAdapter]]:
    """构建适配器注册表（延迟导入，避免循环依赖）"""
    from .providers import (
        DeepSeekStreamAdapter,
        MoonshotStreamAdapter,
        OllamaStreamAdapter,
        OpenAIStreamAdapter,
        TongyiStreamAdapter,
        UinoStreamAdapter,
    )

    return {
        "default": DefaultStreamAdapter,
        "openai": OpenAIStreamAdapter,
        "uino": UinoStreamAdapter,
        "deepseek": DeepSeekStreamAdapter,
        "tongyi": TongyiStreamAdapter,
        "qwen": TongyiStreamAdapter,
        "moonshot": MoonshotStreamAdapter,
        "ollama": OllamaStreamAdapter,
    }


# 平台（provider）适配优先
PROVIDER_ADAPTERS: dict[str, str] = {
    "openai": "openai",
    "uino": "uino",
    "deepseek": "deepseek",
    "tongyi": "tongyi",
    "moonshot": "moonshot",
    "ollama": "ollama",
}

# 模型名前缀适配（平台为中转聚合平台时，按具体模型名再适配一层）
MODEL_ADAPTER_RULES: tuple[tuple[str, str], ...] = (
    ("deepseek", "deepseek"),
    ("qwq", "deepseek"),
    ("qwen", "tongyi"),
    ("tongyi", "tongyi"),
    ("moonshot", "moonshot"),
    ("kimi", "moonshot"),
    ("ollama", "ollama"),
)

# 环境变量强制指定适配器，便于线上快速切换排查
ADAPTER_ENV_KEY = "LLM_STREAM_ADAPTER"


def get_stream_adapter(llm: Any) -> BaseStreamAdapter:
    """根据大语言模型的平台/模型信息获取流式适配器（每次调用返回新实例）"""
    import logging as _logging

    registry = _build_registry()
    metadata = getattr(llm, "metadata", None) or {}
    provider = str(metadata.get("provider") or "").lower()
    model = str(metadata.get("model") or getattr(llm, "model_name", "") or "").lower()

    # 1.优先级：模型元数据强制指定 > 环境变量 > 平台 > 模型名前缀 > 通用
    adapter_name: Optional[str] = None
    forced = str(metadata.get("stream_adapter") or os.environ.get(ADAPTER_ENV_KEY) or "").lower()
    if forced in registry:
        adapter_name = forced
    elif provider in PROVIDER_ADAPTERS:
        adapter_name = PROVIDER_ADAPTERS[provider]
        # 中转聚合平台按具体模型名再适配一层（如 uino 上的 deepseek-v4-flash）
        if adapter_name == "uino":
            for prefix, model_adapter in MODEL_ADAPTER_RULES:
                if model.startswith(prefix):
                    adapter_name = model_adapter
                    break
    else:
        for prefix, model_adapter in MODEL_ADAPTER_RULES:
            if model.startswith(prefix):
                adapter_name = model_adapter
                break

    adapter_class = registry.get(adapter_name or "default", DefaultStreamAdapter)
    _logging.debug(
        "流式适配器选择, adapter=%(adapter)s, provider=%(provider)s, model=%(model)s",
        {"adapter": adapter_class.name, "provider": provider, "model": model},
    )
    return adapter_class(provider=provider, model=model)
