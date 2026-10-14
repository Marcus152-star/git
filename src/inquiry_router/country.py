from __future__ import annotations

import re
import unicodedata
from typing import Literal


COUNTRY_ALIASES = {
    "russia": "Russia",
    "russian federation": "Russia",
    "俄罗斯": "Russia",
    "indonesia": "Indonesia",
    "印度尼西亚": "Indonesia",
    "印尼": "Indonesia",
    "israel": "Israel",
    "以色列": "Israel",
    "hungary": "Hungary",
    "匈牙利": "Hungary",
    "ukraine": "Ukraine",
    "乌克兰": "Ukraine",
    "united arab emirates": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "阿联酋": "United Arab Emirates",
    "colombia": "Colombia",
    "哥伦比亚": "Colombia",
    "turkey": "Turkey",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
    "土耳其": "Turkey",
    "slovenia": "Slovenia",
    "斯洛文尼亚": "Slovenia",
    "iran": "Iran",
    "iran, islamic republic of": "Iran",
    "伊朗": "Iran",
}

EXPLICIT_COUNTRY_PATTERN = re.compile(
    r"(?im)^\s*(?:country|country/region|国家|所在国家|pais|país)\s*:\s*(?P<value>[^\r\n]+)"
)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip()


def canonical_country(value: str) -> str:
    folded = _fold(value).strip(" .,:;()[]{}")
    for alias, canonical in sorted(COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        token = _fold(alias).strip(" .,:;()[]{}")
        if folded == token or re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", folded):
            return canonical
    return value.strip()


def extract_country(text: str) -> tuple[str, Literal["high", "low", "none"]]:
    explicit = EXPLICIT_COUNTRY_PATTERN.search(text)
    if explicit:
        raw = explicit.group("value").strip()
        canonical = canonical_country(raw)
        return canonical, "high"

    folded_text = _fold(text)
    for alias, canonical in COUNTRY_ALIASES.items():
        token = _fold(alias)
        if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", folded_text):
            return canonical, "low"
    return "", "none"

