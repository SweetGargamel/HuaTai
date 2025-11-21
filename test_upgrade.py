"""
测试新的自动化提取功能

运行此脚本以验证升级后的功能是否正常工作
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_confidence_module():
    """测试置信度计算模块"""
    print("=" * 60)
    print("测试 1: 置信度计算模块")
    print("=" * 60)
    
    from tools.confidence import calculate_confidence
    
    test_cases = [
        {
            'name': '高置信度 - 4/4模型一致',
            'item': {
                'value': '1500.00',
                'unit': '百万元',
                'year': '2024',
                'support': ['glm-4-plus', 'spark-4.0Ultra', 'qwen3-max', 'deepseek-v3.2-exp'],
                'confidence': 'high',
                'notes': ['投票结果: 4/4 模型支持此值']
            },
            'expected_range': (95, 100)
        },
        {
            'name': '中置信度 - 2/4模型一致',
            'item': {
                'value': '250',
                'unit': '亿元',
                'year': '2024',
                'support': ['glm-4-plus', 'spark-4.0Ultra'],
                'confidence': 'medium',
                'notes': ['投票结果: 2/4 模型支持此值']
            },
            'expected_range': (50, 75)
        },
        {
            'name': '低置信度 - 空值',
            'item': {
                'value': '',
                'unit': '',
                'year': '',
                'support': ['glm-4-plus'],
                'confidence': 'low',
                'notes': ['投票结果: 1/4 模型支持此值']
            },
            'expected_range': (0, 30)
        }
    ]
    
    passed = 0
    failed = 0
    
    for case in test_cases:
        score = calculate_confidence(case['item'])
        min_score, max_score = case['expected_range']
        
        if min_score <= score <= max_score:
            print(f"✅ PASS: {case['name']}")
            print(f"   置信度: {score} (期望范围: {min_score}-{max_score})")
            passed += 1
        else:
            print(f"❌ FAIL: {case['name']}")
            print(f"   置信度: {score} (期望范围: {min_score}-{max_score})")
            failed += 1
        print()
    
    print(f"结果: {passed} 通过, {failed} 失败\n")
    return failed == 0


def test_merger_module():
    """测试合并模块"""
    print("=" * 60)
    print("测试 2: 合并模块")
    print("=" * 60)
    
    from tools.merger import merge_results
    
    # 模拟多个模型的提取结果
    test_results = [
        # 模型1
        {
            'company': '测试公司',
            'metric': '营业收入',
            'value': '1500.00',
            'value_lastyear': '1200.00',
            'YoY': '25.00%',
            'unit': '亿元',
            'year': '2024',
            'type': 'actual',
            'model': 'glm-4-plus',
            'page_id': 1,
            'para_id': 1
        },
        # 模型2 - 相同结果
        {
            'company': '测试公司',
            'metric': '营业收入',
            'value': '1500.00',
            'value_lastyear': '1200.00',
            'YoY': '25.00%',
            'unit': '亿元',
            'year': '2024',
            'type': 'actual',
            'model': 'spark-4.0Ultra',
            'page_id': 1,
            'para_id': 1
        },
        # 模型3 - 不同结果
        {
            'company': '测试公司',
            'metric': '营业收入',
            'value': '1600.00',
            'value_lastyear': '1200.00',
            'YoY': '33.33%',
            'unit': '亿元',
            'year': '2024',
            'type': 'actual',
            'model': 'qwen3-max',
            'page_id': 1,
            'para_id': 1
        },
        # 另一个指标
        {
            'company': '测试公司',
            'metric': '净利润',
            'value': '200.00',
            'unit': '亿元',
            'year': '2024',
            'type': 'actual',
            'model': 'glm-4-plus',
            'page_id': 2,
            'para_id': 3
        }
    ]
    
    merged = merge_results(test_results)
    
    print(f"输入: {len(test_results)} 条原始结果")
    print(f"输出: {len(merged)} 条合并结果")
    print()
    
    success = True
    
    # 检查是否有2个不同的指标
    if len(merged) != 2:
        print(f"❌ FAIL: 期望2个指标，实际得到 {len(merged)} 个")
        success = False
    else:
        print("✅ PASS: 正确合并为2个指标")
    
    # 检查字段完整性
    for item in merged:
        required_fields = ['company', 'metric', 'value', 'unit', 'year', 'type', 
                          'confidence', 'page_id', 'para_id', 'support', 'notes']
        missing = [f for f in required_fields if f not in item]
        
        if missing:
            print(f"❌ FAIL: 指标 '{item.get('metric')}' 缺少字段: {missing}")
            success = False
        else:
            print(f"✅ PASS: 指标 '{item.get('metric')}' 字段完整")
            
        # 检查置信度是否为整数
        if not isinstance(item.get('confidence'), int):
            print(f"❌ FAIL: 指标 '{item.get('metric')}' 的置信度不是整数")
            success = False
        else:
            print(f"   置信度: {item['confidence']} (百分制)")
    
    print()
    return success


def test_extractor_prompt():
    """测试提示词生成"""
    print("=" * 60)
    print("测试 3: 提示词生成")
    print("=" * 60)
    
    from tools.extractor import _build_prompt, _build_verification_prompt
    
    # 测试自动提取提示词
    text = "公司2024年营业收入为1500亿元，同比增长25%"
    prompt = _build_prompt(text, metric=None)
    
    print("自动提取提示词:")
    print("-" * 60)
    print(prompt[:300] + "..." if len(prompt) > 300 else prompt)
    print()
    
    # 检查关键词
    keywords = ['财报', '指标', 'JSON', 'metric', 'value', 'YoY']
    found = [kw for kw in keywords if kw in prompt]
    
    if len(found) >= len(keywords) - 1:  # 允许缺少1个
        print(f"✅ PASS: 提示词包含必要的关键词 ({len(found)}/{len(keywords)})")
    else:
        print(f"❌ FAIL: 提示词缺少关键词 ({len(found)}/{len(keywords)})")
        return False
    
    print()
    
    # 测试验证提示词
    extracted = [{'metric': '营业收入', 'value': '1500', 'unit': '亿元'}]
    verify_prompt = _build_verification_prompt(text, extracted)
    
    print("验证提示词:")
    print("-" * 60)
    print(verify_prompt[:300] + "..." if len(verify_prompt) > 300 else verify_prompt)
    print()
    
    if '检查' in verify_prompt and 'missing_metrics' in verify_prompt:
        print("✅ PASS: 验证提示词格式正确")
    else:
        print("❌ FAIL: 验证提示词格式错误")
        return False
    
    print()
    return True


def test_chunking():
    """测试分段功能"""
    print("=" * 60)
    print("测试 4: 分段功能")
    print("=" * 60)
    
    from tools.extractor import _create_chunks
    
    # 创建测试段落
    paragraphs = [
        {'page_id': 1, 'para_id': i, 'text': f'段落{i}'}
        for i in range(1, 11)  # 10个段落
    ]
    
    chunks = _create_chunks(paragraphs, chunk_size=5, overlap=2)
    
    print(f"输入: {len(paragraphs)} 个段落")
    print(f"输出: {len(chunks)} 个块")
    print()
    
    # 检查每个块的大小
    for i, chunk in enumerate(chunks):
        print(f"   块 {i+1}: 段落 {chunk[0]['para_id']}-{chunk[-1]['para_id']} ({len(chunk)} 个段落)")
    
    # 检查是否至少有2个块
    if len(chunks) >= 2:
        print(f"✅ PASS: 成功创建了 {len(chunks)} 个块")
    else:
        print(f"❌ FAIL: 块数量太少 ({len(chunks)})")
        return False
    
    # 检查重叠（如果有多个块）
    if len(chunks) >= 2:
        # 检查第1块和第2块是否有重叠
        chunk1_end = chunks[0][-1]['para_id']
        chunk2_start = chunks[1][0]['para_id']
        
        # 应该有重叠，即 chunk2_start <= chunk1_end
        if chunk2_start <= chunk1_end:
            print(f"✅ PASS: 块之间有正确的重叠 (块1结尾={chunk1_end}, 块2开始={chunk2_start})")
        else:
            print(f"❌ FAIL: 块之间没有重叠 (块1结尾={chunk1_end}, 块2开始={chunk2_start})")
            return False
    
    print()
    return True


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("财报分析系统 - 功能测试")
    print("=" * 60 + "\n")
    
    results = []
    
    try:
        results.append(("置信度计算", test_confidence_module()))
    except Exception as e:
        print(f"❌ 置信度计算测试失败: {e}\n")
        results.append(("置信度计算", False))
    
    try:
        results.append(("合并模块", test_merger_module()))
    except Exception as e:
        print(f"❌ 合并模块测试失败: {e}\n")
        results.append(("合并模块", False))
    
    try:
        results.append(("提示词生成", test_extractor_prompt()))
    except Exception as e:
        print(f"❌ 提示词生成测试失败: {e}\n")
        results.append(("提示词生成", False))
    
    try:
        results.append(("分段功能", test_chunking()))
    except Exception as e:
        print(f"❌ 分段功能测试失败: {e}\n")
        results.append(("分段功能", False))
    
    # 总结
    print("=" * 60)
    print("测试总结")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print()
    print(f"总计: {passed}/{total} 测试通过")
    print("=" * 60)
    
    if passed == total:
        print("\n🎉 所有测试通过！系统升级成功！\n")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查。\n")
        return 1


if __name__ == '__main__':
    sys.exit(main())
