"""PDF text, properties and bookmarks with pypdfium2 (PDFium, the engine in Chrome).

Docling (design §5.2) is kept for later: it pulls in PyTorch, which is a heavy install for a
laptop, and PDFs with a text layer don't need it. Pages without a text layer are listed as
needing OCR, which arrives with image OCR.
"""

from dataclasses import dataclass, field

import pypdfium2 as pdfium

EXTRACTOR = f"pypdfium2/{pdfium.PYPDFIUM_INFO}"
METADATA_FIELDS = ("Title", "Author", "Subject", "Keywords")
MIN_CHARS_FOR_TEXT_LAYER = 10
MAX_SEGMENTS = 50_000
MAX_BOOKMARKS = 2_000


class PdfError(Exception):
    """The file can't be read as a PDF (damaged, encrypted, not a PDF)."""


@dataclass
class PdfExtraction:
    segments: list[dict] = field(default_factory=list)
    pages: int = 0
    pages_without_text: list[int] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def needs_ocr(self) -> bool:
        return bool(self.pages_without_text)

    def info(self) -> dict:
        return {
            "pages": self.pages,
            "pages_without_text": self.pages_without_text[:200],
            "needs_ocr": self.needs_ocr,
            "metadata": self.metadata,
        }


def _lines(text: str):
    """(start, end) of each non-empty line; PDFium separates lines with \\r\\n."""
    start = 0
    for index, char in enumerate(text + "\n"):
        if char in "\r\n":
            if text[start:index].strip():
                yield start, index
            start = index + 1


def _line_box(textpage, text: str, start: int, end: int) -> list[float] | None:
    first = start + (len(text[start:end]) - len(text[start:end].lstrip()))
    last = end - 1 - (len(text[start:end]) - len(text[start:end].rstrip()))
    try:
        left, bottom, right, top = textpage.get_charbox(first)
        l2, b2, r2, t2 = textpage.get_charbox(last)
    except Exception:
        return None
    return [round(v, 1) for v in (min(left, l2), min(bottom, b2), max(right, r2), max(top, t2))]


def extract_pdf(data: bytes) -> PdfExtraction:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        message = str(exc)
        if "password" in message.lower():
            raise PdfError("the PDF is password-protected") from exc
        raise PdfError(f"not a readable PDF ({message})") from exc

    result = PdfExtraction(pages=len(pdf))
    add = result.segments.append
    try:
        meta = pdf.get_metadata_dict(skip_empty=True)
        for name in METADATA_FIELDS:
            value = (meta.get(name) or "").strip()
            if value:
                result.metadata[name.lower()] = value
                add(
                    {
                        "text": value,
                        "source": f"pdf_meta:{name.lower()}",
                        "visibility": "metadata",
                        "locator": {"property": name},
                    }
                )

        for count, bookmark in enumerate(pdf.get_toc(max_depth=8)):
            if count >= MAX_BOOKMARKS:
                break
            title = (bookmark.get_title() or "").strip()
            if title:
                page = bookmark.get_dest().get_index() if bookmark.get_dest() else None
                add(
                    {
                        "text": title,
                        "source": "pdf_bookmark",
                        "visibility": "metadata",
                        "locator": {"page": page + 1 if page is not None else None},
                    }
                )

        for number in range(len(pdf)):
            page = pdf[number]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            if len(text.strip()) < MIN_CHARS_FOR_TEXT_LAYER:
                result.pages_without_text.append(number + 1)
            size = [round(v, 1) for v in page.get_size()]
            aligned = len(text) == textpage.count_chars()  # boxes need 1:1 character indices
            for start, end in _lines(text):
                if len(result.segments) >= MAX_SEGMENTS:
                    break
                add(
                    {
                        "text": " ".join(text[start:end].split()),
                        "source": "pdf_text",
                        "visibility": "visible",
                        "locator": {
                            "page": number + 1,
                            "bbox": _line_box(textpage, text, start, end) if aligned else None,
                            "page_size": size,
                        },
                    }
                )
            textpage.close()
            page.close()
    finally:
        pdf.close()
    return result
