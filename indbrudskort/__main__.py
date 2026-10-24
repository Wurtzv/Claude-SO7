"""Kør med:  python -m indbrudskort opdater [--dage 14] [--uden-geokodning] [--prøvekørsel]"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .geokod import Geokoder
from .kilder import KILDER, siden
from .lager import Lager
from .parse import parse_rapport

RODEN = Path(__file__).resolve().parent.parent
DATA = RODEN / "data"


def indlæs_startdata(lager: Lager, fil: Path) -> int:
    """Startdata (fra prototypen) i samme format som en meddelelse pr. kilde."""
    if not fil.exists():
        return 0
    nye = 0
    for m in json.loads(fil.read_text("utf-8"))["meddelelser"]:
        if m["url"] in lager.behandlet:
            continue
        rd = date.fromisoformat(m["rapportdato"])
        poster = parse_rapport(m["linjer"], rd, titel="indbrud i privat beboelse")
        for p, t in zip(poster, m.get("typer", [])):
            p.type = t
        nye += lager.tilføj_rapport(poster, url=m["url"], titel=m["titel"], rapportdato=rd,
                                    udgiver=m["udgiver"], politikreds=m["politikreds"])
    return nye


def opdater(args) -> int:
    lager = Lager(DATA / "indbrud.json")
    nye = indlæs_startdata(lager, DATA / "startdata.json")
    fra = siden(args.dage)
    fejl = 0
    for kilde in KILDER:
        navn = f"{kilde.udgiver} ({kilde.politikreds})"
        try:
            meddelelser = kilde.find(fra)
        except Exception as e:
            print(f"FEJL: kunne ikke hente oversigt fra {navn}: {e}")
            fejl += 1
            continue
        print(f"{navn}: {len(meddelelser)} meddelelser siden {fra}")
        for m in sorted(meddelelser, key=lambda m: m.dato):
            if m.url in lager.behandlet and not args.alle:
                continue
            try:
                poster = parse_rapport(kilde.hent(m), m.dato, m.titel)
            except Exception as e:
                print(f"  FEJL ved {m.url}: {e}")
                continue
            n = lager.tilføj_rapport(poster, url=m.url, titel=m.titel, rapportdato=m.dato,
                                     udgiver=m.udgiver, politikreds=m.politikreds)
            nye += n
            if poster:
                print(f"  {m.dato} {m.titel[:60]}: {len(poster)} indbrud, {n} nye")

    if not args.uden_geokodning:
        geo = Geokoder(DATA / "geokode-cache.json")
        try:
            for r in lager.mangler_koordinater():
                p = geo.vej(r["vej"], r["by"])
                if p:
                    r.update(lat=p["lat"], lon=p["lon"], praecision=p["praecision"], geokilde=p["geokilde"])
                else:
                    print(f"  kunne ikke geokode {r['vej']}, {r['by']}")
        finally:
            if not args.prøvekørsel:
                geo.gem()

    print(f"I alt {len(lager.indbrud)} indbrud, {nye} nye.")
    if not args.prøvekørsel:
        lager.gem()
    # Rødt flag i Actions, hvis ingen kilder kunne nås.
    return 1 if fejl == len(KILDER) else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="indbrudskort")
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("opdater", help="hent nye døgnrapporter og opdater data/indbrud.json")
    o.add_argument("--dage", type=int, default=14, help="hvor mange dage tilbage der kigges (standard 14)")
    o.add_argument("--alle", action="store_true", help="genbehandl også meddelelser, der er set før")
    o.add_argument("--uden-geokodning", action="store_true")
    o.add_argument("--prøvekørsel", action="store_true", help="hent og parse, men gem intet")
    args = p.parse_args(argv)
    return opdater(args)


if __name__ == "__main__":
    sys.exit(main())
