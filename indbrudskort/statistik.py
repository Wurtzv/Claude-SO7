"""Anmeldte indbrud i beboelse pr. jysk kommune pr. kvartal fra Danmarks Statistik.

Tabel STRAF11 (anmeldte forbrydelser, overtrædelse 1320 "Indbrud i beboelser") og
FOLK1A (befolkning) hentes fra statistikbankens åbne API. Det dækker hele Jylland,
også de politikredse, der ikke udgiver døgnrapporter. Resultatet gemmes i
data/statistik.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import net

API = "https://api.statbank.dk/v1/data/{tabel}/BULK"
INDBRUD_I_BEBOELSE = "1320"
ANTAL_KVARTALER = 5  # seneste kvartal + samme kvartal året før


def er_jysk(kode: str) -> bool:
    """Kommunekoder fra 500 og op er de jyske kommuner (inkl. Fanø, Samsø og Læsø).
    Fynske kommuner (410-492) og alt øst for Storebælt har lavere koder."""
    return len(kode) == 3 and kode.isdigit() and 500 <= int(kode) < 990  # 998 = uoplyst kommune


def parse_bulk(csv: str) -> list[tuple[str, str, str, int | None]]:
    """Statistikbankens BULK-format (semikolon, 'kode tekst' i hver kolonne) ->
    [(områdekode, områdenavn, kvartal, værdi)]."""
    linjer = [l for l in csv.strip().splitlines() if l.strip()]
    hoved = linjer[0].split(";")
    i_omr, i_tid, i_val = hoved.index("OMRÅDE"), hoved.index("TID"), hoved.index("INDHOLD")
    ud = []
    for l in linjer[1:]:
        f = l.split(";")
        kode, _, navn = f[i_omr].partition(" ")
        tid = f[i_tid].split(" ")[0]
        v = f[i_val].strip()
        ud.append((kode, navn, tid, int(v) if v.isdigit() else None))
    return ud


def hent_indbrud(kvartaler: int = ANTAL_KVARTALER) -> list[tuple[str, str, str, int | None]]:
    csv = net.hent_tekst(API.format(tabel="STRAF11"), params={
        "lang": "da", "OMRÅDE": "*", "OVERTRÆD": INDBRUD_I_BEBOELSE,
        "Tid": f"(-n+{kvartaler})", "valuePresentation": "CodeAndValue"})
    return parse_bulk(csv)


def hent_befolkning() -> dict[str, int]:
    csv = net.hent_tekst(API.format(tabel="FOLK1A"), params={
        "lang": "da", "OMRÅDE": "*", "KØN": "TOT", "ALDER": "IALT", "CIVILSTAND": "TOT",
        "Tid": "(-n+1)", "valuePresentation": "CodeAndValue"})
    return {kode: v for kode, _, _, v in parse_bulk(csv) if v}


def byg(indbrud, befolkning: dict[str, int], centrum) -> dict:
    """Samler tallene pr. jysk kommune. `centrum(navn)` giver (lon, lat) eller None."""
    kvartaler = sorted({t for _, _, t, _ in indbrud})
    kommuner: dict[str, dict] = {}
    for kode, navn, tid, v in indbrud:
        if not er_jysk(kode):
            continue
        k = kommuner.setdefault(kode, {"kode": kode, "navn": navn, "indbyggere": befolkning.get(kode), "antal": {}})
        k["antal"][tid] = v
    for k in kommuner.values():
        p = centrum(k["navn"])
        k["lon"], k["lat"] = (round(p[0], 5), round(p[1], 5)) if p else (None, None)
    return {
        "kilde": "Danmarks Statistik, tabel STRAF11 (anmeldte indbrud i beboelser) og FOLK1A (befolkning)",
        "kilde_url": "https://www.statistikbanken.dk/STRAF11",
        "opdateret": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kvartaler": kvartaler,
        "kommuner": sorted(kommuner.values(), key=lambda k: k["navn"]),
    }


def opdater(fil: Path, geokoder) -> dict:
    def centrum(navn: str):
        return geokoder.by(f"{navn} Kommune") or geokoder.by(navn)

    data = byg(hent_indbrud(), hent_befolkning(), centrum)
    fil.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return data
