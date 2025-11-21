"""
可信度计算模块

基于多个大模型的投票结果计算置信度（百分制）
"""

from typing import Dict, Any, List, Optional
from collections import Counter


def calculate_confidence(merged_item: Dict[str, Any]) -> int:
    """
    根据合并后的数据项计算置信度（百分制：0-100）
    
    置信度计算规则：
    1. 基础分：根据模型投票一致性
       - 100% 一致（所有模型返回相同值）: 100分
       - 80%+ 一致: 85-95分
       - 60-80% 一致: 70-85分
       - 50-60% 一致: 55-70分
       - <50% 一致: 30-55分
    
    2. 加分项：
       - 有明确单位: +5分
       - 有年份信息: +5分
       - 支持模型数量 >= 3: +5分
    
    3. 减分项：
       - 值为空或无效: -30分
       - 只有1个模型支持: -20分
    
    Args:
        merged_item: 合并后的数据项，包含以下字段：
            - value: 提取的值
            - unit: 单位
            - year: 年份
            - support: 支持的模型列表
            - confidence: 原有的文本置信度（high/medium/low）
            - notes: 注释信息（可能包含投票详情）
    
    Returns:
        int: 0-100的置信度分数
    """
    
    # 获取基础信息
    value = merged_item.get('value', '').strip()
    unit = merged_item.get('unit', '').strip()
    year = merged_item.get('year', '').strip()
    support_models = merged_item.get('support', [])
    text_confidence = merged_item.get('confidence', 'medium').lower()
    notes = merged_item.get('notes', [])
    
    # 起始分数：根据原有文本置信度
    confidence_base_map = {
        'high': 90,
        'medium': 65,
        'low': 40
    }
    base_score = confidence_base_map.get(text_confidence, 50)
    
    # 尝试从notes中解析投票比例
    vote_ratio = _extract_vote_ratio_from_notes(notes)
    
    if vote_ratio is not None:
        # 根据投票比例细化分数
        if vote_ratio >= 1.0:
            base_score = 100
        elif vote_ratio >= 0.8:
            base_score = 85 + int((vote_ratio - 0.8) * 50)  # 85-95
        elif vote_ratio >= 0.6:
            base_score = 70 + int((vote_ratio - 0.6) * 75)  # 70-85
        elif vote_ratio >= 0.5:
            base_score = 55 + int((vote_ratio - 0.5) * 150) # 55-70
        else:
            base_score = 30 + int(vote_ratio * 50)          # 30-55
    
    # 加分项
    bonus = 0
    if unit:
        bonus += 5
    if year:
        bonus += 5
    if len(support_models) >= 3:
        bonus += 5
    
    # 减分项
    penalty = 0
    if not value or value == '':
        penalty += 30
    elif len(support_models) == 1:
        penalty += 20
    
    # 计算最终分数
    final_score = base_score + bonus - penalty
    
    # 确保在0-100范围内
    final_score = max(0, min(100, final_score))
    
    return final_score


def _extract_vote_ratio_from_notes(notes: List[str]) -> Optional[float]:
    """
    从notes中提取投票比例
    
    例如：notes = ["投票结果: 3/4 模型支持此值", ...]
    返回：0.75
    """
    if not notes:
        return None
    
    import re
    for note in notes:
        # 匹配 "投票结果: X/Y 模型支持此值" 或类似格式
        match = re.search(r'(\d+)\s*/\s*(\d+)\s*模型', note)
        if match:
            numerator = int(match.group(1))
            denominator = int(match.group(2))
            if denominator > 0:
                return numerator / denominator
    
    return None


def calculate_batch_confidence(merged_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    批量计算置信度
    
    Args:
        merged_results: 合并后的结果列表
    
    Returns:
        添加了confidence字段（百分制）的结果列表
    """
    results_with_confidence = []
    
    for item in merged_results:
        item_copy = item.copy()
        # 计算百分制置信度
        confidence_score = calculate_confidence(item)
        # 更新confidence字段为百分制
        item_copy['confidence'] = confidence_score
        results_with_confidence.append(item_copy)
    
    return results_with_confidence


if __name__ == '__main__':
    # 测试用例
    test_cases = [
        {
            'value': '1500.00',
            'unit': '百万元',
            'year': '2024',
            'support': ['glm-4-plus', 'spark-4.0Ultra', 'qwen3-max', 'deepseek-v3.2-exp'],
            'confidence': 'high',
            'notes': ['投票结果: 4/4 模型支持此值']
        },
        {
            'value': '250',
            'unit': '亿元',
            'year': '2024',
            'support': ['glm-4-plus', 'spark-4.0Ultra'],
            'confidence': 'medium',
            'notes': ['投票结果: 2/4 模型支持此值', '所有投票: 250 亿元 (2024, actual): 2票; 260 亿元 (2024, actual): 2票']
        },
        {
            'value': '',
            'unit': '',
            'year': '',
            'support': ['glm-4-plus'],
            'confidence': 'low',
            'notes': ['投票结果: 1/4 模型支持此值']
        }
    ]
    
    print("置信度计算测试:")
    for i, case in enumerate(test_cases, 1):
        score = calculate_confidence(case)
        print(f"\n测试 {i}:")
        print(f"  值: {case['value']} {case['unit']}")
        print(f"  支持模型数: {len(case['support'])}")
        print(f"  原置信度: {case['confidence']}")
        print(f"  计算得分: {score}")
