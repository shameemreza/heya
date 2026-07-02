from pathlib import Path
import re

GUIDANCE = Path("heya/guidance")


def test_all_read_guidance_refs_resolve():
    stems = {p.stem for p in GUIDANCE.glob("*.md")}
    refs = set()
    for md in GUIDANCE.glob("*.md"):
        for m in re.finditer(r"read_guidance\(['\"]([a-z0-9-]+)['\"]\)", md.read_text()):
            refs.add(m.group(1))
    missing = refs - stems
    assert not missing, f"dangling read_guidance targets: {missing}"
