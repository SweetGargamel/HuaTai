
"""
Main pipeline entrypoint.

- Loads config
- Parses PDF(s) into paragraphs via tools.parser.parse_pdf
- Calls tools.extractor.extract_metrics for paragraphs relevant to each company
- Merges multi-model outputs via tools.merger.merge_results
- Aggregates merged results into final JSON: company -> metric -> best entry

Run:
  python main.py --pdf /path/to/doc.pdf

"""
import os
import sys
import json
import argparse
from collections import defaultdict
from typing import List, Dict, Any

# Import pipeline modules from tools/ (assumes tools/ is on PYTHONPATH)
try:
    from tools import parser as pdf_parser
    from tools import extractor as llm_extractor
    from tools import merger as results_merger
except Exception:
    # Try local import path fallback
    import importlib.util
    # if running from repo root where tools/ is a sibling
    sys.path.append(os.path.abspath('.'))
    from tools import parser as pdf_parser
    from tools import extractor as llm_extractor
    from tools import merger as results_merger

# Load config (config.py should be in same dir or pythonpath)
import config as cfg


def ensure_output_dir(path: str):
    os.makedirs(path, exist_ok=True)


def save_json(obj: Any, path: str):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_pdf_list(cli_pdf: List[str]) -> List[str]:
    if cli_pdf:
        return cli_pdf
    if cfg.PDF_FILES:
        return cfg.PDF_FILES
    raise SystemExit('No PDF files provided. Set config.PDF_FILES or pass --pdf')


def find_companies_in_paragraph(paragraph_text: str, companies: List[str]) -> List[str]:
    hits = []
    for c in companies:
        if c in paragraph_text:
            hits.append(c)
    return hits


def aggregate_merged_for_company(merged_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Build metric -> best item (by confidence then support count)
    metric_map = {}
    rank = {'high': 3, 'medium': 2, 'low': 1}
    for item in merged_items:
        metric = item['metric']
        cur = metric_map.get(metric)
        if not cur:
            metric_map[metric] = item
            continue
        # Compare confidence
        cur_score = rank.get(cur.get('confidence','low'), 0)
        new_score = rank.get(item.get('confidence','low'), 0)
        if new_score > cur_score:
            metric_map[metric] = item
        elif new_score == cur_score:
            # tie-breaker: more supporting models
            if len(item.get('support',[])) > len(cur.get('support',[])):
                metric_map[metric] = item
    return metric_map


def run_pipeline(pdf_files: List[str], companies: List[str], metrics: List[str], output_dir: str, mock_extractor: bool, max_workers:int, auto_extract: bool = True):
    """
    运行提取流程
    
    Args:
        pdf_files: PDF文件列表
        companies: 公司列表
        metrics: 指标列表（仅当auto_extract=False时使用）
        output_dir: 输出目录
        mock_extractor: 是否使用mock模式
        max_workers: 并发数
        auto_extract: 是否使用自动化全指标提取（True=新模式，False=旧模式）
    """
    ensure_output_dir(output_dir)

    all_paragraphs = []
    # 1) Parse PDFs
    for pdf in pdf_files:
        print(f'Parsing {pdf}...')
        paras = pdf_parser.parse_pdf(pdf, ocr_lang='chi_sim+eng', render_images=True)
        # add source file path in paragraphs
        for p in paras:
            p['source_file'] = os.path.basename(pdf)
        all_paragraphs.extend(paras)

    parsed_path = cfg.PARSED_JSON.format(output_dir=output_dir)
    save_json(all_paragraphs, parsed_path)
    print(f'Parsed paragraphs saved to {parsed_path} (count={len(all_paragraphs)})')

    # 2) For each company, select paragraphs mentioning company; if none, fallback to all paragraphs
    company_paragraphs = {}
    for comp in companies:
        sel = [p for p in all_paragraphs if comp in (p.get('text') or '')]
        if not sel:
            # fallback: look in source file name
            sel = [p for p in all_paragraphs if comp in (p.get('source_file') or '')]
        if not sel:
            print(f'Warning: no paragraphs matched company {comp}, will search whole doc for metrics')
            sel = all_paragraphs
        company_paragraphs[comp] = sel

    # 3) Call extractor for each company's paragraphs
    extractor_results = []
    # Optionally override mock mode
    if mock_extractor:
        os.environ['EXTRACTOR_MOCK'] = '1'
    else:
        os.environ['EXTRACTOR_MOCK'] = '0'

    for comp, paras in company_paragraphs.items():
        # 为段落添加公司标识
        for p in paras:
            p['company'] = comp
        
        if auto_extract:
            # 新模式：自动化全指标提取
            print(f'Running AUTO extraction for company {comp} on {len(paras)} paragraphs...')
            res = llm_extractor.extract_all_metrics_chunked(
                paras, 
                chunk_size=getattr(cfg, 'CHUNK_SIZE', 5),
                overlap=getattr(cfg, 'CHUNK_OVERLAP', 2),
                enable_verification=getattr(cfg, 'ENABLE_VERIFICATION', True),
                workers=max_workers
            )
        else:
            # 旧模式：基于预定义指标列表提取
            print(f'Running extraction for company {comp} on {len(paras)} paragraphs with {len(metrics)} metrics...')
            res = llm_extractor.extract_metrics(paras, metrics, workers=max_workers)
        
        # attach company tag (如果extractor没有添加的话)
        for r in res:
            if 'company' not in r or not r['company']:
                r['company'] = comp
        extractor_results.extend(res)

    ext_path = cfg.EXTRACTIONS_JSON.format(output_dir=output_dir)
    save_json(extractor_results, ext_path)
    print(f'Extraction results saved to {ext_path} (rows={len(extractor_results)})')

    
    # 4) Merge per company/metric
    merged = results_merger.merge_results(extractor_results)
    merged_path = cfg.MERGED_JSON.format(output_dir=output_dir)
    save_json(merged, merged_path)
    print(f'Merged results saved to {merged_path} (items={len(merged)})')

    # 5) Aggregate into final company -> metric -> entry
    final = {}
    # group merged by company
    by_company = defaultdict(list)
    for m in merged:
        comp = m.get('company') or 'Unknown'
        by_company[comp].append(m)

    para_bbox_map = {
        (p.get("page_id"), p.get("para_id")): p.get("bbox")
        for p in all_paragraphs
        if p.get("page_id") is not None and p.get("para_id") is not None
    }

    for comp, items in by_company.items():
        metric_map = aggregate_merged_for_company(items)
        # transform into desired JSON shape: metric -> {value, unit, year, type, confidence, source}
        final_map = {}
        for metric, item in metric_map.items():
            bbox = para_bbox_map.get((item.get("page_id"), item.get("para_id")))
            final_map[metric] = {
                'value': item.get('value',''),
                'value_lastyear': item.get('value_lastyear', ''),
                'value_before2year': item.get('value_before2year', ''),
                'YoY': item.get('YoY', ''),
                'YoY_D': item.get('YoY_D', ''),
                'unit': item.get('unit',''),
                'year': item.get('year',''),
                'type': item.get('type',''),
                'confidence': item.get('confidence',''),
                'page_id': item.get('page_id'),
                'para_id': item.get('para_id'),
                'bbox': bbox, 
                'support': item.get('support',[]),
                'notes': item.get('notes',[])
            }
        final[comp] = final_map

    final_path = cfg.FINAL_JSON.format(output_dir=output_dir)
    save_json(final, final_path)
    print(f'Final aggregated company metrics written to {final_path}')

    return final


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', nargs='+', help='PDF file(s) to process')
    ap.add_argument('--output_dir', default='./output')
    ap.add_argument('--mock', action='store_true', help='Use mock extractor (no API keys)')
    ap.add_argument('--legacy', action='store_true', help='Use legacy extraction (predefined metrics only)')
    args = ap.parse_args()

    pdfs = load_pdf_list(args.pdf)
    cfg.PDF_FILES = pdfs
    cfg.PARSED_JSON = cfg.PARSED_JSON
    cfg.EXTRACTIONS_JSON = cfg.EXTRACTIONS_JSON
    cfg.MERGED_JSON = cfg.MERGED_JSON
    cfg.FINAL_JSON = cfg.FINAL_JSON

    run_pipeline(
        pdfs, 
        cfg.COMPANIES, 
        cfg.METRICS, 
        args.output_dir, 
        mock_extractor=(args.mock or cfg.MOCK_EXTRACTOR), 
        max_workers=cfg.MAX_WORKERS,
        auto_extract=(not args.legacy)  # 默认使用新的自动提取模式
    )
