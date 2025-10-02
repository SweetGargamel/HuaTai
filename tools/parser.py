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

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, asdict
from typing import List, Optional, Any, Dict

import fitz  # PyMuPDF
import pdfplumber
import pandas as pd
from PIL import Image
import pytesseract

# ----- Configuration (tweak as needed) -----
DEFAULT_OCR_LANG = "chi_sim+eng"  # change depending on tesseract languages installed
IMAGE_DPI = 300  # resolution for rendering images before OCR
ROW_Y_EPS = 8  # pixels tolerance when grouping OCR words into rows
# --------------------------------------------


@dataclass
class Paragraph:
    page_id: int
    para_id: int
    type: str  # 'text'|'table'|'image_text'|'image_table'
    text: str
    raw_table: Optional[List[List[str]]] = None
    bbox: Optional[List[float]] = None


def _split_paragraphs(text: str) -> List[str]:
    """Split page text into paragraphs using blank lines and sentence heuristics."""
    if not text:
        return []
    # Normalize newlines
    t = re.sub(r"\r\n?", "\n", text).strip()
    # Split on two or more newlines
    parts = [p.strip() for p in re.split(r"\n{2,}", t) if p.strip()]
    # If still long single block, further split by sentences (~periods followed by space and uppercase/Chinese punctuation)
    if len(parts) == 1 and len(parts[0]) > 800:
        # attempt to split by Chinese/English sentence enders
        parts = re.split(r'(?<=[。！？.!?])\s+', parts[0])
        parts = [p.strip() for p in parts if p.strip()]
    return parts


def _ocr_image_get_text_and_table(img: Image.Image, ocr_lang: str = DEFAULT_OCR_LANG) -> Dict[str, Any]:
    """
    Run OCR on PIL image and try to return both free text and table-like rows.
    Uses pytesseract.image_to_data (TSV) to group words into rows by y-coordinate.
    """
    ocr_text = pytesseract.image_to_string(img, lang=ocr_lang)
    # Use TSV for structured output
    tsv = pytesseract.image_to_data(img, lang=ocr_lang, output_type=pytesseract.Output.DATAFRAME)
    # Filter out empty
    if tsv.empty:
        return {"text": ocr_text.strip(), "table": None}
    # Keep only confident words
    tsv = tsv[tsv.conf != -1]
    # Group by approximate top coordinate to form rows
    rows = []
    if not tsv.empty:
        # Round top coordinate to allow grouping
        tsv['row_key'] = (tsv['top'] / ROW_Y_EPS).round().astype(int)
        grouped = tsv.groupby('row_key')
        for _, g in grouped:
            # sort by left coordinate
            row_words = [str(w) for w in g.sort_values('left')['text'].tolist() if str(w).strip()]
            if row_words:
                rows.append(row_words)
    # Heuristic: if many rows and multiple columns per row, treat as table
    table = None
    if len(rows) >= 2 and any(len(r) > 1 for r in rows):
        table = rows
    return {"text": ocr_text.strip(), "table": table}


def _extract_images_from_page(mupdf_doc: fitz.Document, page_number: int) -> List[Image.Image]:
    """Extract images from a page using PyMuPDF and return list of PIL Images."""
    pg = mupdf_doc.load_page(page_number)
    images = []
    for img in pg.get_images(full=True):
        xref = img[0]
        try:
            pix = fitz.Pixmap(mupdf_doc, xref)
            if pix.n >= 5:  # CMYK: convert to RGB
                pix = fitz.Pixmap(fitz.csRGB, pix)
            mode = "RGB" if pix.n >= 3 else "L"
            img_pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            images.append(img_pil)
            pix = None
        except Exception:
            continue
    return images


def parse_pdf(pdf_path: str, ocr_lang: str = DEFAULT_OCR_LANG, render_images: bool = True) -> List[Dict[str, Any]]:
    """
    Parse PDF and return list of paragraph dicts with page_id, para_id, text.

    - Extract textual paragraphs from pdfplumber.
    - Extract table objects via pdfplumber and convert to text/table entries.
    - Extract images with PyMuPDF and run OCR on them.
    """
    results: List[Paragraph] = []
    para_counter = 1

    # Open both libraries
    with pdfplumber.open(pdf_path) as pdf, fitz.open(pdf_path) as mdoc:
        for page_idx, page in enumerate(pdf.pages):
            page_no = page_idx + 1
            # 1) Text extraction
            text = page.extract_text() or ""
            paras = _split_paragraphs(text)
            for p in paras:
                results.append(Paragraph(page_id=page_no, para_id=para_counter, type='text', text=p))
                para_counter += 1

            # 2) Table extraction via pdfplumber
            try:
                tables = page.extract_tables()
            except Exception:
                tables = []
            for table in tables:
                # table is list of rows (list of cells)
                # Create pretty text for the table and also keep raw
                clean_rows = [[(cell or "").strip() for cell in row] for row in table]
                # Build single-line representation for text field
                text_repr = '\n'.join([' | '.join(r) for r in clean_rows if any(c.strip() for c in r)])
                results.append(Paragraph(page_id=page_no, para_id=para_counter, type='table', text=text_repr, raw_table=clean_rows))
                para_counter += 1

            # 3) Image extraction + OCR
            if render_images:
                images = _extract_images_from_page(mdoc, page_idx)
                for img in images:
                    # Optional: resize to improve OCR if very small
                    if max(img.size) < 800:
                        scale = int(IMAGE_DPI / 72)
                        new_size = (img.width * scale, img.height * scale)
                        img = img.resize(new_size, resample=Image.BICUBIC)
                    ocr_res = _ocr_image_get_text_and_table(img, ocr_lang=ocr_lang)
                    text_o = ocr_res.get('text', '').strip()
                    tab = ocr_res.get('table')
                    if tab:
                        text_repr = '\n'.join([' | '.join(r) for r in tab])
                        results.append(Paragraph(page_id=page_no, para_id=para_counter, type='image_table', text=text_repr, raw_table=tab))
                    elif text_o:
                        results.append(Paragraph(page_id=page_no, para_id=para_counter, type='image_text', text=text_o))
                    para_counter += 1

    # Convert dataclasses to dicts
    out = [asdict(p) for p in results]
    return out


def save_json(output: List[Dict[str, Any]], out_path: str):
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    # Quick CLI for testing
    import argparse

    parser = argparse.ArgumentParser(description='Parse PDF into paragraph-like entries (text, tables, OCR images).')
    parser.add_argument('pdf', help='Path to PDF file')
    parser.add_argument('--out', '-o', help='Output JSON path', default='parsed_output.json')
    parser.add_argument('--ocr-lang', help='Tesseract OCR language(s)', default=DEFAULT_OCR_LANG)
    args = parser.parse_args()

    out = parse_pdf(args.pdf, ocr_lang=args.ocr_lang)
    save_json(out, args.out)
    print(f'Parsed {len(out)} entries and saved to {args.out}')
