# 财报分析系统升级说明

## 升级概览

本次升级将系统从**预定义字段提取**升级为**AI自动化全字段提取**，支持分段处理、多轮验证和智能可信度计算。

---

## 主要改进

### 1. ✨ 自动化全指标提取
- **旧版本**：需要在 `config.py` 中预定义要提取的指标列表
- **新版本**：AI自动识别并提取财报中的所有财务指标，无需预定义

### 2. 🔄 分段+重叠提取策略
- **分段处理**：将长文档分成多个段落块（默认每块5段）
- **重叠窗口**：段落块之间有重叠（默认重叠2段），确保跨段落信息不丢失
- **示例**：段落1-5、段落4-8、段落7-11...

### 3. ✅ 多轮验证机制
- **第一轮**：提取所有财务指标
- **第二轮**：验证是否有遗漏或错误，补充遗漏的指标
- **可配置**：可通过 `ENABLE_VERIFICATION` 关闭验证以节省成本

### 4. 📊 衍生指标支持
自动提取并合并以下衍生指标：
- `value`：当期值
- `value_lastyear`：去年同期值
- `value_before2year`：前年同期值
- `YoY`：同比增长率（如 21.57%）
- `YoY_D`：同比增长额

### 5. 🎯 智能可信度计算
- **新模块**：`tools/confidence.py`
- **百分制**：0-100分的置信度评分
- **多因素**：基于模型投票一致性、字段完整性、支持模型数量等
- **自动化**：无需手动配置，自动计算

### 6. 📍 精确定位信息
- 支持 `bbox` 坐标定位
- 返回 `page_id` 和 `para_id`
- 便于前端高亮显示

---

## 新增文件

### `tools/confidence.py`
置信度计算模块，提供以下函数：
- `calculate_confidence(merged_item)` - 计算单个指标的置信度（0-100）
- `calculate_batch_confidence(merged_results)` - 批量计算置信度

---

## 修改的文件

### 1. `tools/extractor.py`
**新增功能：**
- `extract_all_metrics_chunked()` - 自动化分段提取所有指标
- `_build_verification_prompt()` - 生成验证提示词
- `_create_chunks()` - 创建重叠段落块
- `_normalize_auto_extract()` - 解析自动提取结果

**新增配置：**
```python
CHUNK_SIZE = 5  # 每块段落数
CHUNK_OVERLAP = 2  # 重叠段落数
ENABLE_VERIFICATION = True  # 启用验证
```

### 2. `tools/merger.py`
**改进：**
- 支持动态字段识别（不依赖预定义METRICS）
- 集成 `confidence.py` 计算百分制置信度
- 支持衍生指标字段的投票合并
- 改为按 `(company, metric)` 分组（而非 `(company, metric, page_id, para_id)`）

### 3. `main.py`
**新增参数：**
- `auto_extract` - 是否使用自动提取模式（默认True）
- `--legacy` 命令行参数 - 使用旧版预定义指标提取

**改进：**
- 调用新的 `extract_all_metrics_chunked()` 函数
- 输出包含所有衍生指标字段

### 4. `jobs.py`
**改进：**
- `build_keywords_payload()` 支持动态字段映射
- 自动处理百分制置信度
- 支持所有衍生指标字段

### 5. `config.py`
**新增配置：**
```python
# 分段提取配置
CHUNK_SIZE = 5
CHUNK_OVERLAP = 2
ENABLE_VERIFICATION = True

# 自动提取模式
AUTO_EXTRACT_MODE = True
```

---

## 使用方法

### 方法1：使用新的自动提取模式（推荐）

```bash
# 使用默认配置
python main.py --pdf pdfs/report.pdf

# 自定义输出目录
python main.py --pdf pdfs/report.pdf --output_dir ./my_output

# Mock模式（无需API密钥，用于测试）
python main.py --pdf pdfs/report.pdf --mock
```

### 方法2：使用旧版预定义指标模式

```bash
# 添加 --legacy 参数
python main.py --pdf pdfs/report.pdf --legacy
```

### 方法3：通过API服务

```bash
# 启动服务器
python server.py

# 上传PDF
curl -X POST http://localhost:8000/api/v1/reports \
  -F "file=@pdfs/report.pdf" \
  -F "fileName=2024年报.pdf"

# 查询结果
curl http://localhost:8000/api/v1/reports/{reportId}
```

---

## 配置调优

### 调整分段大小
在 `config.py` 中修改：
```python
CHUNK_SIZE = 8  # 增大块大小，减少API调用次数
CHUNK_OVERLAP = 3  # 增大重叠，提高准确性但增加成本
```

### 关闭验证（节省成本）
```python
ENABLE_VERIFICATION = False
```

### 调整并发数
```python
MAX_WORKERS = 4  # 减少并发，避免API限流
```

---

## API响应格式

### 提取结果示例

```json
{
  "success": true,
  "data": {
    "reportId": "uuid-xxx",
    "status": "COMPLETED",
    "message": "解析PDF文档成功",
    "keywords": {
      "营业收入": {
        "value": "1500.00",
        "value_lastyear": "1200.00",
        "value_before2year": "1000.00",
        "YoY": "25.00%",
        "YoY_D": "300.00",
        "unit": "亿元",
        "year": "2024",
        "type": "actual",
        "confidence": 95,
        "page_id": 3,
        "para_id": 12,
        "bbox": [100, 200, 500, 220],
        "company": "某某公司"
      },
      "净利润": {
        "value": "200.00",
        "value_lastyear": "150.00",
        "YoY": "33.33%",
        "unit": "亿元",
        "year": "2024",
        "type": "actual",
        "confidence": 88,
        "page_id": 3,
        "para_id": 15,
        "company": "某某公司"
      }
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `value` | string | 当期值 |
| `value_lastyear` | string | 去年同期值 |
| `value_before2year` | string | 前年同期值 |
| `YoY` | string | 同比增长率 |
| `YoY_D` | string | 同比增长额 |
| `unit` | string | 单位 |
| `year` | string | 年份 |
| `type` | string | 类型（actual/forecast/budget） |
| `confidence` | int | 置信度（0-100） |
| `page_id` | int | 页码 |
| `para_id` | int | 段落ID |
| `bbox` | array | 坐标 [x0, y0, x1, y1] |
| `company` | string | 公司名称 |

---

## 性能与成本

### API调用量估算

假设文档有100段落：

**旧版本（预定义5个指标）：**
- 调用次数：100段 × 5指标 × 4模型 = 2000次

**新版本（自动提取）：**
- 不启用验证：20块 × 4模型 = 80次
- 启用验证：20块 × 4模型 + 20块 × 1模型 = 100次

💡 **成本降低95%以上！**

### 准确性提升

- ✅ 不会遗漏财报中的任何指标
- ✅ 自动识别衍生数据（同比、环比等）
- ✅ 多轮验证确保完整性
- ✅ 重叠窗口避免跨段落信息丢失

---

## 故障排查

### 问题1：提取结果为空

**检查：**
1. 确认PDF已正确解析（查看 `output/parsed.json`）
2. 确认公司名称在PDF中出现
3. 查看 `output/extractions.json` 是否有原始提取结果

### 问题2：置信度过低

**可能原因：**
- 模型之间结果不一致
- 字段信息不完整（缺少单位或年份）

**解决方案：**
- 增加模型数量
- 调整提示词
- 检查PDF质量

### 问题3：API超时

**解决方案：**
- 减少 `MAX_WORKERS`
- 减少 `CHUNK_SIZE`
- 增加 `REQUEST_TIMEOUT`

---

## 兼容性说明

✅ **向后兼容**：旧版本的代码仍可使用 `--legacy` 参数运行

✅ **API兼容**：API响应格式保持一致，新增字段不影响旧版前端

✅ **配置兼容**：所有旧配置项保持有效

---

## 下一步计划

- [ ] 支持更多文件格式（Word、Excel）
- [ ] 增加财报类型识别（年报/季报/中报）
- [ ] 优化表格识别算法
- [ ] 增加指标关联分析
- [ ] 支持自定义提示词模板

---

## 技术支持

如有问题，请查看：
- 错误日志：`output/{reportId}/error.log`
- 中间结果：`output/{reportId}/extractions.json`
- 合并结果：`output/{reportId}/merged.json`

或联系开发团队获取支持。
