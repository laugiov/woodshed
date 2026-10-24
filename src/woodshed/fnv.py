"""FNV-1a, 32 bits: the keys the band's corrections are kept under, the same in Python and in the page."""

from __future__ import annotations


def fnv1a(text: str) -> str:
    """fnv1a in the page (app.js, core/wordedits.js), over UTF-16 code units as charCodeAt reads them."""
    h = 0x811C9DC5
    units = text.encode("utf-16-le")
    for i in range(0, len(units), 2):
        h = ((h ^ int.from_bytes(units[i : i + 2], "little")) * 0x01000193) & 0xFFFFFFFF
    return format(h, "x")
