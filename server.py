from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any
from uuid import uuid4

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.utils import secure_filename

from jobs import JobStore, ReportProcessor

app = Flask(__name__)
CORS(app)
UPLOAD_DIR = Path('uploads')
OUTPUT_DIR = Path('output')
DB_PATH = OUTPUT_DIR / 'report_jobs.db'

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

job_store = JobStore(DB_PATH)
processor = ReportProcessor(job_store, uploads_dir=UPLOAD_DIR, output_dir=OUTPUT_DIR)


def _build_job_payload(job: Dict[str, Any], keywords: Any) -> Dict[str, Any]:
    return {
        'success': True,
        'data': {
            'reportId': job['report_id'],
            'status': job['status'],
            'message': job.get('message', ''),
            'keywords': keywords,
        }
    }


@app.route('/api/v1/reports', methods=['POST'])
def create_report():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '缺少文件字段'}), 400

    upload_file = request.files['file']
    if upload_file.filename == '':
        return jsonify({'success': False, 'message': '文件名不能为空'}), 400

    display_name = request.form.get('fileName') or upload_file.filename
    safe_name = secure_filename(display_name) or 'report.pdf'
    report_id = str(uuid4())
    report_folder = UPLOAD_DIR / report_id
    report_folder.mkdir(parents=True, exist_ok=True)
    pdf_path = report_folder / safe_name
    upload_file.save(pdf_path)

    job = job_store.create(file_name=display_name, file_path=pdf_path, report_id=report_id)
    processor.submit(report_id)

    response = {
        'success': True,
        'data': {
            'reportId': job['report_id'],
            'status': job['status'],
            'message': '文件上传成功，正在处理中...',
            'keywords': []
        }
    }
    return jsonify(response), 201


@app.route('/api/v1/reports/<report_id>', methods=['GET'])
def get_report(report_id: str):
    job = job_store.fetch(report_id)
    if not job:
        return jsonify({'success': False, 'message': '报告不存在'}), 404

    status = job['status']
    keywords: Any = [] if status != 'COMPLETED' else {}

    if status == 'COMPLETED' and job.get('result_path'):
        payload_path = Path(job['result_path'])
        if payload_path.exists():
            try:
                payload = json.loads(payload_path.read_text(encoding='utf-8'))
                keywords = payload.get('data', {}).get('keywords', {})
            except Exception:
                keywords = {}
        else:
            keywords = {}
    elif status == 'FAILED':
        keywords = []
    else:
        keywords = []

    payload = _build_job_payload(job, keywords)
    if status == 'PROCESSING':
        payload['data']['message'] = job.get('message') or '文件正在处理中'
    elif status == 'FAILED':
        payload['data']['message'] = job.get('message') or '无法解析此 PDF 文档。'

    return jsonify(payload)



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3001, debug=False)
