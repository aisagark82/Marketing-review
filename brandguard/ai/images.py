"""Gemini reads the text in a raster image (banners, logos, infographics)."""

from pydantic import BaseModel

from brandguard.ai.llm import Gemini, Image
from brandguard.ai.prompts import IMAGE_TEXT_SYSTEM

STAGE = "image_text"
MAX_LINES = 200


class ImageText(BaseModel):
    lines: list[str]


def image_text_reader(gemini: Gemini, run_id: int | None = None):
    """A function (image bytes, MIME type) -> lines of text, for the file-processing step."""

    def read(data: bytes, mime_type: str) -> list[str]:
        answer = gemini.generate_json(
            STAGE,
            IMAGE_TEXT_SYSTEM,
            [Image(data, mime_type)],
            ImageText,
            max_output_tokens=2048,
            run_id=run_id,
        ).data
        return [line.strip() for line in answer.lines[:MAX_LINES] if line.strip()]

    return read
