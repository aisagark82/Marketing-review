import pytest

from brandguard.pipeline.extract.pdf import PdfError, extract_pdf
from tests.pdfs import make_pdf


def test_text_properties_and_bookmarks():
    data = make_pdf(
        [["Annual Review 2025", "At Phizer we believe", "PFIZER and Pfizer"], ["Page two text"]],
        title="Pfizer Annual Review",
        author="pfizer inc",
        bookmarks=[("Letter from the CEO", 0), ("Our science", 1)],
    )
    result = extract_pdf(data)
    assert result.pages == 2
    assert result.metadata == {"title": "Pfizer Annual Review", "author": "pfizer inc"}
    texts = [(s["text"], s["source"], s["visibility"]) for s in result.segments]
    assert ("pfizer inc", "pdf_meta:author", "metadata") in texts
    assert ("Letter from the CEO", "pdf_bookmark", "metadata") in texts
    assert ("At Phizer we believe", "pdf_text", "visible") in texts
    line = next(s for s in result.segments if s["text"] == "Page two text")
    assert line["locator"]["page"] == 2
    left, bottom, right, top = line["locator"]["bbox"]
    assert 70 < left < 75 and right > left and top > bottom
    assert line["locator"]["page_size"] == [595.3, 841.9]
    assert not result.needs_ocr


def test_pages_without_text_are_flagged_for_ocr():
    result = extract_pdf(make_pdf([["Some text on page one"]], image_page=True))
    assert result.pages_without_text == [2]
    assert result.needs_ocr
    assert result.info()["needs_ocr"] is True


def test_password_protected_pdf():
    with pytest.raises(PdfError, match="password"):
        extract_pdf(make_pdf([["secret"]], encrypt="letmein"))


def test_not_a_pdf():
    with pytest.raises(PdfError, match="not a readable PDF"):
        extract_pdf(b"<html>Not found</html>")
