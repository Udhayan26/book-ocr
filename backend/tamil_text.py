"""Tamil-aware text cleanup and the symbol catalogue used by the dashboard palette.

Everything here is pure Unicode handling — no network, no paid service.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Symbol catalogue
# ---------------------------------------------------------------------------
# Tamil block extras (U+0B80–U+0BFF): digits, numbers, calendar/accounting signs, OM, aytham
TAMIL_BLOCK_EXTRAS = (
    [0x0B83, 0x0BD0]                      # ஃ aytham, ௐ OM
    + list(range(0x0BE6, 0x0BF0))         # ௦–௯ Tamil digits
    + list(range(0x0BF0, 0x0BFB))         # ௰ ௱ ௲ + ௳ ௴ ௵ ௶ ௷ ௸ ௹ ௺
)
# Tamil Supplement block (U+11FC0–U+11FFF): fractions, measures, accounting & clerical marks
TAMIL_SUPPLEMENT = list(range(0x11FC0, 0x11FF2)) + [0x11FFF]


def _entry(cp: int) -> dict | None:
    ch = chr(cp)
    try:
        name = unicodedata.name(ch)
    except ValueError:  # unassigned in this Python's Unicode version
        return None
    return {"char": ch, "code": f"U+{cp:04X}", "name": name.title()}


def symbol_catalogue() -> list[dict]:
    groups = [
        ("Tamil digits & signs", TAMIL_BLOCK_EXTRAS),
        ("Tamil Supplement (fractions, measures, clerical)", TAMIL_SUPPLEMENT),
        ("Punctuation", [0x2018, 0x2019, 0x201C, 0x201D, 0x2013, 0x2014, 0x2026, 0x0964, 0x0965, 0x00B7]),
    ]
    out = []
    for title, cps in groups:
        items = [e for e in (_entry(cp) for cp in cps) if e]
        out.append({"group": title, "symbols": items})
    return out


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
TA_CONSONANT = "க-ஹ"
TA_PREFIX_SIGNS = "ெேை"  # ெ ே ை — drawn before the consonant
_ZW_JUNK = re.compile("[​⁠﻿◌]")   # zero-width space/joiner junk, dotted circle
_ZWNJ_AFTER_PULLI = re.compile("\u0BCD[\u200C\u200D]")  # Tesseract appends ZWNJ after ் — never needed in Tamil
_PREFIX_FIX = re.compile(rf"(^|[^{TA_CONSONANT}்])([{TA_PREFIX_SIGNS}])([{TA_CONSONANT}])")
_SPACE_BEFORE_SIGN = re.compile(r"([க-ஹ]) +([ா-்ௗ])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def clean_tamil(text: str) -> str:
    """Fix common OCR artefacts in Tamil text while leaving English untouched."""
    if not text:
        return text
    t = _ZW_JUNK.sub("", text)
    t = _ZWNJ_AFTER_PULLI.sub("\u0BCD", t)
    # Vowel sign recognised in *visual* order (ெ before the consonant) -> logical order
    t = _PREFIX_FIX.sub(lambda m: m.group(1) + m.group(3) + m.group(2), t)
    # Stray space between a consonant and its vowel sign
    t = _SPACE_BEFORE_SIGN.sub(r"\1\2", t)
    # Two-part vowel signs (ெ+ா -> ொ, ே+ா -> ோ, ெ+ௗ -> ௌ) are composed by NFC
    t = unicodedata.normalize("NFC", t)
    t = _MULTI_SPACE.sub(" ", t)
    return t


def apply_rules(text: str, rules: list[dict]) -> str:
    """User-defined find/replace rules, e.g. map an OCR misread to a Tamil Supplement symbol."""
    for r in rules or []:
        find = r.get("find", "")
        if not find or not r.get("enabled", True):
            continue
        repl = r.get("replace", "")
        if r.get("regex"):
            try:
                text = re.sub(find, repl, text)
            except re.error:
                continue
        else:
            text = text.replace(find, repl)
    return text


def script_mix(text: str) -> dict:
    """Rough share of Tamil vs Latin letters on a page — shown in the dashboard."""
    ta = sum(1 for c in text if "஀" <= c <= "௿" or "\U00011FC0" <= c <= "\U00011FFF")
    la = sum(1 for c in text if c.isascii() and c.isalpha())
    total = ta + la or 1
    return {"tamil": round(ta / total, 3), "latin": round(la / total, 3)}
