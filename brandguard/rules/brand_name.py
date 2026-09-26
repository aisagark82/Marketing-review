"""The brand-name rule (design §3.1, §5.5, D13, D14): is the name spelled right everywhere?

The check runs on NFKC-normalized text (full-width letters, ligatures, zero-width characters
handled) but reports character offsets in the original text, so matches can be highlighted.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from rapidfuzz.distance import DamerauLevenshtein

ExceptionKind = Literal["urls", "emails", "file_names", "domains", "handles", "hashtags"]
ALL_EXCEPTIONS: list[ExceptionKind] = [
    "urls",
    "emails",
    "file_names",
    "domains",
    "handles",
    "hashtags",
]

# Applied in this order; each masks its matches so later patterns and the checks skip them.
EXCEPTION_PATTERNS: dict[str, re.Pattern] = {
    "urls": re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE),
    "emails": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "file_names": re.compile(
        r"\b[\w-]+\.(?:pdf|docx?|pptx?|xlsx?|csv|jpe?g|png|gif|svg|webp|mp4|mp3|zip)\b",
        re.IGNORECASE,
    ),
    "domains": re.compile(
        r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|co|io|us|uk|de|jp|cn|es|fr|it|ca|au|in|info|biz|health)\b",
        re.IGNORECASE,
    ),
    "handles": re.compile(r"(?<![\w@])@\w+"),
    "hashtags": re.compile(r"(?<![\w#])#\w+"),
}
ZERO_WIDTH = frozenset("​‌‍⁠﻿­")
WORD = re.compile(r"[^\W\d_]+")
SPLIT_SEPARATORS = frozenset(" -.·‐‑")
CONTEXT_CHARS = 40
MIN_FUZZY_LENGTH = 4

Kind = Literal["casing", "disallowed", "split", "near_miss", "wrong_market_form"]


class LocaleForms(BaseModel):
    approved: list[str] = []
    disallowed: list[str] = []


class FuzzyConfig(BaseModel):
    enabled: bool = True
    max_edit_distance: int = Field(1, ge=1, le=2)


class BrandNameConfig(BaseModel):
    canonical: str = Field(min_length=2, max_length=100)
    allowed_casings: list[str] = []
    disallowed: list[str] = []
    attached_forms_ok: bool = True  # "Pfizer's", "Pfizer-BioNTech", "PfizerPro" (D14)
    fuzzy: FuzzyConfig = FuzzyConfig()
    ignore_words: list[str] = []  # real words that happen to be near-misses
    exceptions: list[ExceptionKind] = list(ALL_EXCEPTIONS)
    locales: dict[str, LocaleForms] = {}
    cross_market: Literal["off", "low", "medium", "high"] = "low"

    @field_validator("allowed_casings", "disallowed", "ignore_words")
    @classmethod
    def _clean(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))

    @model_validator(mode="after")
    def _casings_spell_the_name(self) -> "BrandNameConfig":
        if self.canonical not in self.allowed_casings:
            self.allowed_casings.insert(0, self.canonical)
        wrong = [c for c in self.allowed_casings if c.casefold() != self.canonical.casefold()]
        if wrong:
            raise ValueError(
                "allowed casings must spell the name exactly, only in different letter case: "
                + ", ".join(wrong)
            )
        clash = [d for d in self.disallowed if d.casefold() == self.canonical.casefold()]
        if clash:
            raise ValueError(
                f"{clash[0]!r} is a casing of the name; remove it from allowed casings instead"
            )
        return self


@dataclass
class Match:
    kind: Kind
    start: int  # offsets in the original text
    end: int
    matched: str
    expected: str
    status: Literal["violation", "ambiguous"]
    severity: str
    confidence: float
    note: str

    def context(self, text: str) -> str:
        left = max(0, self.start - CONTEXT_CHARS)
        right = min(len(text), self.end + CONTEXT_CHARS)
        return ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")


def normalize(text: str) -> tuple[str, list[int]]:
    """NFKC per character, zero-width characters removed; returns the text and, for each
    normalized character, its index in the original (plus a final end index)."""
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        if char in ZERO_WIDTH:
            continue
        for normalized in unicodedata.normalize("NFKC", char):
            chars.append(normalized)
            origin.append(index)
    origin.append(len(text))
    return "".join(chars), origin


def market_of(language: str | None) -> str | None:
    """'zh-CN' -> 'zh-Hans', 'zh-TW' -> 'zh-Hant', 'en-US' -> 'en'."""
    if not language:
        return None
    lang = language.strip().replace("_", "-").lower()
    if lang.startswith("zh"):
        return "zh-Hant" if any(t in lang for t in ("hant", "-tw", "-hk", "-mo")) else "zh-Hans"
    return lang.split("-")[0] or None


def is_latin(form: str) -> bool:
    return all(ord(c) < 0x250 for c in form if c.isalpha())


class BrandNameRule:
    def __init__(self, config: BrandNameConfig, severity: str = "high"):
        self.config = config
        self.severity = severity
        self.canonical = config.canonical
        self.canonical_key = config.canonical.casefold()
        self.allowed = set(config.allowed_casings)
        self.ignore = {w.casefold() for w in config.ignore_words}
        # Disallowed spellings: one-word ones are compared per word, others by pattern.
        self.disallowed_words = {d.casefold(): d for d in config.disallowed if WORD.fullmatch(d)}
        self.disallowed_patterns = [
            (
                re.compile(
                    r"(?<!\w)" + r"\s+".join(map(re.escape, d.split())) + r"(?!\w)", re.IGNORECASE
                ),
                d,
            )
            for d in config.disallowed
            if not WORD.fullmatch(d) and is_latin(d)
        ]
        self.cross_market_severity = None if config.cross_market == "off" else config.cross_market
        self.market_forms = self._market_forms()

    def _market_forms(self) -> list[tuple[str, str, str]]:
        """Non-Latin forms as (form, market, 'approved'|'disallowed'), longest first."""
        forms = []
        for market, spec in self.config.locales.items():
            forms += [(f, market, "approved") for f in spec.approved if not is_latin(f)]
            forms += [(f, market, "disallowed") for f in spec.disallowed if not is_latin(f)]
        return sorted(forms, key=lambda item: -len(item[0]))

    # --- public -----------------------------------------------------------------------------
    def check(self, text: str, language: str | None = None) -> list[Match]:
        norm, origin = normalize(text)
        masked = self._mask_exceptions(norm)
        taken: list[tuple[int, int]] = []  # normalized spans already reported
        matches: list[Match] = []

        def report(
            kind: Kind,
            start: int,
            end: int,
            expected: str,
            note: str,
            status="violation",
            severity=None,
            confidence=1.0,
        ) -> None:
            taken.append((start, end))
            o_start, o_end = origin[start], origin[end - 1] + 1
            matches.append(
                Match(
                    kind,
                    o_start,
                    o_end,
                    text[o_start:o_end],
                    expected,
                    status,
                    severity or self.severity,
                    round(confidence, 3),
                    note,
                )
            )

        def free(start: int, end: int) -> bool:
            return all(end <= s or start >= e for s, e in taken)

        for pattern, spelling in self.disallowed_patterns:
            for m in pattern.finditer(masked):
                if free(m.start(), m.end()):
                    report(
                        "disallowed",
                        m.start(),
                        m.end(),
                        self.canonical,
                        f'"{spelling}" is a disallowed spelling',
                    )

        words = list(WORD.finditer(masked))
        self._check_split(words, masked, report, free)
        for word in words:
            if free(word.start(), word.end()):
                self._check_word(word, report)
        self._check_market_forms(masked, market_of(language), report, free, taken)
        return sorted(matches, key=lambda m: m.start)

    # --- steps ------------------------------------------------------------------------------
    def _mask_exceptions(self, text: str) -> str:
        for kind in self.config.exceptions:
            text = EXCEPTION_PATTERNS[kind].sub(lambda m: " " * len(m.group()), text)
        return text

    def _check_split(self, words, text: str, report, free) -> None:
        """'Pfi zer', 'Pfi-zer': the name broken into two words."""
        for first, second in zip(words, words[1:], strict=False):
            gap = text[first.end() : second.start()]
            joined = (first.group() + second.group()).casefold()
            split = len(gap) == 1 and gap in SPLIT_SEPARATORS and joined == self.canonical_key
            if split and free(first.start(), second.end()):
                report(
                    "split",
                    first.start(),
                    second.end(),
                    self.canonical,
                    "the name is split into two words",
                )

    def _check_word(self, word: re.Match, report) -> None:
        token = word.group()
        key = token.casefold()
        position = key.find(self.canonical_key)
        if position != -1:
            if key != self.canonical_key and not self.config.attached_forms_ok:
                report(
                    "casing",
                    word.start(),
                    word.end(),
                    self.canonical,
                    "the name is joined to another word",
                )
                return
            while position != -1:
                part = token[position : position + len(self.canonical)]
                if part not in self.allowed:
                    start = word.start() + position
                    report(
                        "casing",
                        start,
                        start + len(part),
                        self.canonical,
                        f"wrong letter case (allowed: {', '.join(sorted(self.allowed))})",
                    )
                position = key.find(self.canonical_key, position + len(self.canonical))
            return
        if key in self.disallowed_words:
            report(
                "disallowed",
                word.start(),
                word.end(),
                self.canonical,
                f'"{self.disallowed_words[key]}" is a disallowed spelling',
            )
            return
        fuzzy = self.config.fuzzy
        if (
            fuzzy.enabled
            and len(key) >= MIN_FUZZY_LENGTH
            and key not in self.ignore
            and abs(len(key) - len(self.canonical_key)) <= fuzzy.max_edit_distance
        ):
            distance = DamerauLevenshtein.distance(key, self.canonical_key)
            if 0 < distance <= fuzzy.max_edit_distance:
                similarity = DamerauLevenshtein.normalized_similarity(key, self.canonical_key)
                report(
                    "near_miss",
                    word.start(),
                    word.end(),
                    self.canonical,
                    f"looks like a misspelling of {self.canonical} ({distance} letter off)",
                    status="ambiguous",
                    severity="medium",
                    confidence=similarity,
                )

    def _check_market_forms(self, text: str, market: str | None, report, free, taken) -> None:
        """Local-script names (ファイザー, 辉瑞, 輝瑞): approved or disallowed per market.

        Longest forms first, and every occurrence claims its span, so a disallowed form that
        is part of a longer approved one (ファイザ in ファイザー) isn't reported.
        """
        locales = self.config.locales
        for form, form_market, status in self.market_forms:
            start = text.find(form)
            while start != -1:
                end = start + len(form)
                if free(start, end):
                    self._judge_market_form(
                        form, form_market, status, market, locales, start, end, report
                    )
                    taken.append((start, end))
                start = text.find(form, end)

    def _judge_market_form(self, form, form_market, status, market, locales, start, end, report):
        here = locales.get(market) if market else None
        expected = next(
            (f for f in (here.approved if here else []) if not is_latin(f)), self.canonical
        )
        if here is not None:
            if form in here.disallowed:
                report(
                    "disallowed",
                    start,
                    end,
                    expected,
                    f'"{form}" is a disallowed spelling in {market}',
                )
            elif form in here.approved:
                return  # correct for this market
            elif status == "approved" and self.cross_market_severity:
                report(
                    "wrong_market_form",
                    start,
                    end,
                    expected,
                    f'"{form}" is the {form_market} name, on a {market} page',
                    severity=self.cross_market_severity,
                )
            return
        # Market unknown or not configured: only flag forms that no market approves.
        approved_anywhere = any(form in spec.approved for spec in locales.values())
        if status == "disallowed" and not approved_anywhere:
            report("disallowed", start, end, expected, f'"{form}" is a disallowed spelling')
