# # 多模型结果融合与可信度分类
# from openai import OpenAI

# class EmbeddingHelper:
#     def __init__(self, model_name):
#         self.model_name = model_name

#     def embed(self, text):
#         import os

#         client = OpenAI(
#             api_key=os.getenv("DASHSCOPE_API_KEY","sk-ad8d5e09965d495c8d8a193a7f16d06d"),  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
#             base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"  # 百炼服务的base_url
#         )

#         completion = client.embeddings.create(
#             model="text-embedding-v4",
#             input=text,
#             dimensions=1024, # 指定向量维度（仅 text-embedding-v3及 text-embedding-v4支持该参数）
#             encoding_format="float"
#         )

#         print(completion.model_dump_json())
#         #返回的json格式，向量是1024维度的
#         # { 
#         # "data": [
#         #     {
#         #     "embedding": [
#         #         0.0023064255,
#         #         -0.009327292,
#         #         .... 
#         #         -0.0028842222,
#         #     ],
#         #     "index": 0,
#         #     "object": "embedding"
#         #     }
#         # ],
#         # "model":"text-embedding-v3",
#         # "object":"list",
#         # "usage":{"prompt_tokens":26,"total_tokens":26},
#         # "id":"f62c2ae7-0906-9758-ab34-47c5764f07e2"
#         # }

#         # 这里调用具体的模型进行文本嵌入
#         return ????
# # 多模型结果融合与可信度分类


"""
多模型结果融合与可信度分类

支持动态字段识别和衍生指标（value_lastyear, YoY等）的合并
"""

from collections import defaultdict, Counter
from typing import Dict, Any, List, Tuple
import re
import json_repair
import config as cfg

# 尝试导入 LLM 客户端
try:
    from tools.extractor import ZhipuClient, SparkClient, QwenClient, DeepSeekClient, MockClient
except ImportError:
    try:
        from extractor import ZhipuClient, SparkClient, QwenClient, DeepSeekClient, MockClient
    except ImportError:
        pass

# 导入置信度计算模块
try:
    from tools.confidence import calculate_confidence
except ImportError:
    try:
        from confidence import calculate_confidence
    except ImportError:
        # 降级方案：使用简单映射
        def calculate_confidence(item: Dict[str, Any]) -> int:
            confidence_map = {"high": 100, "medium": 70, "low": 40}
            return confidence_map.get(item.get("confidence", "medium"), 50)

def clean_numeric_value(val: str) -> str:
    """
    清洗数值，移除非数字字符（保留小数点和负号）
    """
    if not val:
        return ""
    # 移除千分位逗号
    val = val.replace(',', '')
    # 提取数字部分 (支持负数和小数)
    match = re.search(r'-?\d+\.?\d*', val)
    if match:
        return match.group(0)
    return val

def semantic_merge_metrics(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    使用 AI 对指标进行语义合并（去除重复/同义指标）
    """
    # 1. 收集所有指标名称
    metrics = list(set(r['metric'] for r in results if r.get('metric')))
    if not metrics:
        return results

    # 2. 初始化 LLM 客户端
    client = None
    if cfg.MOCK_EXTRACTOR:
         client = MockClient("mock")
    elif cfg.ZHIPU_API_KEY:
        client = ZhipuClient(cfg.ZHIPU_API_KEY)
    elif cfg.DASHSCOPE_API_KEY:
        client = QwenClient(cfg.DASHSCOPE_API_KEY, cfg.DASHSCOPE_BASE_URL)
    
    if not client:
        print("Warning: No LLM client available for semantic merge, skipping.")
        return results

    # 3. 构建提示词
    prompt = (
        "请分析以下财务指标名称列表，找出含义相同或包含关系的指标，并将它们合并为标准名称。\n"
        "原则：\n"
        "1. 优先保留更简洁、通用的名称（如'营业收入'优于'营业收入（合并口径）'）\n"
        "2. 去除括号内的补充说明，除非那是区分不同指标的关键（如'期初'和'期末'通常需要区分，除非你能确定它们是重复的）。\n"
        "3. 重点合并：'XX余额' 与 'XX余额（报告期末）' 通常是同一个指标，请合并为 'XX余额'。\n"
        "4. '非合并口径' 与 '合并口径' 如果数值一致或者是默认口径，可以合并为通用名称。\n"
        "5. 返回一个 JSON 映射对象，格式为 {\"原指标名\": \"标准指标名\"}。\n"
        "6. 未提及的指标将保持原样。\n\n"
        f"指标列表：{json_repair.dumps(metrics, ensure_ascii=False)}\n\n"
        "仅返回 JSON。"
    )

    # 4. 调用 LLM
    try:
        print("Running semantic merge on metrics...")
        resp = client.call(prompt, max_tokens=2000)
        mapping = json_repair.loads(resp.get("raw_text", "{}"))
        print(f"Semantic merge mapping: {mapping}")
    except Exception as e:
        print(f"Semantic merge failed: {e}")
        mapping = {}

    # 5. 应用映射
    for r in results:
        old_m = r.get('metric')
        if old_m and old_m in mapping:
            r['metric'] = mapping[old_m]
            # 记录原始指标名以便追溯
            if 'original_metric' not in r:
                r['original_metric'] = old_m
    
    return results

def merge_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    合并多个大模型的提取结果，使用投票制度选择最优值
    
    支持动态字段识别，不依赖预定义的指标列表
    
    Args:
        results: 包含多个模型提取结果的列表
                
    Returns:
        合并后的结果列表
    """
    
    # 0. 语义合并（AI）
    results = semantic_merge_metrics(results)

    # 按 (company, metric) 分组（不再依赖page_id/para_id，因为同一指标可能出现在多处）
    grouped = defaultdict(list)
    for result in results:
        # 跳过无效记录
        if not result.get('metric') or not result.get('company'):
            continue
            
        key = (
            result.get('company', 'Unknown'),
            result.get('metric', '').strip()
        )
        grouped[key].append(result)
    
    merged_results = []
    
    for (company, metric), group in grouped.items():
        # 对每组进行投票合并
        merged_item = vote_merge_group(group)
        
        # 计算百分制置信度
        confidence_score = calculate_confidence(merged_item)
        
        # 构建最终结果
        final_item = {
            'company': company,
            'metric': metric,
            'value': merged_item.get('value', ''),
            'value_lastyear': merged_item.get('value_lastyear', ''),
            'value_before2year': merged_item.get('value_before2year', ''),
            'YoY': merged_item.get('YoY', ''),
            'YoY_D': merged_item.get('YoY_D', ''),
            'unit': merged_item.get('unit', ''),
            'year': merged_item.get('year', ''),
            'type': merged_item.get('type', ''),
            'confidence': confidence_score,  # 百分制
            'page_id': merged_item.get('page_id'),
            'para_id': merged_item.get('para_id'),
            'support': merged_item.get('support', []),
            'notes': merged_item.get('notes', [])
        }
        merged_results.append(final_item)
    
    return merged_results


def vote_merge_group(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    对同一组（相同company, metric）的结果进行投票合并
    
    支持多字段投票：value, value_lastyear, value_before2year, YoY, YoY_D等
    
    Args:
        group: 同一组的所有模型结果
        
    Returns:
        投票选出的最优结果，包含置信度信息
    """
    
    if not group:
        return {}
    
    # 如果只有一个结果，直接返回
    if len(group) == 1:
        result = group[0].copy()
        result['confidence'] = 'medium'  # 单个模型默认中等置信度
        result['support'] = [result.get('model', 'unknown')]
        result['notes'] = []
        return result
    
    # 对主要字段分别进行投票
    field_votes = {
        'value': Counter(),
        'value_lastyear': Counter(),
        'value_before2year': Counter(),
        'YoY': Counter(),
        'YoY_D': Counter(),
        'unit': Counter(),
        'year': Counter(),
        'type': Counter(),
    }
    
    # 收集每个字段的投票
    for item in group:
        for field in field_votes.keys():
            val = item.get(field, '').strip()
            
            # 对数值字段进行清洗
            if field in ['value', 'value_lastyear', 'value_before2year', 'YoY', 'YoY_D']:
                val = clean_numeric_value(val)

            if val:  # 只统计非空值
                field_votes[field][val] += 1
    
    # 选择每个字段的获胜值
    merged = {}
    for field, votes in field_votes.items():
        if votes:
            merged[field] = votes.most_common(1)[0][0]
        else:
            merged[field] = ''
    
    # 计算主字段（value）的投票比例作为置信度参考
    value_votes = field_votes['value']
    if value_votes:
        winning_value, winning_count = value_votes.most_common(1)[0]
        total_votes = sum(value_votes.values())
        vote_ratio = winning_count / total_votes if total_votes > 0 else 0
    else:
        vote_ratio = 0
        winning_count = 0
    
    total_models = len(group)
    
    # 根据投票比例确定文本置信度
    if vote_ratio >= 0.8:
        confidence = 'high'
    elif vote_ratio >= 0.5:
        confidence = 'medium'
    else:
        confidence = 'low'
    
    # 收集支持的模型
    support_models = [item.get('model', 'unknown') for item in group]
    
    # 创建注释信息
    notes = []
    notes.append(f"投票结果: {winning_count}/{total_models} 模型支持此值")
    
    if len(value_votes) > 1:
        # 如果有多个不同的值，记录所有投票结果
        vote_details = []
        for value, votes in value_votes.most_common():
            vote_details.append(f"{value}: {votes}票")
        notes.append(f"所有投票: {'; '.join(vote_details)}")
    
    # 选择一个代表性的位置信息（选第一个）
    merged['page_id'] = group[0].get('page_id')
    merged['para_id'] = group[0].get('para_id')
    
    # 更新结果
    merged.update({
        'confidence': confidence,
        'support': support_models,
        'notes': notes
    })
    
    return merged