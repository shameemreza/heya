"""Turn @mentions in a user's line into message content: text files inlined,
images as base64 image_url blocks. Reads only within the allowed roots; every
read failure is a note, never an exception."""
from __future__ import annotations

import base64
from pathlib import Path

from .tools_files import resolve_in_allowlist

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_MAX_TEXT_BYTES = 256 * 1024
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}


def parse_mentions(text: str) -> list[str]:
    out = []
    for tok in (text or "").split():
        if len(tok) > 1 and tok.startswith("@"):
            out.append(tok[1:])
    return out


def build_user_content(text, *, allowed_roots, cwd, read_bytes=None):
    mentions = parse_mentions(text)
    info = {"has_image": False, "notes": []}
    if not mentions:
        return text, info
    read_bytes = read_bytes or (lambda p: Path(p).read_bytes())
    blocks = [{"type": "text", "text": text}]
    for m in mentions:
        raw_path = m if Path(m).is_absolute() else str(Path(cwd) / m)
        try:
            target = resolve_in_allowlist(raw_path, allowed_roots)
        except Exception:
            info["notes"].append(f"could not include @{m}: outside the allowed folders")
            continue
        try:
            data = read_bytes(target)
        except Exception:
            info["notes"].append(f"could not read @{m}")
            continue
        ext = Path(str(target)).suffix.lower()
        if ext in IMAGE_EXTS:
            b64 = base64.b64encode(data).decode("ascii")
            mime = _MIME.get(ext, "image/png")
            blocks.append({"type": "image_url",
                           "image_url": {"url": f"data:{mime};base64,{b64}"}})
            info["has_image"] = True
        else:
            text_content = data[:_MAX_TEXT_BYTES].decode("utf-8", errors="replace")
            tail = "\n... (truncated)" if len(data) > _MAX_TEXT_BYTES else ""
            blocks.append({"type": "text",
                           "text": f"Contents of {m}:\n\n{text_content}{tail}"})
    if len(blocks) == 1:  # nothing attached successfully
        return text, info
    return blocks, info
