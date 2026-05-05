"""
OCR Service — local text extraction from PDFs.

Strategy:
  1. PyMuPDF (fitz) extracts embedded text from every page (free, instant).
  2. If a page has < 20 chars of embedded text, render it to a PIL image and
     run pytesseract OCR on it (no Gemini tokens consumed).
  3. Return the combined plain text, which is then forwarded to Gemini as a
     normal text prompt — far cheaper than sending raw PDF bytes.

Requirements (already installed):
  pip install pymupdf pytesseract pillow
  + Tesseract OCR engine: https://github.com/UB-Mannheim/tesseract/wiki
    (if not installed, image pages fall back to "[image page - OCR unavailable]")
"""

import base64
import io
from typing import Optional

from .logger import logger

# Minimum characters a page must contain via embedded text before we OCR it.
_MIN_TEXT_CHARS = 20


def extract_text_from_pdf_base64(file_base64: str) -> Optional[str]:
    """
    Given a base64-encoded PDF, return its full text content using local OCR.
    Returns None on unrecoverable error.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.log("PyMuPDF not installed — cannot perform local OCR", "error")
        return None

    try:
        raw_bytes = base64.b64decode(file_base64)
    except Exception as e:
        logger.log(f"OCR: base64 decode failed: {e}", "error")
        return None

    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
    except Exception as e:
        logger.log(f"OCR: failed to open PDF: {e}", "error")
        return None

    pages_text: list[str] = []
    total_pages = len(doc)
    logger.log(f"OCR: processing {total_pages} page(s)", "info")

    for page_num in range(total_pages):
        page = doc[page_num]

        # --- Step 1: Try embedded text first (fast, zero tokens) ---
        embedded_text = page.get_text("text").strip()
        if len(embedded_text) >= _MIN_TEXT_CHARS:
            pages_text.append(embedded_text)
            continue

        # --- Step 2: Image-based page — use pytesseract ---
        pages_text.append(_ocr_page(page, page_num + 1))

    doc.close()

    full_text = "\n\n".join(pages_text).strip()
    char_count = len(full_text)
    logger.log(f"OCR: extracted {char_count} characters from {total_pages} page(s)", "success")
    return full_text if full_text else None


def _ocr_page(page, page_number: int) -> str:
    """Render a single PDF page to a PIL image and run Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image

        # Render at 200 DPI (good quality / speed tradeoff)
        mat = page.get_pixmap(matrix=page.get_displaylist().rect.irect, dpi=200)  # type: ignore[attr-defined]
        img_bytes = mat.tobytes("png")
        pil_image = Image.open(io.BytesIO(img_bytes))
        text = pytesseract.image_to_string(pil_image, lang="eng").strip()
        logger.log(f"OCR: page {page_number} tesseract extracted {len(text)} chars", "info")
        return text if text else f"[Page {page_number}: image content, no text extracted]"

    except pytesseract.TesseractNotFoundError:
        logger.log(
            "Tesseract OCR engine not found. Install from https://github.com/UB-Mannheim/tesseract/wiki",
            "warn",
        )
        return f"[Page {page_number}: image-based — install Tesseract for OCR]"
    except Exception as e:
        logger.log(f"OCR: page {page_number} OCR failed: {e}", "warn")
        return f"[Page {page_number}: OCR error — {e}]"
