"""Job storage and background report processing utilities."""

from __future__ import annotations

import json
import sqlite3
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import config as cfg
from main import run_pipeline


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Simple SQLite-backed job metadata store."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    result_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create(
        self,
        file_name: str,
        file_path: Path,
        status: str = "PROCESSING",
        report_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        report_id = report_id or str(uuid4())
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reports (report_id, file_name, file_path, status, message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (report_id, file_name, str(file_path), status, "", now, now),
            )
        created = self.fetch(report_id)
        if not created:
            raise RuntimeError("Failed to create report record")
        return created

    def update(self, report_id: str, **fields):
        if not fields:
            return
        fields["updated_at"] = _utc_now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [report_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE reports SET {cols} WHERE report_id = ?", values)

    def fetch(self, report_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_id, file_name, file_path, status, message, result_path, created_at, updated_at FROM reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_recent(self, limit: int = 20):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT report_id, file_name, status, created_at, updated_at FROM reports ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


class ReportProcessor:
    """Runs PDF pipeline jobs asynchronously and updates their status."""

    def __init__(self, job_store: JobStore, uploads_dir: Path, output_dir: Path, workers: int = 2):
        self.job_store = job_store
        self.uploads_dir = Path(uploads_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def submit(self, report_id: str):
        self.executor.submit(self._process_job, report_id)

    def _process_job(self, report_id: str):
        job = self.job_store.fetch(report_id)
        if not job:
            return
        pdf_path = Path(job["file_path"])
        run_dir = self.output_dir / report_id
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            final = run_pipeline(
                pdf_files=[str(pdf_path)],
                companies=cfg.COMPANIES,
                metrics=cfg.METRICS,
                output_dir=str(run_dir),
                mock_extractor=cfg.MOCK_EXTRACTOR,
                max_workers=cfg.MAX_WORKERS,
                auto_extract=True  # 使用新的自动提取模式
            )
            keywords = build_keywords_payload(final)
            payload_path = run_dir / "keywords.json"
            payload = {
                "success": True,
                "data": {
                    "reportId": report_id,
                    "status": "COMPLETED",
                    "message": "解析PDF文档成功",
                    "keywords": keywords,
                },
            }
            payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.job_store.update(
                report_id,
                status="COMPLETED",
                message="解析PDF文档成功",
                result_path=str(payload_path),
            )
        except Exception as exc:
            error_message = f"处理失败: {exc}"
            trace_path = run_dir / "error.log"
            trace_path.write_text(traceback.format_exc(), encoding="utf-8")
            self.job_store.update(report_id, status="FAILED", message=error_message, result_path=str(trace_path))


def build_keywords_payload(final_result: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Transform final aggregated result into the API keywords shape.
    
    支持动态字段，包括衍生指标：
    - value_lastyear: 去年同期值
    - value_before2year: 前年同期值
    - YoY: 同比增长率
    - YoY_D: 同比增长额
    """

    keywords: Dict[str, Any] = {}
    for company, metrics in (final_result or {}).items():
        for metric_name, metric_data in (metrics or {}).items():
            # confidence已经是百分制（0-100）
            confidence = metric_data.get("confidence")
            if isinstance(confidence, str):
                # 如果仍是文本格式，转换为百分制
                CONFIDENCE_MAP = {"high": 100, "medium": 70, "low": 40}
                confidence = CONFIDENCE_MAP.get(confidence, 50)
            elif not isinstance(confidence, int):
                confidence = 50
            
            keywords[metric_name] = {
                "value": metric_data.get("value", ""),
                "value_lastyear": metric_data.get("value_lastyear", ""),
                "value_before2year": metric_data.get("value_before2year", ""),
                "YoY": metric_data.get("YoY", ""),
                "YoY_D": metric_data.get("YoY_D", ""),
                "unit": metric_data.get("unit", ""),
                "year": metric_data.get("year", ""),
                "type": metric_data.get("type", ""),
                "confidence": confidence,
                "page_id": metric_data.get("page_id"),
                "para_id": metric_data.get("para_id"),
                "bbox": metric_data.get("bbox"),
            }
    return keywords
