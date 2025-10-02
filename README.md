# PDF 财报指标抽取系统

本项目实现了一个端到端的财报信息抽取系统：
- **parser.py**：解析 PDF，提取段落、表格、图片 OCR 内容。
- **extractor.py**：构造 Prompt 调用多种大模型（本系统采用智谱 GLM、讯飞星火），抽取指标。
- **merger.py**：融合多模型结果，打分可信度。
- **main.py**：整体流水线入口，输出最终 JSON（公司 → 指标 → 值/单位/年份/类型/位置/可信度）。
- **config.py**：配置公司列表、指标列表、输出目录。

---

## 1. 环境准备

### Python 环境
推荐 Python 3.9+
```bash
python -m venv venv
source venv/bin/activate  # Linux / macOS
venv\Scripts\activate     # Windows
```

### 安装依赖
```bash
pip install -r requirements.txt
```
如果没有 `requirements.txt`，请安装：
```bash
pip install pdfplumber pymupdf pillow pytesseract pandas requests zai
```

### 安装 Tesseract OCR
- Linux: `sudo apt install tesseract-ocr libtesseract-dev`
- macOS: `brew install tesseract`
- Windows: [下载 Tesseract OCR 安装包](https://github.com/UB-Mannheim/tesseract/wiki)
- 中文支持：下载 `chi_sim.traineddata` 到 tessdata 目录。

---

## 2. 配置 API Key

### 智谱 GLM-4-plus
设置环境变量：
```bash
export ZHIPU_API_KEY="your-zhipu-api-key"
```

### 讯飞星火 Spark 4.0Ultra
设置环境变量：
```bash
export SPARK_API_KEY="your-spark-api-password"
```

如果未配置 API Key，系统会自动启用 **mock 模式**（返回模拟结果，方便调试）。

---

## 3. 配置公司与指标
编辑 `config.py`：
```python
COMPANIES = [
    "中国南方航空股份有限公司"
]

METRICS = [
    "营收",
    "利润",
    "债券面值",
    "利率"
]
```

---

## 4. 运行示例
```bash
python main.py --pdf ./sample.pdf --output_dir ./output
```

输出目录下将生成：
- `parsed.json`：解析出的段落/表格/图片文字
- `extractions.json`：模型逐条抽取结果
- `merged.json`：多模型融合结果（含可信度）
- `final_company_metrics.json`：最终公司 → 指标 → 指标值/单位/年份/位置/可信度

示例：
```json
{
  "中国南方航空股份有限公司": {
    "债券面值": {
      "value": "1500.00",
      "unit": "百万元",
      "year": "2022",
      "type": "actual",
      "confidence": "high",
      "page_id": 1,
      "para_id": 2,
      "support": ["glm-4-plus", "spark-4.0Ultra"],
      "notes": ["..."]
    }
  }
}
```

---

## 5. 目录结构
```
project/
  ├── tools/
  │   ├── parser.py
  │   ├── extractor.py
  │   └── merger.py
  ├── config.py
  ├── main.py
  ├── README.md
  └── requirements.txt
```

---

## 6. 注意事项
- OCR 对扫描 PDF 的表格识别效果有限，可自行优化。
- 如果调用真实大模型，请注意 API key 的保密。
- merger 的可信度规则可根据业务需求调整。


