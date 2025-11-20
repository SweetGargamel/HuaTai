# PDF 财报关键词抽取后端

该后端完成“上传 PDF → 异步解析 → 轮询获取关键词”的闭环，既能作为命令行流水线使用，也能通过 REST API 提供任务式服务。

- `main.py`：核心流水线，负责解析 PDF、调用大模型、合并结果并导出 JSON。
- `tools/`：包含解析、抽取、融合三个模块。
- `jobs.py`：SQLite 任务存储 + 线程池后台处理器，负责管理 reportId、状态、结果文件。
- `server.py`：Flask 应用，提供 `POST /api/v1/reports` 与 `GET /api/v1/reports/{reportId}` 两个接口。
- `config.py`：配置公司与指标、输出目录、Mock 模式等。

---

## 1. 环境准备

### 1.1 Python
推荐 Python 3.9+。

```bash
python -m venv venv
source venv/bin/activate      # Linux / macOS
venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

若无 `requirements.txt`，请手动安装：

```bash
pip install pdfplumber pymupdf pillow pytesseract pandas requests flask zai
```

### 1.2 OCR 依赖

- Linux：`sudo apt install tesseract-ocr libtesseract-dev`
- macOS：`brew install tesseract`
- Windows：参考 [UB Mannheim 版本](https://github.com/UB-Mannheim/tesseract/wiki)
- 需要中文请将 `chi_sim.traineddata` 放入 tessdata 目录。

---

## 2. 配置 `config.py`

所有关键参数（公司、指标、API Key、Mock 开关）都在 `config.py` 中维护。

```python
COMPANIES = ["招商证券"]
METRICS = ["营收", "利润", "债券面值", "利率"]

# 必填：真实调用所需的 API Key
ZHIPU_API_KEY = "sk-xxxxxxxx"
SPARK_API_KEY = "spark-xxxxxxxx"

# 仅在没有真实 Key 或希望离线调试时设为 True
MOCK_EXTRACTOR = False
```

- **默认行为**：`MOCK_EXTRACTOR = False` 时会直接调用真实大模型；若缺少 Key，后端会抛错，以免误以为调到了真实接口。
- **Mock 模式**：只有在 `MOCK_EXTRACTOR = True` 或 CLI 运行 `python main.py --mock ...` 时才会使用内置的模拟客户端。
- 如需保留环境变量覆盖，可手动设置 `EXTRACTOR_MOCK=1` 或导出新的 Key，项目仍会以环境变量为最高优先级。

---

## 3. 启动后端服务

```bash
python server.py
```

默认监听 `http://0.0.0.0:8000`，关键目录：

- `uploads/<reportId>/report.pdf`：用户上传的原始文件。
- `output/<reportId>/`：解析生成的中间与最终结果（`parsed.json`、`extractions.json`、`merged.json`、`final_company_metrics.json`、`keywords.json`）。
- `output/report_jobs.db`：SQLite 任务表，记录 reportId、状态、消息、结果路径。

后台处理流程：
1. `POST /api/v1/reports` 写入任务，立即返回 `reportId` 与 `PROCESSING` 状态。
2. `ReportProcessor` 在线程池中调用 `run_pipeline()`，产出 `keywords.json`。
3. 成功后将状态改为 `COMPLETED`，失败则标记 `FAILED` 并写入 `error.log`。

---

## 4. API 使用方式

### 4.1 上传 PDF 并触发任务

`POST /api/v1/reports` （`multipart/form-data`）

必填字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `file` | File | PDF 文件 |
| `fileName` | string | 业务展示用名称 |

示例：

```bash
curl -X POST http://localhost:8000/api/v1/reports \
  -F "file=@pdfs/01_Zhaoshang-149-151.pdf" \
  -F "fileName=2024年年度财报.pdf"
```

成功响应（201）：

```json
{
  "success": true,
  "message": "文件上传成功，正在处理中...",
  "data": {
    "reportId": "uuid-a1b2c3d4-e5f6-7890",
    "fileName": "2024年年度财报.pdf",
    "status": "PROCESSING",
    "uploadedAt": "2025-11-15T12:05:00+00:00"
  }
}
```

### 4.2 轮询任务状态 / 获取关键词

`GET /api/v1/reports/{reportId}`

```bash
curl http://localhost:8000/api/v1/reports/uuid-a1b2c3d4-e5f6-7890
```

- **PROCESSING**：`keywords` 返回空数组。
- **COMPLETED**：`keywords` 返回对象，每个指标节点包含 `value/YoY/confidence(%)` 等字段。
- **FAILED**：`keywords` 为空，`message` 描述错误原因。

示例完成响应：

```json
{
  "success": true,
  "data": {
    "reportId": "uuid-a1b2c3d4-e5f6-7890",
    "status": "COMPLETED",
    "message": "解析PDF文档成功",
    "keywords": {
      "债券面值": {
        "value": "1500.00",
        "YoY": "21.57%",
        "confidence": 100,
        "page_id": 1,
        "para_id": 2
      }
    }
  }
}
```

前端可按 1–2 秒间隔轮询该接口，拿到 `COMPLETED` 状态后停止轮询并展示结果。

---

## 5. 命令行模式（可选）

仍可直接调用流水线处理本地 PDF：

```bash
python main.py --pdf pdfs/01_Zhaoshang-149-151.pdf --output_dir ./output/manual
```

输出文件说明：

- `parsed.json`: 按段落/表格分段的 OCR 文本。
- `extractions.json`: 每个模型的指标抽取原始结果。
- `merged.json`: 多模型投票融合结果。
- `final_company_metrics.json`: 公司 → 指标的最佳条目。

---

## 6. 常见问题

- **长时间 PROCESSING**：检查 `output/<reportId>/error.log` 是否有异常栈，或确认模型 API Key 是否有效。
- **OCR 结果为空**：确认 PDF 是否为扫描件并正确安装了 Tesseract 中文语言包。
- **数据库损坏**：删除 `output/report_jobs.db` 后重新上传（旧任务会丢失）。
- **自定义指标**：修改 `config.py` 中的 `METRICS`，并确保前端期望的字段与 `jobs.build_keywords_payload` 对齐。

---

## 7. 项目结构

```
HuaTai/
├── config.py
├── jobs.py
├── main.py
├── server.py
├── tools/
│   ├── parser.py
│   ├── extractor.py
│   └── merger.py
├── output/
│   └── ...
├── uploads/
└── README.md
```

如需接入前端，只需使用 Axios / Fetch 调用上述两个 API 并根据 `reportId` 轮询即可。


