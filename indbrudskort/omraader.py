"""Langtidsstatistik ud fra egne data: indbrud fra døgnrapporterne talt pr. by/bydel og
pr. område pr. måned (efter rapportdato). Gemmes i data/omraader.json, som kortsiden
bruger til grafer og ranglister uden at skulle regne på hele data/indbrud.json.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def byg(indbrud: list[dict]) -> dict:
    by_tæl: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    omr_tæl: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    dækning: dict[str, list[str]] = {}
    for r in indbrud:
        md = r["rapportdato"][:7]
        kreds = r.get("politikreds", "")
        by_tæl[(kreds, r["omraade"], r["by"])][md] += 1
        omr_tæl[(kreds, r["omraade"])][md] += 1
        d = dækning.setdefault(kreds, [r["rapportdato"], r["rapportdato"]])
        d[0], d[1] = min(d[0], r["rapportdato"]), max(d[1], r["rapportdato"])
    måneder = sorted({md for t in omr_tæl.values() for md in t})
    return {
        "opdateret": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kilde": "Egne data fra politiets døgnrapporter (data/indbrud.json), talt efter rapportdato",
        "maaneder": måneder,
        "daekning": {k: {"fra": v[0], "til": v[1]} for k, v in sorted(dækning.items())},
        "omraader": [{"kreds": k, "navn": o, "antal": dict(sorted(t.items()))}
                     for (k, o), t in sorted(omr_tæl.items())],
        "byer": [{"kreds": k, "omraade": o, "navn": b, "antal": dict(sorted(t.items()))}
                 for (k, o, b), t in sorted(by_tæl.items())],
    }


def gem(indbrud: list[dict], fil: Path) -> dict:
    data = byg(indbrud)
    fil.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    return data
