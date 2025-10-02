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


# 这里需要你进行这样的操作
"""
我现在想要做一个合并的函数，我现在在用大模型去提取某个财报里面的数据 ，
然后不同的大模型会返回数据。我希望能够合并不同大模型的结果。
我能怎么写，请你用python帮我写这个代码.
"""

from collections import defaultdict, Counter

def merge_results(results):
    """
    合并多个大模型的提取结果，使用投票制度选择最优值
    
    Args:
        results: 包含多个模型提取结果的列表，每个结果包含:
                - company: 公司名称
                - metric: 指标名称（如营收、营业额等）
                - value: 提取的数值
                - unit: 单位
                - year: 年份
                - type: 类型
                - model: 模型名称
                - page_id, para_id: 位置信息
                
    Returns:
        合并后的结果列表，每个元素代表一个唯一的(company, metric, page_id, para_id)组合的最优结果
        只保留指定的字段：value, unit, year, type, confidence, page_id, para_id, support, notes
    """
    
    # 按 (company, metric, page_id, para_id) 分组
    grouped = defaultdict(list)
    for result in results:
        # 跳过无效记录
        if not result.get('metric') or not result.get('company'):
            continue
            
        key = (
            result.get('company', 'Unknown'),
            result.get('metric', ''),
            result.get('page_id', ''),
            result.get('para_id', '')
        )
        grouped[key].append(result)
    
    merged_results = []
    
    for (company, metric, page_id, para_id), group in grouped.items():
        # 对每组进行投票合并
        merged_item = vote_merge_group(group)
        
        # 只保留指定的字段
        final_item = {
            'company': company,
            'metric': metric,
            'value': merged_item.get('value', ''),
            'unit': merged_item.get('unit', ''),
            'year': merged_item.get('year', ''),
            'type': merged_item.get('type', ''),
            'confidence': merged_item.get('confidence', ''),
            'page_id': merged_item.get('page_id'),
            'para_id': merged_item.get('para_id'),
            'support': merged_item.get('support', []),
            'notes': merged_item.get('notes', [])
        }
        merged_results.append(final_item)
    
    return merged_results


def vote_merge_group(group):
    """
    对同一组（相同company, metric, page_id, para_id）的结果进行投票合并
    
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
    
    # 对提取的值进行投票
    # 创建值的组合键：(value, unit, year, type)
    value_votes = Counter()
    value_to_items = defaultdict(list)
    
    for item in group:
        value_key = (
            item.get('value', ''),
            item.get('unit', ''),
            item.get('year', ''),
            item.get('type', '')
        )
        value_votes[value_key] += 1
        value_to_items[value_key].append(item)
    
    # 选择得票最多的值
    winning_value_key, winning_votes = value_votes.most_common(1)[0]
    winning_items = value_to_items[winning_value_key]
    
    # 选择获胜值中的一个代表项（选第一个）
    representative = winning_items[0].copy()
    
    # 计算置信度（基于投票比例）
    total_votes = len(group)
    vote_ratio = winning_votes / total_votes
    
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
    notes.append(f"投票结果: {winning_votes}/{total_votes} 模型支持此值")
    
    if len(value_votes) > 1:
        # 如果有多个不同的值，记录所有投票结果
        vote_details = []
        for (value, unit, year, type_), votes in value_votes.most_common():
            vote_details.append(f"{value} {unit} ({year}, {type_}): {votes}票")
        notes.append(f"所有投票: {'; '.join(vote_details)}")
    
    # 更新结果
    representative.update({
        'confidence': confidence,
        'support': support_models,
        'notes': notes
    })
    
    return representative