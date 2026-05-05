from __future__ import annotations

import re
import unicodedata


GENERIC_PHRASES = [
    "sản phẩm tốt",
    "hàng ok",
    "ok nha",
    "ổn áp",
    "đóng gói đẹp",
    "giao hàng nhanh",
    "rất hài lòng",
    "đáng tiền",
    "tuyệt vời",
    "shop uy tín",
    "chất lượng tốt",
]


def clean_text(text: str | None) -> str:
    """Normalize Vietnamese review text while preserving accents."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", str(text)).lower()
    normalized = re.sub(r"https?://\S+|www\.\S+", " ", normalized)
    normalized = re.sub(r"[\U00010000-\U0010ffff]", " ", normalized)
    normalized = normalize_repeated_chars(normalized)
    normalized = re.sub(r"[^\w\sÀ-ỹ!?.,%+-]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def count_words(text: str | None) -> int:
    return len(clean_text(text).split())


def caps_ratio(text: str | None) -> float:
    if not text:
        return 0.0
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isupper() for char in letters) / len(letters)


def has_generic_phrase(text: str | None, phrases: list[str] | None = None) -> bool:
    cleaned = clean_text(text)
    return any(phrase in cleaned for phrase in (phrases or GENERIC_PHRASES))


def is_only_generic(text: str | None, phrases: list[str] | None = None) -> bool:
    """True if the entire review is only generic phrases with no specific detail."""
    cleaned = clean_text(text)
    if not cleaned:
        return False
    remaining = cleaned
    for phrase in (phrases or GENERIC_PHRASES):
        remaining = remaining.replace(phrase, "")
    # Strip punctuation and whitespace from what's left
    remaining = re.sub(r"[^\w]", "", remaining)
    return len(remaining) < 5


def normalize_repeated_chars(text: str | None, max_repeats: int = 2) -> str:
    if not text:
        return ""
    return re.sub(r"([A-Za-zÀ-ỹ])\1{%s,}" % max_repeats, lambda match: match.group(1) * max_repeats, str(text))


def is_noise_text(text: str | None) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return True
    alpha_chars = [char for char in cleaned if char.isalpha()]
    return len(alpha_chars) < 3
