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
import json_repair

# 智谱 SDK
try:
    from zai import ZhipuAiClient
except Exception:
    ZhipuAiClient = None

# OpenAI-compatible SDK (for Qwen and DeepSeek)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

import config as cfg

# ---------- 配置 ----------
MAX_PROMPT_CHARS = 3500
DEFAULT_TEMPERATURE = 0.0
CONCURRENCY = 6
REQUEST_TIMEOUT = 30

# 分段提取配置
CHUNK_SIZE = 5  # 每次处理的段落数量
CHUNK_OVERLAP = 2  # 段落重叠数量
ENABLE_VERIFICATION = True  # 是否启用二轮验证

ZHIPU_API_KEY = cfg.ZHIPU_API_KEY
SPARK_API_KEY = cfg.SPARK_API_KEY
SPARK_ENDPOINT = cfg.SPARK_ENDPOINT
DASHSCOPE_API_KEY = cfg.DASHSCOPE_API_KEY
DASHSCOPE_BASE_URL = cfg.DASHSCOPE_BASE_URL

_mock_flag = os.getenv("EXTRACTOR_MOCK")
if _mock_flag is None:
    MOCK_MODE = bool(cfg.MOCK_EXTRACTOR)
else:
    MOCK_MODE = _mock_flag == "1"

# ---------- 工具函数 ----------

def _truncate_text(t: str, max_chars: int = MAX_PROMPT_CHARS) -> str:
    if not t:
        return t
    if len(t) <= max_chars:
        return t
    return t[: max_chars // 2] + "\n...<truncated>...\n" + t[-max_chars // 2 :]


def _build_prompt(paragraph_text: str, metric: Optional[str] = None) -> str:
    """
    构建提取提示词
    
    Args:
        paragraph_text: 段落文本
        metric: 指标名称（可选）。如果为None，则进行开放式全指标提取
    """
    p = _truncate_text(paragraph_text)
    
    if metric:
        # 针对特定指标的提取（保留原有逻辑兼容性）
        return (
            f"请从下面的段落中抽取与指标「{metric}」相关的数值信息。\n"
            "返回严格的 JSON 对象，包含字段：value, unit, year, type, note。\n"
            '如果没有相关信息，返回 {"value":"","unit":"","year":"","type":"","note":""}。\n'
            f"段落:\n{p}\n"
            "仅返回 JSON。"
        )
    else:
        # 开放式全指标提取（新功能）
        return (
            "请从下面的财报段落中提取所有财务和经营指标的数值信息。\n\n"
            "要求：\n"
            "1. 提取所有出现的指标名称和对应数值\n"
            "2. 特别注意表格数据、同比数据、环比数据\n"
            "3. 提取以下信息（如有）：\n"
            "   - metric: 指标名称\n"
            "   - value: 当期值\n"
            "   - value_lastyear: 去年同期值\n"
            "   - value_before2year: 前年同期值\n"
            "   - YoY: 同比增长率（如 21.57%）\n"
            "   - YoY_D: 同比增长额\n"
            "   - unit: 单位（如：万元、亿元、%）\n"
            "   - year: 年份\n"
            "   - type: 类型（actual/forecast/budget）\n"
            "\n"
            "返回 JSON 数组格式：\n"
            '[{"metric":"指标名","value":"值","value_lastyear":"去年值","YoY":"同比","unit":"单位","year":"年份","type":"类型"},...]\n\n'
            "如果段落中没有任何财务指标，返回空数组 []。\n\n"
            f"段落内容:\n{p}\n\n"
            "仅返回 JSON 数组，不要任何解释。"
        )


def _build_verification_prompt(paragraph_text: str, extracted_metrics: List[Dict[str, Any]]) -> str:
    """
    构建二轮验证提示词
    
    Args:
        paragraph_text: 原始段落文本
        extracted_metrics: 第一轮提取的结果
    """
    p = _truncate_text(paragraph_text)
    metrics_json = json.dumps(extracted_metrics, ensure_ascii=False, indent=2)
    
    return (
        "请检查以下从财报段落中提取的指标是否完整和准确。\n\n"
        f"原始段落:\n{p}\n\n"
        f"已提取的指标:\n{metrics_json}\n\n"
        "请执行以下检查：\n"
        "1. 是否有遗漏的重要指标？\n"
        "2. 提取的数值是否准确？\n"
        "3. 单位是否正确？\n"
        "4. 同比数据是否完整？\n\n"
        "返回格式：\n"
        "{\n"
        "  \"has_issues\": true/false,\n"
        "  \"missing_metrics\": [{\"metric\":\"...\",\"value\":\"...\",\"unit\":\"...\"}],\n"
        "  \"corrections\": [{\"metric\":\"...\",\"field\":\"value\",\"old\":\"...\",\"new\":\"...\"}],\n"
        "  \"notes\": \"检查说明\"\n"
        "}\n\n"
        "仅返回 JSON，不要任何解释。"
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


class QwenClient(BaseClient):
    def __init__(self, api_key: str, base_url: str):
        self.name = "qwen3-max"
        if not OpenAI:
            raise RuntimeError("openai SDK not installed")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
    def call(self, prompt: str, max_tokens: int = 300, temperature: float = DEFAULT_TEMPERATURE) -> Dict[str, Any]:
        t0 = time.time()
        resp = self.client.chat.completions.create(
            model="qwen3-max",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False
        )
        latency = time.time() - t0
        text = resp.choices[0].message.content
        return {"raw_text": text, "latency": latency, "ok": True}


class DeepSeekClient(BaseClient):
    def __init__(self, api_key: str, base_url: str):
        self.name = "deepseek-v3.2-exp"
        if not OpenAI:
            raise RuntimeError("openai SDK not installed")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
    def call(self, prompt: str, max_tokens: int = 300, temperature: float = DEFAULT_TEMPERATURE) -> Dict[str, Any]:
        t0 = time.time()
        resp = self.client.chat.completions.create(
            model="deepseek-v3.2-exp",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body={"enable_thinking": True},
            stream=False
        )
        latency = time.time() - t0
        text = resp.choices[0].message.content
        return {"raw_text": text, "latency": latency, "ok": True}

# ---------- 输出解析 ----------

def _try_parse_json(s: str):
    try:
        return json_repair.loads(s)
    except Exception:
        return None


def _normalize(raw: str) -> Dict[str, Any]:
    j = _try_parse_json(raw)
    if isinstance(j, dict):
        return {"value":str(j.get("value","")), "unit":str(j.get("unit","")), "year":str(j.get("year","")), "type":str(j.get("type","")), "note":str(j.get("note","")), "raw":raw}
    return {"value":"","unit":"","year":"","type":"","note":raw[:200],"raw":raw}


def _normalize_auto_extract(raw: str) -> List[Dict[str, Any]]:
    """
    解析自动提取的JSON数组结果
    
    Args:
        raw: LLM返回的原始文本
    
    Returns:
        规范化的指标列表
    """
    j = _try_parse_json(raw)
    
    # 如果解析为列表
    if isinstance(j, list):
        normalized = []
        for item in j:
            if isinstance(item, dict):
                normalized.append({
                    "metric": str(item.get("metric", "")),
                    "value": str(item.get("value", "")),
                    "value_lastyear": str(item.get("value_lastyear", "")),
                    "value_before2year": str(item.get("value_before2year", "")),
                    "YoY": str(item.get("YoY", "")),
                    "YoY_D": str(item.get("YoY_D", "")),
                    "unit": str(item.get("unit", "")),
                    "year": str(item.get("year", "")),
                    "type": str(item.get("type", "")),
                    "note": str(item.get("note", "")),
                    "raw": raw
                })
        return normalized
    
    # 如果解析为单个字典（兼容旧格式）
    if isinstance(j, dict):
        return [{
            "metric": str(j.get("metric", "")),
            "value": str(j.get("value", "")),
            "value_lastyear": str(j.get("value_lastyear", "")),
            "value_before2year": str(j.get("value_before2year", "")),
            "YoY": str(j.get("YoY", "")),
            "YoY_D": str(j.get("YoY_D", "")),
            "unit": str(j.get("unit", "")),
            "year": str(j.get("year", "")),
            "type": str(j.get("type", "")),
            "note": str(j.get("note", "")),
            "raw": raw
        }]
    
    return []


def _create_chunks(paragraphs: List[Dict[str, Any]], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[List[Dict[str, Any]]]:
    """
    将段落列表分成重叠的块
    
    Args:
        paragraphs: 段落列表
        chunk_size: 每块的段落数量
        overlap: 重叠的段落数量
    
    Returns:
        段落块列表
    """
    if not paragraphs:
        return []
    
    chunks = []
    i = 0
    while i < len(paragraphs):
        chunk = paragraphs[i:i + chunk_size]
        chunks.append(chunk)
        i += chunk_size - overlap
        
        # 防止无限循环
        if chunk_size <= overlap:
            break
    
    return chunks


def _merge_chunk_text(chunk: List[Dict[str, Any]]) -> str:
    """
    将一个段落块合并为文本
    
    Args:
        chunk: 段落列表
    
    Returns:
        合并后的文本
    """
    texts = []
    for para in chunk:
        text = para.get('text', '')
        if text:
            para_marker = f"[段落 {para.get('page_id', '?')}-{para.get('para_id', '?')}]"
            texts.append(f"{para_marker}\n{text}")
    
    return "\n\n".join(texts)

# ---------- 主函数 ----------

def extract_all_metrics_chunked(
    paragraphs: List[Dict[str, Any]], 
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    enable_verification: bool = ENABLE_VERIFICATION,
    workers: int = CONCURRENCY
) -> List[Dict[str, Any]]:
    """
    自动化提取所有财务指标（分段+重叠+二轮验证）
    
    Args:
        paragraphs: 段落列表
        chunk_size: 每次处理的段落数量
        overlap: 段落重叠数量
        enable_verification: 是否启用二轮验证
        workers: 并发数
    
    Returns:
        提取结果列表，每个结果包含：
            - model: 模型名称
            - metric: 指标名称
            - value: 当期值
            - value_lastyear: 去年同期值
            - value_before2year: 前年同期值
            - YoY: 同比增长率
            - YoY_D: 同比增长额
            - unit: 单位
            - year: 年份
            - type: 类型
            - page_id, para_id: 位置信息
            - company: 公司名称
    """
    clients: List[BaseClient] = []
    if MOCK_MODE:
        clients = [MockClient("glm-4-plus"), MockClient("spark-4.0Ultra")]
    else:
        if ZHIPU_API_KEY:
            clients.append(ZhipuClient(ZHIPU_API_KEY))
        if SPARK_API_KEY:
            clients.append(SparkClient(SPARK_API_KEY))
        if DASHSCOPE_API_KEY:
            clients.append(QwenClient(DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL))
            clients.append(DeepSeekClient(DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL))
        if not clients:
            raise RuntimeError("No LLM extractor configured. Provide API keys in config.py or enable mock mode.")
    
    # 创建段落块
    chunks = _create_chunks(paragraphs, chunk_size, overlap)
    print(f"Created {len(chunks)} chunks from {len(paragraphs)} paragraphs")
    
    results = []
    
    # 第一轮：提取
    print(f"Phase 1: Extracting metrics from {len(chunks)} chunks...")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = []
        for chunk_idx, chunk in enumerate(chunks):
            chunk_text = _merge_chunk_text(chunk)
            prompt = _build_prompt(chunk_text, metric=None)  # 开放式提取
            
            for client in clients:
                futs.append(ex.submit(_call_auto_extract, client, prompt, chunk, chunk_idx))
        
        for f in as_completed(futs):
            r = f.result()
            if r:
                results.extend(r)
    
    print(f"Phase 1 complete: extracted {len(results)} metric entries")
    
    # 第二轮：验证（可选）
    if enable_verification and results:
        print(f"Phase 2: Verifying extracted metrics...")
        verified_results = _verify_extractions(chunks, results, clients, workers)
        print(f"Phase 2 complete: {len(verified_results)} entries after verification")
        return verified_results
    
    return results


def extract_metrics(paragraphs: List[Dict[str,Any]], metrics: List[str], workers:int=CONCURRENCY) -> List[Dict[str,Any]]:
    """
    针对特定指标列表的提取（保留旧版本兼容性）
    
    Args:
        paragraphs: 段落列表
        metrics: 指标名称列表
        workers: 并发数
    
    Returns:
        提取结果列表
    """
    clients: List[BaseClient] = []
    if MOCK_MODE:
        clients = [MockClient("glm-4-plus"), MockClient("spark-4.0Ultra"), MockClient("qwen3-max"), MockClient("deepseek-v3.2-exp")]
    else:
        if ZHIPU_API_KEY:
            clients.append(ZhipuClient(ZHIPU_API_KEY))
        if SPARK_API_KEY:
            clients.append(SparkClient(SPARK_API_KEY))
        if DASHSCOPE_API_KEY:
            clients.append(QwenClient(DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL))
            clients.append(DeepSeekClient(DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL))
        if not clients:
            raise RuntimeError("No LLM extractor configured. Provide API keys in config.py or enable mock mode.")
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


def _call_auto_extract(client: BaseClient, prompt: str, chunk: List[Dict[str, Any]], chunk_idx: int):
    """
    调用模型进行自动化提取
    """
    try:
        resp = client.call(prompt, max_tokens=1000)  # 增加token限制以容纳更多指标
        metrics = _normalize_auto_extract(resp.get("raw_text", ""))
        
        results = []
        for metric_data in metrics:
            if not metric_data.get("metric"):
                continue
            
            # 为每个提取的指标创建结果记录
            # 使用chunk的第一个段落的位置信息
            first_para = chunk[0] if chunk else {}
            
            result = {
                "model": client.name,
                "metric": metric_data["metric"],
                "value": metric_data["value"],
                "value_lastyear": metric_data.get("value_lastyear", ""),
                "value_before2year": metric_data.get("value_before2year", ""),
                "YoY": metric_data.get("YoY", ""),
                "YoY_D": metric_data.get("YoY_D", ""),
                "unit": metric_data["unit"],
                "year": metric_data["year"],
                "type": metric_data["type"],
                "note": metric_data.get("note", ""),
                "raw": metric_data["raw"],
                "latency": resp.get("latency"),
                "page_id": first_para.get("page_id"),
                "para_id": first_para.get("para_id"),
                "chunk_idx": chunk_idx,
                "company": first_para.get("company", "")
            }
            results.append(result)
        
        return results
    except Exception as e:
        print(f"Error in auto extract with {client.name}: {e}")
        return []


def _verify_extractions(
    chunks: List[List[Dict[str, Any]]], 
    extractions: List[Dict[str, Any]], 
    clients: List[BaseClient],
    workers: int
) -> List[Dict[str, Any]]:
    """
    二轮验证提取结果
    
    Args:
        chunks: 段落块列表
        extractions: 第一轮提取结果
        clients: 模型客户端列表
        workers: 并发数
    
    Returns:
        验证和补充后的结果
    """
    # 按chunk_idx分组
    from collections import defaultdict
    chunk_extractions = defaultdict(list)
    for ext in extractions:
        chunk_idx = ext.get("chunk_idx", -1)
        if chunk_idx >= 0:
            chunk_extractions[chunk_idx].append(ext)
    
    verified = list(extractions)  # 保留原始结果
    
    # 对每个chunk进行验证
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = []
        for chunk_idx, chunk in enumerate(chunks):
            chunk_text = _merge_chunk_text(chunk)
            chunk_metrics = chunk_extractions.get(chunk_idx, [])
            
            if not chunk_metrics:
                continue
            
            # 只用一个模型进行验证（节省成本）
            client = clients[0] if clients else None
            if client:
                futs.append(ex.submit(_call_verification, client, chunk_text, chunk_metrics, chunk, chunk_idx))
        
        for f in as_completed(futs):
            additional = f.result()
            if additional:
                verified.extend(additional)
    
    return verified


def _call_verification(
    client: BaseClient, 
    chunk_text: str, 
    extracted_metrics: List[Dict[str, Any]], 
    chunk: List[Dict[str, Any]],
    chunk_idx: int
):
    """
    调用模型进行验证
    """
    try:
        prompt = _build_verification_prompt(chunk_text, extracted_metrics)
        resp = client.call(prompt, max_tokens=800)
        verification = _try_parse_json(resp.get("raw_text", ""))
        
        if not isinstance(verification, dict):
            return []
        
        # 提取遗漏的指标
        missing = verification.get("missing_metrics", [])
        additional_results = []
        
        first_para = chunk[0] if chunk else {}
        
        for miss in missing:
            if isinstance(miss, dict) and miss.get("metric"):
                result = {
                    "model": f"{client.name}-verify",
                    "metric": miss.get("metric", ""),
                    "value": miss.get("value", ""),
                    "value_lastyear": miss.get("value_lastyear", ""),
                    "value_before2year": miss.get("value_before2year", ""),
                    "YoY": miss.get("YoY", ""),
                    "YoY_D": miss.get("YoY_D", ""),
                    "unit": miss.get("unit", ""),
                    "year": miss.get("year", ""),
                    "type": miss.get("type", ""),
                    "note": f"Verification补充: {verification.get('notes', '')}",
                    "page_id": first_para.get("page_id"),
                    "para_id": first_para.get("para_id"),
                    "chunk_idx": chunk_idx,
                    "company": first_para.get("company", "")
                }
                additional_results.append(result)
        
        return additional_results
    except Exception as e:
        print(f"Error in verification with {client.name}: {e}")
        return []


def _call(client: BaseClient, prompt: str, metric: str, para: Dict[str,Any]):
    try:
        resp = client.call(prompt)
        norm = _normalize(resp.get("raw_text",""))
        return {"model":client.name, "metric":metric, "value":norm["value"], "unit":norm["unit"], "year":norm["year"], "type":norm["type"], "note":norm["note"], "raw":norm["raw"], "latency":resp.get("latency"), "page_id":para.get("page_id"), "para_id":para.get("para_id"), "company":para.get("company")}
    except Exception as e:
        return {"model":client.name, "metric":metric, "error":str(e), "page_id":para.get("page_id"), "para_id":para.get("para_id"), "company":para.get("company")}


if __name__ == "__main__":
    print("Extractor module ready (Zhipu + Spark)")
