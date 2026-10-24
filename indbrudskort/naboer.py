"""Naboveje: vejene inden for ca. 500 m af hvert nyligt indbrud.

Risikoen for indbrud er forhøjet i nabolaget i ugerne efter et indbrud, så listen bruges
til at dække vejene omkring det. Vejene findes ved at slå vejnavnet op i 20 punkter i ringe
på ca. 150, 300 og 500 m omkring indbruddet (omvendt opslag i Nominatim, cachet). Resultatet
gemmes i data/naboveje.json med indbruddets punkt (4 decimaler) som nøgle.
"""

from __future__ import annotations

import json
import math
import time
from datetime import date, timedelta
from pathlib import Path

RINGE = ((150, 4), (300, 8), (500, 8))  # (meter, antal retninger)
DAGE = 30


def nøgle(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def prøvepunkter(lat: float, lon: float) -> list[tuple[int, float, float]]:
    ud = []
    for meter, n in RINGE:
        for i in range(n):
            v = math.radians(i * 360 / n + (22.5 if n == 4 else 0))
            dlat = meter * math.cos(v) / 111_320
            dlon = meter * math.sin(v) / (111_320 * math.cos(math.radians(lat)))
            ud.append((meter, lat + dlat, lon + dlon))
    return ud


def naboveje(lat: float, lon: float, egen_vej: str, vejnavn) -> list[dict]:
    """`vejnavn(lat, lon)` giver nærmeste vejnavn eller None. Hver vej får den mindste
    ringafstand, den blev fundet i; indbruddets egen vej udelades."""
    fundet: dict[str, int] = {}
    egen = egen_vej.casefold()
    for meter, la, lo in prøvepunkter(lat, lon):
        v = vejnavn(la, lo)
        if v and v.casefold() != egen and v not in fundet:
            fundet[v] = meter
    return [{"vej": v, "m": m} for v, m in sorted(fundet.items(), key=lambda x: (x[1], x[0]))]


def opdater(indbrud: list[dict], fil: Path, vejnavn, minutter: float = 8, i_dag: date | None = None) -> dict:
    """Beregner naboveje for indbrud med vej-præcision fra de seneste DAGE dage, nyeste først.
    Punkter, der allerede er beregnet, genbruges; gamle punkter fjernes fra filen."""
    gammel = json.loads(fil.read_text("utf-8")) if fil.exists() else {}
    seneste = max((r["rapportdato"] for r in indbrud), default=(i_dag or date.today()).isoformat())
    grænse = (date.fromisoformat(seneste) - timedelta(days=DAGE)).isoformat()
    aktuelle = sorted((r for r in indbrud if r.get("praecision") == "vej" and r.get("lat") is not None
                       and r["rapportdato"] >= grænse), key=lambda r: r["rapportdato"], reverse=True)
    ny: dict[str, list] = {}
    slut = time.monotonic() + minutter * 60
    for r in aktuelle:
        k = nøgle(r["lat"], r["lon"])
        if k in ny:
            continue
        if k in gammel:
            ny[k] = gammel[k]
            continue
        if time.monotonic() > slut:
            continue
        try:
            ny[k] = naboveje(r["lat"], r["lon"], r.get("vej", ""), vejnavn)
        except Exception as e:  # netværksfejl: prøv igen næste kørsel
            print(f"  naboveje fejlede: {e}")
            break
    fil.write_text(json.dumps(ny, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    mangler = len({nøgle(r["lat"], r["lon"]) for r in aktuelle}) - len(ny)
    print(f"Naboveje: {len(ny)} punkter" + (f", {mangler} venter til næste kørsel" if mangler else ""))
    return ny
