# path: tools/extractor.py
"""
Extractor module (updated for real APIs)

- 支持智谱 GLM (通过 zai.ZhipuAiClient)
- 支持讯飞星火 Spark (通过 v2/chat/completions)
- 保持统一输出格式
"""

from __future__ import annotations

import os
import time
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

import requests

# 智谱 SDK
try:
    from zai import ZhipuAiClient
except Exception:
    ZhipuAiClient = None

# ---------- 配置 ----------
MAX_PROMPT_CHARS = 3500
DEFAULT_TEMPERATURE = 0.0
CONCURRENCY = 6
REQUEST_TIMEOUT = 30

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY","64f170d742a64de681b5c978d2f896ca.LykJN8uymnwNA0o6")
SPARK_API_KEY = os.getenv("SPARK_API_KEY","jUKnJwaWgcKBuPzbJQOc:lKHUGblYvqXXIdryjDjv")
SPARK_ENDPOINT = os.getenv("SPARK_ENDPOINT", "https://spark-api-open.xf-yun.com/v2/chat/completions")

MOCK_MODE = os.getenv("EXTRACTOR_MOCK", "0") 

# ---------- 工具函数 ----------

def _truncate_text(t: str, max_chars: int = MAX_PROMPT_CHARS) -> str:
    if not t:
        return t
    if len(t) <= max_chars:
        return t
    return t[: max_chars // 2] + "\n...<truncated>...\n" + t[-max_chars // 2 :]


def _build_prompt(paragraph_text: str, metric: str) -> str:
    p = _truncate_text(paragraph_text)
    return (
        f"请从下面的段落中抽取与指标“{metric}”相关的数值信息。\n"
        "返回严格的 JSON 对象，包含字段：value, unit, year, type, note。\n"
        "如果没有相关信息，返回 {\"value\":\"\",\"unit\":\"\",\"year\":\"\",\"type\":\"\",\"note\":\"\"}。\n"
        f"段落:\n{p}\n"
        "仅返回 JSON。"
    )

# ---------- 客户端实现 ----------

class BaseClient:
    name: str = "base"
    def call(self, prompt: str, max_tokens: int = 300, temperature: float = DEFAULT_TEMPERATURE) -> Dict[str, Any]:
        raise NotImplementedError


class MockClient(BaseClient):
    def __init__(self, name: str):
        self.name = name
    def call(self, prompt: str, max_tokens: int = 300, temperature: float = DEFAULT_TEMPERATURE) -> Dict[str, Any]:
        return {"raw_text": json.dumps({"value":"100","unit":"亿元","year":"2023","type":"actual","note":"mock"},ensure_ascii=False), "latency":0.0, "ok":True}


class ZhipuClient(BaseClient):
    def __init__(self, api_key: str):
        self.name = "glm-4-plus"
        if not ZhipuAiClient:
            raise RuntimeError("zai SDK not installed")
        self.client = ZhipuAiClient(api_key=api_key)
    def call(self, prompt: str, max_tokens: int = 300, temperature: float = DEFAULT_TEMPERATURE) -> Dict[str, Any]:
        t0 = time.time()
        resp = self.client.chat.completions.create(
            model="glm-4-plus",
            messages=[{"role":"user","content":prompt}],
            max_tokens=max_tokens,
            temperature=temperature
        )
        latency = time.time() - t0
        text = resp.choices[0].message.content
        return {"raw_text": text, "latency": latency, "ok": True}


class SparkClient(BaseClient):
    def __init__(self, api_key: str):
        self.name = "spark-4.0Ultra"
        self.api_key = api_key
    def call(self, prompt: str, max_tokens: int = 300, temperature: float = DEFAULT_TEMPERATURE) -> Dict[str, Any]:
        t0 = time.time()
        headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        body = {"model": "4.0Ultra", "user": "user_id", "messages":[{"role":"user","content":prompt}], "stream": False}
        r = requests.post(SPARK_ENDPOINT, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        latency = time.time() - t0
        r.raise_for_status()
        data = r.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"raw_text": text, "latency": latency, "ok": True}

# ---------- 输出解析 ----------

def _try_parse_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*?\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except: return None
    return None


def _normalize(raw: str) -> Dict[str, Any]:
    j = _try_parse_json(raw)
    if isinstance(j, dict):
        return {"value":str(j.get("value","")), "unit":str(j.get("unit","")), "year":str(j.get("year","")), "type":str(j.get("type","")), "note":str(j.get("note","")), "raw":raw}
    return {"value":"","unit":"","year":"","type":"","note":raw[:200],"raw":raw}

# ---------- 主函数 ----------

def extract_metrics(paragraphs: List[Dict[str,Any]], metrics: List[str], workers:int=CONCURRENCY) -> List[Dict[str,Any]]:
    clients: List[BaseClient] = []
    if MOCK_MODE:
        clients = [MockClient("glm-4-plus"), MockClient("spark-4.0Ultra")]
    else:
        if ZHIPU_API_KEY:
            clients.append(ZhipuClient(ZHIPU_API_KEY))
        if SPARK_API_KEY:
            clients.append(SparkClient(SPARK_API_KEY))
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = []
        for para in paragraphs:
            txt = para.get("text","")
            for m in metrics:
                prompt = _build_prompt(txt, m)
                for c in clients:
                    futs.append(ex.submit(_call, c, prompt, m, para))
        for f in as_completed(futs):
            r = f.result()
            if r: results.append(r)
    return results


def _call(client: BaseClient, prompt: str, metric: str, para: Dict[str,Any]):
    try:
        resp = client.call(prompt)
        norm = _normalize(resp.get("raw_text",""))
        return {"model":client.name, "metric":metric, "value":norm["value"], "unit":norm["unit"], "year":norm["year"], "type":norm["type"], "note":norm["note"], "raw":norm["raw"], "latency":resp.get("latency"), "page_id":para.get("page_id"), "para_id":para.get("para_id"), "company":para.get("company")}
    except Exception as e:
        return {"model":client.name, "metric":metric, "error":str(e), "page_id":para.get("page_id"), "para_id":para.get("para_id"), "company":para.get("company")}


if __name__ == "__main__":
    print("Extractor module ready (Zhipu + Spark)")
