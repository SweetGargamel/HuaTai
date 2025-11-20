# PDF解析，负责段落和表格定位

# path: tools/parser.py
"""
PDF parser that extracts paragraphs with (page_id, para_id, text) and
also recognizes tables and images (OCR).

Features:
- Uses pdfplumber for high-quality PDF text and table extraction.
- Uses PyMuPDF (fitz) to extract embedded images at page-level.
- Uses pytesseract for OCR on images; also uses tesseract TSV output to
  heuristically reconstruct table-like structures inside images.
- Produces a list of paragraph-like entries with metadata suitable for
  downstream extractor/merger steps.

Output format (list of dicts):
[{
  "page_id": 1,
  "para_id": 1,
  "type": "text" | "table" | "image_text" | "image_table",
  "text": "...",            # best-effort readable text
  "raw_table": [[...],...],   # present when type is table/image_table
  "bbox": [x0, top, x1, bottom], # optional bounding box in PDF coords
}]

Dependencies (pip):
  pip install pdfplumber pymupdf pillow pytesseract pandas

Tesseract: must have tesseract installed on the system and in PATH.
For Chinese OCR use language packs (e.g. chi_sim). Configure `ocr_lang` if needed.
"""

# === enhanced parser.py ===
from __future__ import annotations
import json, re, fitz, pdfplumber
from dataclasses import dataclass, asdict
from typing import List, Optional, Any, Dict
from PIL import Image
import pytesseract
import pandas as pd

DEFAULT_OCR_LANG = "chi_sim+eng"
IMAGE_DPI = 300
ROW_Y_EPS = 8

@dataclass
class Paragraph:
    page_id: int
    para_id: int
    type: str
    text: str
    raw_table: Optional[List[List[str]]] = None
    bbox: Optional[List[float]] = None

def _split_paragraphs(text: str) -> List[str]:
    if not text:
        return []
    t = re.sub(r"\r\n?", "\n", text).strip()
    parts = [p.strip() for p in re.split(r"\n{2,}", t) if p.strip()]
    if len(parts) == 1 and len(parts[0]) > 800:
        parts = re.split(r'(?<=[。！？.!?])\s+', parts[0])
        parts = [p.strip() for p in parts if p.strip()]
    return parts

def _ocr_image_get_text_and_table(img: Image.Image, ocr_lang: str = DEFAULT_OCR_LANG) -> Dict[str, Any]:
    ocr_text = pytesseract.image_to_string(img, lang=ocr_lang)
    tsv = pytesseract.image_to_data(img, lang=ocr_lang, output_type=pytesseract.Output.DATAFRAME)
    if tsv.empty:
        return {"text": ocr_text.strip(), "table": None}
    tsv = tsv[tsv.conf != -1]
    rows = []
    if not tsv.empty:
        tsv['row_key'] = (tsv['top'] / ROW_Y_EPS).round().astype(int)
        grouped = tsv.groupby('row_key')
        for _, g in grouped:
            row_words = [str(w) for w in g.sort_values('left')['text'].tolist() if str(w).strip()]
            if row_words:
                rows.append(row_words)
    table = None
    if len(rows) >= 2 and any(len(r) > 1 for r in rows):
        table = rows
    return {"text": ocr_text.strip(), "table": table}

def _extract_images_with_bbox(mupdf_doc: fitz.Document, page_number: int):
    """Return list of (PIL Image, bbox) for each image."""
    pg = mupdf_doc.load_page(page_number)
    items = []
    for img in pg.get_images(full=True):
        xref = img[0]
        bbox = None
        # 查找图片矩形
        for b in pg.get_image_info(xref):
            bbox = [b["bbox"].x0, b["bbox"].y0, b["bbox"].x1, b["bbox"].y1]
        try:
            pix = fitz.Pixmap(mupdf_doc, xref)
            if pix.n >= 5:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            mode = "RGB" if pix.n >= 3 else "L"
            img_pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            items.append((img_pil, bbox))
        except Exception:
            continue
    return items

def parse_pdf(pdf_path: str, ocr_lang: str = DEFAULT_OCR_LANG, render_images: bool = True) -> List[Dict[str, Any]]:
    results: List[Paragraph] = []
    para_counter = 1

    with pdfplumber.open(pdf_path) as pdf, fitz.open(pdf_path) as mdoc:
        for page_idx, page in enumerate(pdf.pages):
            page_no = page_idx + 1

            # --- 1. 文本段落 + bbox ---
            try:
                words = page.extract_words()  # 每个词有 x0, top, x1, bottom
                if words:
                    text = " ".join(w["text"] for w in words)
                    paras = _split_paragraphs(text)
                    for p in paras:
                        # 定位该段文字的坐标范围
                        w_in_para = [w for w in words if p[:10] in w["text"]] if p else []
                        if w_in_para:
                            x0 = min(w["x0"] for w in w_in_para)
                            y0 = min(w["top"] for w in w_in_para)
                            x1 = max(w["x1"] for w in w_in_para)
                            y1 = max(w["bottom"] for w in w_in_para)
                            bbox = [x0, y0, x1, y1]
                        else:
                            bbox = None
                        results.append(Paragraph(page_no, para_counter, "text", p, bbox=bbox))
                        para_counter += 1
            except Exception:
                pass

            # --- 2. 表格 ---
            try:
                tables = page.extract_tables()
            except Exception:
                tables = []
            for table in tables:
                clean_rows = [[(cell or "").strip() for cell in row] for row in table]
                text_repr = '\n'.join([' | '.join(r) for r in clean_rows if any(c.strip() for c in r)])
                # pdfplumber table 没直接 bbox，用表格所有文字 bbox 估计
                try:
                    words = page.extract_words()
                    x0 = min(w["x0"] for w in words)
                    y0 = min(w["top"] for w in words)
                    x1 = max(w["x1"] for w in words)
                    y1 = max(w["bottom"] for w in words)
                    bbox = [x0, y0, x1, y1]
                except Exception:
                    bbox = None
                results.append(Paragraph(page_no, para_counter, "table", text_repr, raw_table=clean_rows, bbox=bbox))
                para_counter += 1

            # --- 3. 图片 + OCR ---
            if render_images:
                for img, bbox in _extract_images_with_bbox(mdoc, page_idx):
                    if max(img.size) < 800:
                        scale = int(IMAGE_DPI / 72)
                        new_size = (img.width * scale, img.height * scale)
                        img = img.resize(new_size)
                    ocr_res = _ocr_image_get_text_and_table(img, ocr_lang)
                    text_o, tab = ocr_res.get('text', ''), ocr_res.get('table')
                    if tab:
                        text_repr = '\n'.join([' | '.join(r) for r in tab])
                        results.append(Paragraph(page_no, para_counter, "image_table", text_repr, raw_table=tab, bbox=bbox))
                    elif text_o:
                        results.append(Paragraph(page_no, para_counter, "image_text", text_o, bbox=bbox))
                    para_counter += 1

    return [asdict(p) for p in results]
