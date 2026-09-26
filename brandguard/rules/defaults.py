"""The starting Pfizer brand-name rule (design §3.1, D13, D14)."""

PFIZER_BRAND_NAME = {
    "canonical": "Pfizer",
    "allowed_casings": ["Pfizer", "PFIZER"],  # D13: title case and all caps
    "disallowed": ["Phizer", "Pfiser", "Pfzer", "Pifzer", "Pfizzer", "Fizer", "P-fizer"],
    "attached_forms_ok": True,  # D14: "Pfizer's", "Pfizer-BioNTech" pass if "Pfizer" is right
    "fuzzy": {"enabled": True, "max_edit_distance": 1},
    "ignore_words": [],
    "exceptions": ["urls", "emails", "file_names", "domains", "handles", "hashtags"],
    "locales": {
        "ja": {
            "approved": ["Pfizer", "PFIZER", "ファイザー"],
            "disallowed": ["ファイザ", "ファイザ―"],
        },
        "zh-Hans": {"approved": ["Pfizer", "PFIZER", "辉瑞"], "disallowed": ["輝瑞"]},
        "zh-Hant": {"approved": ["Pfizer", "PFIZER", "輝瑞"], "disallowed": ["辉瑞"]},
    },
    "cross_market": "low",
}
