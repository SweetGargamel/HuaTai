# This canvas contains two files concatenated for convenience. Copy each section
# into its own file in your repo.

# === file: config.py ===
"""
Configuration for the pipeline.
Contains company list, metric list, and some runtime options.
"""

COMPANIES = [
    # Put the canonical company names you want to scan for in the PDFs.
    # Matching is simple substring search (case-sensitive for now). Add variants
    # if necessary (e.g. short name, full name).
    "招商证券",
]

METRICS = [
    # Put the metrics you want to extract from documents.
    "营收",
    "利润",
    "债券面值",
    "利率",
]

# --- LLM credentials ---
# Fill in the API keys you received from each provider. These values are used
# unless you explicitly enable mock mode.
ZHIPU_API_KEY = ""
SPARK_API_KEY = ""
SPARK_ENDPOINT = "https://spark-api-open.xf-yun.com/v2/chat/completions"

# 阿里云百炼 API (Qwen 和 DeepSeek 模型)
DASHSCOPE_API_KEY = "sk-ad8d5e09965d495c8d8a193a7f16d06d"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Where to write intermediate and final outputs
OUTPUT_DIR = "./output"
PARSED_JSON = "{output_dir}/parsed.json"
EXTRACTIONS_JSON = "{output_dir}/extractions.json"
MERGED_JSON = "{output_dir}/merged.json"
FINAL_JSON = "{output_dir}/final_company_metrics.json"

# PDF source(s) can be a list or a single file path. You can also supply via CLI.
PDF_FILES = [
"pdfs/01_Zhaoshang-149-151.pdf"

]  # e.g. ["/path/to/report1.pdf", "/path/to/report2.pdf"]

# Whether to run extractor in mock mode (no API keys required). When False,
# the backend will attempt to call the real APIs and raise if keys are missing.
MOCK_EXTRACTOR = False

# Other settings
MAX_WORKERS = 6


