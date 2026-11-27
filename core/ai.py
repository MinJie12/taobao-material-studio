# -*- coding: utf-8 -*-
"""本地优先的可插拔 AI 服务层。

基础图片处理不依赖 AI。未配置模型、模型不可用或请求失败时，调用方可以
继续使用本模块提供的本地规则结果。
"""
from __future__ import annotations

import re
from typing import Any

import requests

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


def normalize_settings(settings: dict | None) -> dict:
    value = dict(settings or {})
    value.setdefault("enabled", False)
    value.setdefault("provider", "ollama")
    value.setdefault("ollama_url", DEFAULT_OLLAMA_URL)
    value.setdefault("base_url", "")
    value.setdefault("api_key", "")
    value.setdefault("text_model", "")
    value.setdefault("vision_model", "")
    value.setdefault("timeout", 20)
    return value


def status(settings: dict | None) -> dict:
    cfg = normalize_settings(settings)
    provider = str(cfg.get("provider") or "ollama").lower()
    result = {
        "enabled": bool(cfg.get("enabled")),
        "provider": provider,
        "available": False,
        "mode": "fallback",
        "message": "未连接 AI，使用本地规则处理",
        "models": [],
    }
    if provider == "ollama":
        url = str(cfg.get("ollama_url") or DEFAULT_OLLAMA_URL).rstrip("/")
        try:
            response = requests.get(f"{url}/api/tags", timeout=3)
            response.raise_for_status()
            models = response.json().get("models", [])
            result.update({
                "available": True,
                "mode": "local",
                "message": "Ollama 本地模型可用",
                "models": [item.get("name") for item in models if item.get("name")],
            })
        except (OSError, ValueError, requests.RequestException):
            result["message"] = "Ollama 未连接，已回退到本地规则处理"
    elif cfg.get("enabled") and cfg.get("base_url"):
        result.update({"available": True, "mode": "remote", "message": "已配置 OpenAI 兼容接口"})
    return result


def complete(prompt: str, settings: dict | None, model: str = "") -> str:
    cfg = normalize_settings(settings)
    if not cfg.get("enabled"):
        return ""
    provider = str(cfg.get("provider") or "ollama").lower()
    chosen = model or str(cfg.get("text_model") or cfg.get("vision_model") or "")
    if not chosen:
        return ""
    timeout = max(1, min(float(cfg.get("timeout") or 20), 120))
    try:
        if provider == "ollama":
            url = str(cfg.get("ollama_url") or DEFAULT_OLLAMA_URL).rstrip("/")
            response = requests.post(
                f"{url}/api/generate",
                json={"model": chosen, "prompt": prompt, "stream": False},
                timeout=timeout,
            )
            response.raise_for_status()
            return str(response.json().get("response") or "")
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        headers = {"Content-Type": "application/json"}
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        response = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={"model": chosen, "messages": [{"role": "user", "content": prompt}]},
            timeout=timeout,
        )
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return str((choices[0].get("message") or {}).get("content") or "") if choices else ""
    except (OSError, ValueError, requests.RequestException):
        return ""


def _tokens(text: str) -> list[str]:
    values = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{1,20}", text or "")
    seen: set[str] = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result[:24]


def analyze_product(meta: dict, raw: dict | None = None) -> dict:
    title = str(meta.get("title") or "")
    category = str(meta.get("category") or "")
    attributes = meta.get("attributes") if isinstance(meta.get("attributes"), dict) else {}
    text = " ".join([title, category, *map(str, attributes.values())])
    image_count = sum(len(value) for value in (raw or {}).values() if isinstance(value, list))
    words = _tokens(text)
    return {
        "title": title,
        "category": category,
        "keywords": words,
        "sellingPoints": words[:6],
        "styleSuggestions": [
            {"id": "minimal", "name": "高级简约风", "description": "留白和中性配色，突出商品主体"},
            {"id": "natural", "name": "清新自然风", "description": "浅色背景和柔和对比，适合日常场景"},
            {"id": "scene", "name": "时尚场景风", "description": "用场景层次强化使用方式和消费人群"},
        ],
        "source": "local-rule",
        "imageCount": image_count,
        "needsMoreInfo": not bool(title or attributes),
    }


def parse_instruction(text: str) -> dict:
    value = str(text or "").strip()
    operations: list[dict[str, Any]] = []
    colors = {"米色": "#F4F0E8", "浅灰": "#F2F3F5", "灰色": "#E5E7EB", "白色": "#FFFFFF", "黑色": "#111827", "蓝色": "#EAF2FF", "绿色": "#EAF7EF", "粉色": "#FFF0F5", "橙色": "#FFF3E8"}
    color = re.search(r"(?:背景|底色|配色).*?(米色|浅灰|灰色|白色|黑色|蓝色|绿色|粉色|橙色)", value)
    if color:
        operations.append({"type": "set_background", "color": colors[color.group(1)]})
    scale = re.search(r"(?:主体|商品).*?(?:放大|增大|扩大)\s*(\d{1,3})?\s*%?", value)
    if scale:
        operations.append({"type": "scale_product", "percent": int(scale.group(1) or 10)})
    if re.search(r"(?:字体|文字).*?(?:统一|一致)", value):
        operations.append({"type": "unify_typography"})
    if re.search(r"(?:简约|简单)", value):
        operations.append({"type": "set_style", "style": "minimal"})
    return {"instruction": value, "operations": operations, "requiresConfirmation": True, "source": "local-rule"}


def apply_instruction(meta: dict, plan: dict) -> dict:
    result = dict(meta)
    design = dict(result.get("design") or {})
    for operation in plan.get("operations") or []:
        kind = operation.get("type")
        if kind == "set_background":
            design["background"] = operation.get("color")
        elif kind == "scale_product":
            design["productScale"] = 1 + max(0, min(200, int(operation.get("percent", 0)))) / 100
        elif kind == "set_style":
            design["style"] = operation.get("style")
        elif kind == "unify_typography":
            design["typographyUnified"] = True
    result["design"] = design
    return result
