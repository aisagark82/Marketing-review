"""Profile an uploaded dataset sample: schema detection, length stats, quality flags.

Token counts use a ~4 characters/token approximation (no tokenizer dependency). For exact
counts, profile with the target tokenizer in the generated pipeline.
"""

import csv
import hashlib
import io
import json
import re
from collections import Counter

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,14}\d(?!\d)")
SCHEMAS = [  # (schema id, required keys, data_kind)
    ("messages", {"messages"}, "sft"),
    ("preference", {"chosen", "rejected"}, "preference"),
    ("kto", {"prompt", "completion", "label"}, "binary_feedback"),
    ("alpaca", {"instruction", "output"}, "sft"),
    ("prompt_completion", {"prompt", "completion"}, "sft"),
    ("text_label", {"text", "label"}, "labels"),
    ("prompt_only", {"prompt", "answer"}, "verifiable"),
    ("prompt_only", {"prompt", "solution"}, "verifiable"),
    ("text", {"text"}, "raw_text"),
]


def parse(name, text):
    name = (name or "").lower()
    text = text.lstrip("﻿")
    if name.endswith(".csv") or name.endswith(".tsv"):
        dialect = "excel-tab" if name.endswith(".tsv") else "excel"
        return list(csv.DictReader(io.StringIO(text), dialect=dialect))
    stripped = text.strip()
    if stripped.startswith("["):
        data = json.loads(stripped)
        return data if isinstance(data, list) else [data]
    rows, bad = [], 0
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    if not rows and bad:
        raise ValueError("Could not parse as JSONL, JSON or CSV")
    return rows


def _text_of(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return " ".join(_text_of(x.get("content", "")) if isinstance(x, dict) else _text_of(x) for x in v)
    if isinstance(v, dict):
        return " ".join(_text_of(x) for x in v.values())
    return "" if v is None else str(v)


def _pct(xs, p):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def profile(name, text):
    rows = [r for r in parse(name, text) if isinstance(r, dict)]
    if not rows:
        raise ValueError("No records found")
    keys = Counter(k for r in rows for k in r)
    common = {k for k, c in keys.items() if c >= 0.9 * len(rows)}
    schema, kind = "text", "raw_text"
    for sid, req, dk in SCHEMAS:
        if req <= common:
            schema, kind = sid, dk
            break

    lengths, hashes, empties = [], Counter(), 0
    roles, labels, turns = Counter(), Counter(), []
    pii_email = pii_phone = 0
    for r in rows:
        t = _text_of(r)
        lengths.append(max(1, round(len(t) / 4)))
        hashes[hashlib.md5(t.strip().lower().encode()).hexdigest()] += 1
        if any(v in (None, "", []) for v in r.values()):
            empties += 1
        pii_email += bool(EMAIL.search(t))
        pii_phone += bool(PHONE.search(t))
        if schema == "messages" and isinstance(r.get("messages"), list):
            turns.append(len(r["messages"]))
            roles.update(m.get("role", "?") for m in r["messages"] if isinstance(m, dict))
        if "label" in r:
            labels[str(r["label"])] += 1

    n = len(rows)
    dupes = sum(c - 1 for c in hashes.values() if c > 1)
    p95 = _pct(lengths, 95)
    edges = [0, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 10 ** 9]
    hist = [dict(lo=edges[i], hi=edges[i + 1], count=sum(edges[i] <= x < edges[i + 1] for x in lengths)) for i in range(len(edges) - 1)]
    while hist and hist[-1]["count"] == 0:
        hist.pop()

    flags = []
    if dupes:
        flags.append(dict(level="warn", msg=f"{dupes} exact duplicates ({100 * dupes / n:.1f}%) — enable deduplication."))
    if empties:
        flags.append(dict(level="warn", msg=f"{empties} records have empty fields."))
    if pii_email or pii_phone:
        flags.append(dict(level="warn", msg=f"Possible PII: {pii_email} records with emails, {pii_phone} with phone numbers."))
    if labels and len(labels) > 1:
        top, low = labels.most_common()[0][1], labels.most_common()[-1][1]
        if top / max(low, 1) > 5:
            flags.append(dict(level="warn", msg=f"Label imbalance {top}:{low} — use stratified splits and class weighting."))
    if roles and roles.get("assistant", 0) == 0:
        flags.append(dict(level="error", msg="No assistant turns found in messages."))
    if n < 200:
        flags.append(dict(level="info", msg="Small sample — stats are indicative only."))

    avg = round(sum(lengths) / n)
    patch = dict(record_schema=schema, data_kind=kind, num_examples=n, avg_tokens=avg, p95_tokens=p95,
                 dedup="exact" if dupes else None, pii_scrub="regex" if (pii_email or pii_phone) else None,
                 split_strategy="stratified" if labels else None, num_labels=len(labels) if kind == "labels" else None)
    patch = {k: v for k, v in patch.items() if v is not None}
    return dict(
        rows=n, schema=schema, data_kind=kind, keys=dict(keys.most_common(20)),
        tokens=dict(avg=avg, p50=_pct(lengths, 50), p95=p95, max=max(lengths), total=sum(lengths)),
        histogram=hist, duplicates=dupes, empty_records=empties,
        roles=dict(roles), avg_turns=round(sum(turns) / len(turns), 1) if turns else None,
        labels=dict(labels.most_common(30)), flags=flags, sample=rows[:3], patch=patch,
    )
