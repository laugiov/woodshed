"""Which pages of a PDF printed by Chromium hold text: enough to tell a blank page (spec 014)."""

from __future__ import annotations

import re
import zlib


def pages_with_text(data: bytes) -> list[bool]:
    """One flag per page (in object order): True when its content streams draw text."""
    objs = {int(m.group(1)): m.group(2) for m in re.finditer(rb"(\d+) 0 obj(.*?)endobj", data, re.S)}

    def stream(n: int) -> bytes:
        body = objs[n]
        found = re.search(rb"stream\r?\n(.*?)\r?\nendstream", body, re.S)
        raw = found.group(1) if found else b""
        return zlib.decompress(raw) if b"FlateDecode" in body else raw

    out = []
    for body in (objs[n] for n in sorted(objs)):
        if not re.search(rb"/Type\s*/Page[^s]", body):
            continue
        contents = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+ 0 R)", body)
        refs = [int(x) for x in re.findall(rb"(\d+) 0 R", contents.group(1))] if contents else []
        out.append(any(re.search(rb"T[Jj]", stream(r)) for r in refs))
    return out
