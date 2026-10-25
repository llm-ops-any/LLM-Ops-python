#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""网页搜索工具，优先使用360搜索、失败时回退必应，均无需API密钥且国内可直连"""
# TODO(搜索接入): 当前为HTML抓取实现，改版即失效且拿不到来源/发布时间/真实URL。
#  后续计划接入官方搜索API（火山豆包 / 阿里IQS / 百度千帆等），接口清单、选型判据、
#  落地步骤与验收标准见 docs/搜索API接入待办.md（2026-10-18 留存，张勇决定暂缓实施）。
import re
from typing import Any, Type

import requests
from bs4 import BeautifulSoup
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.tools import BaseTool

from internal.exception import FailException

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 360搜索结果中出现的站内聚合噪音摘要
NOISE_SNIPPETS = {"ai.so.com 反馈"}

# 摘要结尾常带「域名 反馈」这类站内标记，输出前清理掉
TAIL_NOISE_PATTERN = re.compile(r"\s*\S+\.(com|cn|net|org)(\S*)?\s*反馈\s*$")

# 360站内聚合入口（文库、图片、相关搜索）没有正文摘要，直接跳过
AGGREGATION_TITLE_KEYWORDS = ("360文库", "360图片", "其他人还搜")
AGGREGATION_LINK_KEYWORDS = ("wenku.so.com", "image.so.com")


class WebSearchArgsSchema(BaseModel):
    """网页搜索参数描述"""

    query: str = Field(description="需要检索查询的语句")


def _fetch_360(query: str, max_results: int) -> list[tuple[str, str, str]]:
    """抓取360搜索结果，返回(标题, 摘要, 链接)列表"""
    response = requests.get(
        "https://www.so.com/s",
        params={"q": query},
        headers={**BROWSER_HEADERS, "Referer": "https://www.so.com/"},
        timeout=15,
    )
    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, "lxml")
    results = []
    for block in soup.select("li.res-list"):
        title_node = block.select_one("h3 a")
        if title_node is None:
            continue

        title = title_node.get_text(" ", strip=True)
        if not title:
            continue

        link = title_node.get("href", "")
        if any(keyword in title for keyword in AGGREGATION_TITLE_KEYWORDS):
            continue
        if any(keyword in link for keyword in AGGREGATION_LINK_KEYWORDS):
            continue

        desc_node = block.select_one(".res-desc") or block.select_one(".res-rich")
        snippet = desc_node.get_text(" ", strip=True) if desc_node else ""
        if snippet in NOISE_SNIPPETS:
            snippet = ""
        snippet = TAIL_NOISE_PATTERN.sub("", snippet).strip()

        results.append((title, snippet, link))
        if len(results) >= max_results:
            break

    return results


def _fetch_bing(query: str, max_results: int) -> list[tuple[str, str, str]]:
    """抓取必应国内站搜索结果，作为360搜索的兜底"""
    response = requests.get(
        "https://cn.bing.com/search",
        params={"q": query},
        headers=BROWSER_HEADERS,
        timeout=15,
    )
    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, "lxml")
    results = []
    for block in soup.select("li.b_algo")[:max_results]:
        title_node = block.select_one("h2 a")
        if title_node is None:
            continue

        caption_node = block.select_one("p") or block.select_one(".b_caption")
        snippet = caption_node.get_text(" ", strip=True) if caption_node else ""
        results.append((title_node.get_text(" ", strip=True), snippet, title_node.get("href", "")))

    return results


class WebSearchTool(BaseTool):
    """网页搜索工具"""

    name = "web_search"
    description = (
        "网页搜索工具，无需API密钥且国内可直连。"
        "当你需要检索时事、商品、资料等互联网信息时可以使用该工具，该工具的输入是一个查询语句"
    )
    args_schema: Type[BaseModel] = WebSearchArgsSchema
    max_results: int = 8

    def _run(self, query: str, *args: Any, **kwargs: Any) -> str:
        """依次尝试360搜索与必应搜索并格式化结果"""
        results: list[tuple[str, str, str]] = []
        for fetcher in (_fetch_360, _fetch_bing):
            try:
                results = fetcher(query, self.max_results)
            except Exception:
                results = []
            if results:
                break

        if not results:
            raise FailException("网页搜索失败，请稍后重试")

        content = [f"网页搜索「{query}」结果如下："]
        for idx, (title, snippet, link) in enumerate(results, start=1):
            item = f"{idx}. {title}\n   摘要：{snippet or '无'}"
            # 说明：360返回的是带加密参数的站内跳转链接，对模型无参考价值且极占token，因此仅在直链时输出
            if link and "so.com/link" not in link:
                item += f"\n   链接：{link}"
            content.append(item)

        return "\n\n".join(content)


def web_search(**kwargs) -> BaseTool:
    """返回网页搜索的LangChain工具"""
    return WebSearchTool(**kwargs)
