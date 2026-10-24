"""Kør med:  python -m indbrudskort opdater [--dage 14] [--uden-geokodning] [--prøvekørsel]"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from .geokod import Geokoder
from .kilder import KILDER, siden
from .lager import Lager
from . import omraader, statistik, ugerapport
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


def geokod(lager: Lager, prøvekørsel: bool, minutter: float) -> None:
    """Geokoder manglende veje, nyeste først, i højst `minutter` (Nominatim tillader ét kald i sekundet,
    så en stor historik bliver placeret over flere dages kørsler)."""
    geo = Geokoder(DATA / "geokode-cache.json")
    slut = time.monotonic() + minutter * 60
    mangler = sorted(lager.mangler_koordinater(), key=lambda r: r["rapportdato"], reverse=True)
    færdige = 0
    try:
        for r in mangler:
            if time.monotonic() > slut:
                print(f"  geokodning stoppet efter {minutter:g} min; {len(mangler) - færdige} venter til næste kørsel")
                break
            p = geo.vej(r["vej"], r["by"])
            færdige += 1
            if p:
                r.update(lat=p["lat"], lon=p["lon"], praecision=p["praecision"], geokilde=p["geokilde"])
            else:
                print(f"  kunne ikke geokode {r['vej']}, {r['by']}")
    finally:
        if not prøvekørsel:
            geo.gem()


def postnumre(lager: Lager, prøvekørsel: bool, minutter: float) -> None:
    """Sætter postnummer på placerede indbrud ud fra punktet (nyeste først, tidsbegrænset)."""
    geo = Geokoder(DATA / "geokode-cache.json")
    slut = time.monotonic() + minutter * 60
    mangler = sorted((r for r in lager.indbrud if r.get("lat") is not None and not r.get("postnr")),
                     key=lambda r: r["rapportdato"], reverse=True)
    try:
        for i, r in enumerate(mangler):
            if time.monotonic() > slut:
                print(f"  postnumre stoppet efter {minutter:g} min; {len(mangler) - i} venter til næste kørsel")
                break
            try:
                p = geo.postnummer(r["lat"], r["lon"])
            except Exception as e:
                print(f"  postnummeropslag fejlede: {e}")
                break
            if p:
                r["postnr"] = p
    finally:
        if not prøvekørsel:
            geo.gem()


def gem_omraader(lager: Lager) -> None:
    """Egen statistik pr. område, by og kommune (kommuner slås op én gang og caches)."""
    geo = Geokoder(DATA / "geokode-cache.json")
    try:
        omraader.gem(lager.indbrud, DATA / "omraader.json", geo.kommune)
    finally:
        geo.gem()


def _statistik() -> dict | None:
    f = DATA / "statistik.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else None


def gem_ugerapport(lager: Lager) -> dict:
    return ugerapport.gem(lager.indbrud, DATA / "ugerapport.json", _statistik())


def uge(args) -> int:
    """Skriver ugens opsummering som Markdown (bruges af det ugentlige GitHub-issue)."""
    data = ugerapport.byg(Lager(DATA / "indbrud.json").indbrud, _statistik())
    tekst = ugerapport.markdown(data, args.url)
    if args.md:
        Path(args.md).write_text(tekst, "utf-8")
    else:
        print(tekst)
    return 0


def historik(args) -> int:
    """Henter ældre døgnrapporter dag for dag (kun kredse med historik-skabeloner)."""
    lager = Lager(DATA / "indbrud.json")
    hfil = DATA / "historik.json"
    ikke_fundet: dict = json.loads(hfil.read_text("utf-8")) if hfil.exists() else {}
    fra, til = date.fromisoformat(args.fra), date.fromisoformat(args.til)
    nye = behandlet = 0
    for kilde in KILDER:
        if not getattr(kilde, "historik", None):
            continue
        set_ = set(ikke_fundet.get(kilde.politikreds, []))
        d = til
        while d >= fra:
            ds = d.isoformat()
            urls = kilde.historiske_urls(d)
            if ds in set_ or any(u in lager.behandlet for u in urls):
                d -= timedelta(days=1)
                continue
            try:
                m = kilde.hent_historisk(d)
            except Exception as e:
                print(f"  FEJL {ds}: {e}")
                d -= timedelta(days=1)
                continue
            if m is None:
                set_.add(ds)
            else:
                poster = kilde.parse(m, m.indhold)
                n = lager.tilføj_rapport(poster, url=m.url, titel=m.titel, rapportdato=d,
                                         udgiver=m.udgiver, politikreds=m.politikreds)
                nye += n
                print(f"  {ds}: {len(poster)} indbrud, {n} nye")
            behandlet += 1
            if behandlet % 25 == 0:  # gem undervejs, så en afbrudt kørsel kan fortsætte
                ikke_fundet[kilde.politikreds] = sorted(set_)
                hfil.write_text(json.dumps(ikke_fundet, indent=1) + "\n", "utf-8")
                lager.gem()
            if args.maks and behandlet >= args.maks:
                break
            time.sleep(args.pause)
            d -= timedelta(days=1)
        ikke_fundet[kilde.politikreds] = sorted(set_)
    hfil.write_text(json.dumps(ikke_fundet, indent=1) + "\n", "utf-8")
    lager.normaliser()
    lager.gem()
    gem_omraader(lager)
    print(f"Historik: {behandlet} dage behandlet, {nye} nye indbrud. I alt {len(lager.indbrud)}.")
    return 0


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
                poster = kilde.parse(m, kilde.hent(m))
            except Exception as e:
                print(f"  FEJL ved {m.url}: {e}")
                continue
            n = lager.tilføj_rapport(poster, url=m.url, titel=m.titel, rapportdato=m.dato,
                                     udgiver=m.udgiver, politikreds=m.politikreds)
            nye += n
            if poster:
                print(f"  {m.dato} {m.titel[:60]}: {len(poster)} indbrud, {n} nye")
            elif kilde.udgiver == "politi.dk":
                print(f"  {m.dato} {m.titel[:60]}: ingen indbrud fundet")

    if not args.uden_geokodning:
        geokod(lager, args.prøvekørsel, args.geokodning_minutter)
        postnumre(lager, args.prøvekørsel, args.postnummer_minutter)

    if not args.uden_statistik and not args.prøvekørsel:
        try:
            geo_s = Geokoder(DATA / "geokode-cache.json")
            s = statistik.opdater(DATA / "statistik.json", geo_s)
            geo_s.gem()
            print(f"Statistik: {len(s['kommuner'])} jyske kommuner, kvartaler {s['kvartaler'][0]}–{s['kvartaler'][-1]}")
        except Exception as e:  # statistikken er et ekstra lag; den må ikke stoppe resten
            print(f"FEJL: kunne ikke hente statistik fra Danmarks Statistik: {e}")

    print(f"I alt {len(lager.indbrud)} indbrud, {nye} nye.")
    if not args.prøvekørsel:
        lager.normaliser()
        lager.gem()
        gem_omraader(lager)
        gem_ugerapport(lager)
    # Rødt flag i Actions, hvis ingen kilder kunne nås.
    return 1 if fejl == len(KILDER) else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="indbrudskort")
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("opdater", help="hent nye døgnrapporter og opdater data/indbrud.json")
    o.add_argument("--dage", type=int, default=14, help="hvor mange dage tilbage der kigges (standard 14)")
    o.add_argument("--alle", action="store_true", help="genbehandl også meddelelser, der er set før")
    o.add_argument("--uden-geokodning", action="store_true")
    o.add_argument("--uden-statistik", action="store_true", help="spring kommunestatistikken fra Danmarks Statistik over")
    o.add_argument("--prøvekørsel", action="store_true", help="hent og parse, men gem intet")
    o.add_argument("--geokodning-minutter", type=float, default=20,
                   help="maks. tid til geokodning pr. kørsel (resten tages næste gang)")
    o.add_argument("--postnummer-minutter", type=float, default=10,
                   help="maks. tid til postnummeropslag pr. kørsel")
    h = sub.add_parser("historik", help="hent ældre døgnrapporter dag for dag")
    h.add_argument("--fra", required=True, help="første dato, fx 2023-01-01")
    h.add_argument("--til", default=date.today().isoformat(), help="sidste dato (standard i dag)")
    h.add_argument("--maks", type=int, default=0, help="stop efter så mange dage (0 = alle)")
    h.add_argument("--pause", type=float, default=1.0, help="sekunder mellem rapporter")
    u = sub.add_parser("ugerapport", help="skriv ugens opsummering som Markdown")
    u.add_argument("--md", help="fil at skrive til (standard: skærmen)")
    u.add_argument("--url", default="", help="link til kortsiden i bunden af rapporten")
    args = p.parse_args(argv)
    return {"historik": historik, "ugerapport": uge}.get(args.cmd, opdater)(args)


if __name__ == "__main__":
    sys.exit(main())
