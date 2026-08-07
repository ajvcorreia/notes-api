"""Serialize/parse Joplin's plain-text sync item format.

Joplin Server does not store notes/notebooks as structured DB rows - each
item is a flat text blob shaped like:

    <title>

    <body, notes only, may contain blank lines>

    key: value
    key: value
    ...
    type_: <1 note, 2 folder>

Verified empirically against a live joplin/server instance: exactly one
blank line must separate title from body (or from the property block, for
items with no body), the property block itself must contain no blank
lines, and the payload must NOT end with a trailing newline (a trailing
"\n" produces an extra empty last line that Joplin's parser reads as the
separator before any properties are seen, so it fails with
"Missing required property: type_").
"""
from __future__ import annotations

from datetime import datetime, timezone

TYPE_NOTE = 1
TYPE_FOLDER = 2
TYPE_RESOURCE = 4


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def serialize_item(title: str, body: str | None, props: dict[str, str]) -> str:
    parts = [title, ""]
    if body is not None:
        parts.append(body)
        parts.append("")
    parts.extend(f"{key}: {value}" for key, value in props.items())
    return "\n".join(parts)


def parse_item(content: str) -> dict[str, str]:
    """Inverse of serialize_item. Returns {"title": ..., "body": ..., **props}.

    Scans from the bottom and stops at the FIRST blank line - not just the
    first line without a colon. Body text legitimately contains lines with
    colons (e.g. a Joplin resource link "![x](:/<id>)"), so "no colon" alone
    is not a safe stop condition; only the blank line that separates body
    from the property block is.
    """
    lines = content.split("\n")
    props: dict[str, str] = {}
    idx = 0
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line == "":
            idx = i
            break
        if ":" not in line:
            idx = i + 1
            break
        key, _, value = line.partition(":")
        props[key.strip()] = value.strip()
        idx = i
    else:
        idx = 0

    body_lines = lines[:idx]
    title = body_lines[0] if body_lines else ""
    body = "\n".join(body_lines[2:]) if len(body_lines) > 1 else ""
    return {"title": title, "body": body, **props}
