"""A tiny TOML writer for the simple shapes Heya writes (config + credentials).

Handles scalars (str/int/float/bool), lists of those, and one- or two-level
tables. Not a general TOML serializer; it round-trips what Heya produces."""
from __future__ import annotations


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        raise TypeError(f"tomlw cannot serialize dict value: {v!r}")
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(data: dict) -> str:
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_value(v)}")
    for k, v in tables.items():
        sub_scalars = {kk: vv for kk, vv in v.items() if not isinstance(vv, dict)}
        sub_tables = {kk: vv for kk, vv in v.items() if isinstance(vv, dict)}
        if sub_scalars or not sub_tables:
            lines.append("")
            lines.append(f"[{k}]")
            for kk, vv in sub_scalars.items():
                lines.append(f"{kk} = {_value(vv)}")
        for kk, vv in sub_tables.items():
            lines.append("")
            lines.append(f"[{k}.{kk}]")
            for kkk, vvv in vv.items():
                lines.append(f"{kkk} = {_value(vvv)}")
    return "\n".join(lines).strip() + "\n"
