"""How woodshed 0.5.x reads and writes the words fixed on the sheet in a corrections file: the functions of
src/woodshed/app.py at commit 3746c1f (main after PR #48), copied verbatim below the marker; only the write
rule at the end is a summary of its write_corrections (every section it does not know written back as it is,
`words` as it read it). The split and join tests (tests/test_split_join.py) round-trip a file through it."""

from __future__ import annotations

import contextlib
import json
import math
import re
from pathlib import Path
from typing import Any

WORDS_BYTES = 32 * 1024  # the pasted words of one song: a long song is 3 KB
LINE_INDEX = re.compile(r"0|[1-9][0-9]{0,3}")
WORD_TEXT_MAX = 200  # code points of one line
LINE_WORDS_MAX = 40

# --- verbatim from 3746c1f:src/woodshed/app.py ---


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _checked_word_entry(k: Any, v: Any) -> dict[str, Any]:
    """A fix of the words as the library keeps it: the placement's text (`was`), then the line's words and
    times placed by the library, another voice, or not in this recording."""
    if not isinstance(k, str) or not LINE_INDEX.fullmatch(k) or not isinstance(v, dict):
        raise ValueError("a line fix by index")
    was = v.get("was")
    if not isinstance(was, str) or len(was) > 4 * WORDS_BYTES:
        raise ValueError("was: the placement's text")
    if set(v) == {"was", "gone"} and v["gone"] == "not-sung":
        return {"was": was, "gone": "not-sung"}
    if not set(v) <= {"was", "lines", "voice"} or len(v) < 2 or v.get("voice", "other") != "other":
        raise ValueError("a line fix")
    out: dict[str, Any] = {"was": was}
    if "lines" in v:
        fixed = v["lines"]
        if not isinstance(fixed, list) or len(fixed) != 1:
            raise ValueError("lines: one line")
        line = fixed[0]
        text, words, check, backing = line["text"], line["words"], line.get("check"), line.get("backing", [])
        if not isinstance(text, str) or len(text) > WORD_TEXT_MAX or not isinstance(words, list):
            raise ValueError("lines: words")
        if not 0 < len(words) <= LINE_WORDS_MAX or not (check is None or (isinstance(check, str) and len(check) < 200)):
            raise ValueError("lines: words")
        if not isinstance(backing, list) or not all(isinstance(b, str) and len(b) <= WORD_TEXT_MAX for b in backing):
            raise ValueError("lines: backing vocals")
        kept = []
        for w in words:
            start, end = w["start"], w["end"]
            timed = _number(start) and _number(end) and 0 <= start <= end < 86400
            if not isinstance(w["text"], str) or len(w["text"]) > WORD_TEXT_MAX or not (timed or start is end is None):
                raise ValueError("lines: words in time")
            kept.append({"text": w["text"], "start": start, "end": end})
        out["lines"] = [{"text": text, "backing": list(backing), "words": kept, "check": check}]
    if "voice" in v:
        out["voice"] = "other"
    return out


# --- end of the verbatim copy ---


def read_words(path: Path) -> dict[str, Any]:
    """The `words` section as read_corrections of 3746c1f reads it (its loop, verbatim)."""
    out: dict[str, Any] = {"words": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    fixed = data.get("words")
    for key, entry in fixed.items() if isinstance(fixed, dict) else []:
        if not isinstance(entry, dict) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", str(key)):
            continue
        lines: dict[str, Any] = {}
        removed: dict[str, Any] = {}
        for k, v in entry.get("lines", {}).items() if isinstance(entry.get("lines"), dict) else []:
            with contextlib.suppress(ValueError, KeyError, TypeError, AttributeError):
                lines[k] = _checked_word_entry(k, v)  # one damaged by hand is skipped, the others kept
        for k, v in entry.get("removed", {}).items() if isinstance(entry.get("removed"), dict) else []:
            if isinstance(k, str) and LINE_INDEX.fullmatch(k):
                try:
                    removed[k] = None if v is None else _checked_word_entry(k, v)
                except (ValueError, KeyError, TypeError, AttributeError):
                    removed[k] = None
        at = entry.get("at", 0)
        out["words"][key] = {"lines": lines, "removed": removed, "at": float(at) if _number(at) else 0.0}
    found: dict[str, Any] = out["words"]
    return found


def write_words(path: Path, words: dict[str, Any]) -> None:
    """write_corrections of 3746c1f in short: every section it does not know (`words_more`) written back as it
    is, `words` as it read it, the revision one up."""
    body = json.loads(path.read_text(encoding="utf-8"))
    body["rev"] = body.get("rev", 0) + 1
    if words:
        body["words"] = words
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
