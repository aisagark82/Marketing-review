import pytest
from pydantic import ValidationError

from brandguard.rules.brand_name import BrandNameConfig, BrandNameRule, market_of, normalize
from brandguard.rules.defaults import PFIZER_BRAND_NAME

RULE = BrandNameRule(BrandNameConfig(**PFIZER_BRAND_NAME))


def check(text, language=None):
    return [(m.kind, m.matched, m.status) for m in RULE.check(text, language)]


@pytest.mark.parametrize(
    "text",
    [
        "Pfizer is a research-based company.",
        "PFIZER",  # D13: all caps allowed
        "Pfizer's pipeline",
        "the Pfizer-BioNTech vaccine",  # D14: attached forms pass if Pfizer is right
        "PfizerPro for professionals",
        "Visit https://www.pfizer.com/news or www.pfizer.com",
        "Write to press@pfizer.com",
        "Follow @pfizer and #pfizer",
        "Download pfizer-annual-report.pdf",
        "pfizer.com and pfizerpro.com",
        "Pfizer Inc. (NYSE: PFE)",
        "",
    ],
)
def test_correct_uses_pass(text):
    assert check(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("at pfizer we believe", [("casing", "pfizer", "violation")]),
        ("PFizer Oncology", [("casing", "PFizer", "violation")]),
        ("pFIZER", [("casing", "pFIZER", "violation")]),
        ("pfizer's pipeline", [("casing", "pfizer", "violation")]),
        (
            "Phizer and PHIZER",
            [("disallowed", "Phizer", "violation"), ("disallowed", "PHIZER", "violation")],
        ),
        ("made by P-fizer", [("disallowed", "P-fizer", "violation")]),
        ("Pfi zer vaccine", [("split", "Pfi zer", "violation")]),
        ("Pfi-zer vaccine", [("split", "Pfi-zer", "violation")]),
        ("Pfzier today", [("near_miss", "Pfzier", "ambiguous")]),  # swapped letters
        ("Pfizr today", [("near_miss", "Pfizr", "ambiguous")]),
        ("Pfizzer", [("disallowed", "Pfizzer", "violation")]),  # listed, so not just a near-miss
    ],
)
def test_violations(text, expected):
    assert check(text) == expected


def test_offsets_point_into_the_original_text():
    text = "Welcome to ｐｆｉｚｅｒ today"  # full-width letters
    [match] = RULE.check(text)
    assert match.kind == "casing"
    assert text[match.start : match.end] == "ｐｆｉｚｅｒ"
    assert match.matched == "ｐｆｉｚｅｒ"
    assert match.expected == "Pfizer"


def test_full_width_correct_name_passes():
    assert check("ＰＦＩＺＥＲ and Ｐｆｉｚｅｒ") == []


def test_zero_width_and_soft_hyphen_are_ignored():
    assert check("Pfi​zer and Pfi­zer") == []
    [match] = RULE.check("pfi​zer")
    assert match.matched == "pfi​zer"


def test_context_snippet():
    text = "x" * 100 + " pfizer " + "y" * 100
    [match] = RULE.check(text)
    assert match.context(text).startswith("…") and " pfizer " in match.context(text)


def test_urls_can_be_checked_when_the_exception_is_off():
    config = BrandNameConfig(**(PFIZER_BRAND_NAME | {"exceptions": ["emails"]}))
    assert [m.matched for m in BrandNameRule(config).check("www.pfizer.com")] == ["pfizer"]


def test_ignore_words_silence_near_misses():
    config = BrandNameConfig(**(PFIZER_BRAND_NAME | {"ignore_words": ["Pfizr"]}))
    assert BrandNameRule(config).check("Pfizr") == []


def test_fuzzy_can_be_switched_off():
    config = BrandNameConfig(**(PFIZER_BRAND_NAME | {"fuzzy": {"enabled": False}}))
    assert BrandNameRule(config).check("Pfzier") == []


def test_attached_forms_can_be_disallowed():
    config = BrandNameConfig(**(PFIZER_BRAND_NAME | {"attached_forms_ok": False}))
    assert [m.matched for m in BrandNameRule(config).check("PfizerPro and Pfizer")] == ["PfizerPro"]


def test_short_and_distant_words_are_not_near_misses():
    assert check("Fizz, prize, sizer, Pfennig, fire, the") == []


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        ("ファイザーの新薬", "ja", []),
        ("ファイザの新薬", "ja", [("disallowed", "ファイザ", "violation")]),
        ("ファイザ―の新薬", "ja", [("disallowed", "ファイザ―", "violation")]),  # dash look-alike
        ("辉瑞中国", "zh-CN", []),
        (
            "輝瑞中国",
            "zh-CN",
            [("disallowed", "輝瑞", "violation")],
        ),  # Traditional on a Simplified page
        ("輝瑞台灣", "zh-TW", []),
        ("辉瑞 on a Japanese page", "ja", [("wrong_market_form", "辉瑞", "violation")]),
        ("Pfizer ファイザー", "ja", []),
        ("輝瑞 and 辉瑞", None, []),  # market unknown: both are approved somewhere
        ("ファイザ", None, [("disallowed", "ファイザ", "violation")]),  # approved nowhere
    ],
)
def test_local_script_names(text, language, expected):
    assert check(text, language) == expected


def test_wrong_market_form_uses_configured_severity():
    [match] = RULE.check("辉瑞", "ja")
    assert match.severity == "low"
    assert match.expected == "ファイザー"


def test_market_of():
    assert market_of("en-US") == "en"
    assert market_of("zh-CN") == "zh-Hans"
    assert market_of("zh-Hant-TW") == "zh-Hant"
    assert market_of("zh-hk") == "zh-Hant"
    assert market_of(None) is None


def test_normalize_maps_back_to_original():
    norm, origin = normalize("ﬁ​x")
    assert norm == "fix"
    assert origin == [0, 0, 2, 3]


def test_config_validation():
    with pytest.raises(ValidationError, match="spell the name exactly"):
        BrandNameConfig(canonical="Pfizer", allowed_casings=["Pfizer", "Pfiser"])
    with pytest.raises(ValidationError, match="is a casing of the name"):
        BrandNameConfig(canonical="Pfizer", disallowed=["pfizer"])
    config = BrandNameConfig(canonical="Pfizer", allowed_casings=["PFIZER"])
    assert config.allowed_casings == ["Pfizer", "PFIZER"]  # the canonical form is always allowed
