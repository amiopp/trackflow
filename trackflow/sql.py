"""SQL model rendering: Jinja templating with a small macro library."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, StrictUndefined

_DATE_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
_DMY_GLOB = "[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]"
_YMD_GLOB = "[0-9]" * 8


def parse_date(column: str) -> str:
    """SQL expression turning ISO, dd/mm/yyyy or yyyymmdd text into an ISO date, else NULL.

    SQLite's DATE() silently rolls impossible dates forward ('2024-02-31' -> '2024-03-02'),
    so the candidate is only accepted if DATE() returns it unchanged.
    """
    c = f"TRIM({column})"
    iso = (
        "(CASE "
        f"WHEN {c} GLOB '{_DATE_GLOB}' THEN {c} "
        f"WHEN {c} GLOB '{_DMY_GLOB}' THEN SUBSTR({c},7,4)||'-'||SUBSTR({c},4,2)||'-'||SUBSTR({c},1,2) "
        f"WHEN {c} GLOB '{_YMD_GLOB}' THEN SUBSTR({c},1,4)||'-'||SUBSTR({c},5,2)||'-'||SUBSTR({c},7,2) "
        "END)"
    )
    return f"(CASE WHEN DATE({iso}) = {iso} THEN {iso} END)"


_env = Environment(undefined=StrictUndefined, autoescape=False)
_env.globals["parse_date"] = parse_date


def render(path: str | Path, **context) -> str:
    return _env.from_string(Path(path).read_text(encoding="utf-8")).render(**context)
