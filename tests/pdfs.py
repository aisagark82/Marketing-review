"""Build small test PDFs with reportlab."""

import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make_pdf(
    pages: list[list[str]],
    *,
    title="",
    author="",
    subject="",
    bookmarks=(),
    image_page=False,
    encrypt: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, encrypt=encrypt)
    pdf.setTitle(title)
    pdf.setAuthor(author)
    pdf.setSubject(subject)
    for number, lines in enumerate(pages):
        y = 780
        for line in lines:
            pdf.drawString(72, y, line)
            y -= 20
        for label, page_index in bookmarks:
            if page_index == number:
                pdf.bookmarkPage(label)
                pdf.addOutlineEntry(label, label, level=0)
        pdf.showPage()
    if image_page:  # a "scanned" page: drawing only, no text layer
        pdf.rect(72, 400, 400, 300, fill=1)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
