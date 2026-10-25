#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : providers.py
@Desc    : 各平台/模型的流式适配器

说明：
    1. 继承 BaseStreamAdapter 即可复用通用处理（以整段输出判定工具调用轮）；
    2. 只覆盖确实存在报文差异的方法，避免为“未知差异”提前写死逻辑；
    3. 新增平台适配只需在此定义类，并在 stream_adapter.py 的 PROVIDER_ADAPTERS /
       MODEL_ADAPTER_RULES 里登记一行。
"""
import json
import re

from .stream_adapter import BaseStreamAdapter


class OpenAIStreamAdapter(BaseStreamAdapter):
    """OpenAI 协议（tool_calls 在 chunk 中标准返回）"""
    name = "openai"


class UinoStreamAdapter(OpenAIStreamAdapter):
    """uino 统一中转平台（OpenAI 兼容协议，模型来自多个厂商）"""
    name = "uino"


class DeepSeekStreamAdapter(OpenAIStreamAdapter):
    """DeepSeek 系列

    报文差异：先流式输出一段铺垫文本（“我这就帮你查查”），随后才返回 tool_calls；
             推理模型还会额外返回 reasoning_content。
    处理：通用适配已能正确判定工具调用轮；此处只补充推理内容与文本清洗。
    """
    name = "deepseek"

    def normalize_text(self, text: str) -> str:
        """清理推理模型可能混入正文的特殊标记"""
        text = text.replace("<｜end▁of▁thinking｜>", "")
        return text


class MoonshotStreamAdapter(OpenAIStreamAdapter):
    """月之暗面（Kimi）

    报文差异：工具参数偶尔以字典而非 JSON 字符串返回，工具名可能带 functions. 前缀。
    """
    name = "moonshot"


class OllamaStreamAdapter(OpenAIStreamAdapter):
    """Ollama 本地模型

    报文差异：工具调用通常在最后一个 chunk 一次性返回，部分版本放在 additional_kwargs.tool_calls。
    """
    name = "ollama"

    def extract_tool_calls(self, chunk):
        calls = super().extract_tool_calls(chunk)
        if calls:
            return calls
        additional = getattr(chunk, "additional_kwargs", None) or {}
        raw_calls = additional.get("tool_calls") or []
        return [
            {
                "id": call.get("id") or "",
                "type": "tool_call",
                "name": (call.get("function") or {}).get("name") or call.get("name") or "",
                "args": (call.get("function") or {}).get("arguments") or call.get("args") or {},
            }
            for call in raw_calls
            if isinstance(call, dict)
        ]


class TongyiStreamAdapter(OpenAIStreamAdapter):
    """通义千问

    报文差异：部分版本把工具调用以 <tool_call>{"name":..,"arguments":..}</tool_call>
             的文本形式返回，需要从答案文本中剥离并解析成工具调用。
    """
    name = "tongyi"
    TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

    def normalize_text(self, text: str) -> str:
        """删除工具调用标记，避免被拼进答案"""
        text = self.TOOL_CALL_PATTERN.sub("", text)
        return text.replace("<tool_call>", "").replace("</tool_call>", "")

    def clean_tool_calls(self, gathered):
        calls = super().clean_tool_calls(gathered)
        if calls:
            return calls

        # 兜底：从整段文本中解析文本形态的工具调用
        content = self.extract_text(gathered)
        if not content or "<tool_call>" not in content:
            return calls

        parsed_calls = []
        for index, raw in enumerate(self.TOOL_CALL_PATTERN.findall(content)):
            try:
                data = json.loads(raw)
            except Exception:
                continue
            name = self.normalize_tool_name(str(data.get("name") or data.get("tool") or ""))
            if not name:
                continue
            args = data.get("arguments") or data.get("args") or {}
            parsed_calls.append({
                "id": str(data.get("id") or f"call_{index}"),
                "type": "tool_call",
                "name": name,
                "args": self.normalize_tool_args(args),
            })
        return parsed_calls
