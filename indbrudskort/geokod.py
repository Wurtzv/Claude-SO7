"""Geokodning af vej + by til et punkt midt på vejen.

Rækkefølge:
1. Dataforsyningens gsearch (navngivenvej) – kræver en gratis token i
   miljøvariablen DATAFORSYNINGEN_TOKEN. DAWA (api.dataforsyningen.dk/vejstykker
   m.fl.) svarer "410 Gone" og kan ikke bruges længere.
2. Nominatim (OpenStreetMap) – maks. ét kald pr. sekund jf. deres brugsregler.

Alle opslag gemmes i en cache (data/geokode-cache.json), så hver vej kun slås op én gang.
Mislykkede opslag caches også, men prøves igen efter FEJL_DAGE dage.
"""

from __future__ import annotations

import difflib
import json
import math
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

from . import net

NOMINATIM = "https://nominatim.openstreetmap.org/search"
GSEARCH = "https://api.dataforsyningen.dk/rest/gsearch/v2.0/navngivenvej"
MAKS_AFSTAND_KM = 12  # vejen skal ligge så tæt på byens midte, ellers er det nok en anden vej
FEJL_DAGE = 14
DK = (54.4, 57.9, 7.9, 15.3)  # syd, nord, vest, øst

Punkt = tuple[float, float]  # (lon, lat)
Linje = list[Punkt]


# ---------- geometri ----------

def afstand_km(a: Punkt, b: Punkt) -> float:
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * k, a[1] - b[1]) * 111.32


def linje_længde(l: Linje) -> float:
    return sum(afstand_km(l[i], l[i + 1]) for i in range(len(l) - 1))


def midtpunkt(l: Linje) -> Punkt:
    """Punktet halvvejs langs linjen."""
    if len(l) == 1:
        return l[0]
    halv, gået = linje_længde(l) / 2, 0.0
    for a, b in zip(l, l[1:]):
        d = afstand_km(a, b)
        if gået + d >= halv and d > 0:
            f = (halv - gået) / d
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        gået += d
    return l[-1]


def nærmeste_på_linje(p: Punkt, l: Linje) -> Punkt:
    k = math.cos(math.radians(p[1]))
    bedst, bd = l[0], float("inf")
    for a, b in zip(l, l[1:] or l):
        ax, ay, bx, by_, px, py = a[0] * k, a[1], b[0] * k, b[1], p[0] * k, p[1]
        dx, dy = bx - ax, by_ - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        d = afstand_km(p, q)
        if d < bd:
            bedst, bd = q, d
    return bedst


def vejens_midte(linjer: list[Linje]) -> Punkt:
    """Midten af en vej, der kan bestå af flere stykker.

    Tager de enkelte stykkers midtpunkter vægtet med længde og flytter resultatet
    ind på selve vejen, så punktet aldrig havner mellem to vejstykker.
    """
    linjer = [l for l in linjer if l]
    if len(linjer) == 1:
        return midtpunkt(linjer[0])
    vægte = [max(linje_længde(l), 1e-6) for l in linjer]
    mids = [midtpunkt(l) for l in linjer]
    c = (sum(m[0] * w for m, w in zip(mids, vægte)) / sum(vægte),
         sum(m[1] * w for m, w in zip(mids, vægte)) / sum(vægte))
    kandidater = [nærmeste_på_linje(c, l) for l in linjer]
    return min(kandidater, key=lambda q: afstand_km(c, q))


def utm32_til_wgs84(e: float, n: float) -> Punkt:
    """EPSG:25832 (ETRS89 / UTM 32N) -> (lon, lat). Standard invers transversal Mercator."""
    a, f, k0 = 6378137.0, 1 / 298.257222101, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x, y = e - 500000.0, n
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
            + (151 * e1**3 / 96) * math.sin(6 * mu) + (1097 * e1**4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = a / math.sqrt(1 - e2 * s * s)
    t1, c1 = t * t, ep2 * c * c
    r1 = a * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * t / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d**4 / 24
                                  + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d**6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d**3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d**5 / 120) / c
    return (math.degrees(lon) + 9.0, math.degrees(lat))


def linjer_fra_geometri(g) -> list[Linje]:
    """GeoJSON-dict eller WKT-streng -> liste af linjer i (lon, lat)."""
    linjer: list[Linje] = []
    if isinstance(g, dict):
        t, c = g.get("type"), g.get("coordinates")
        if t == "LineString":
            linjer = [[tuple(p[:2]) for p in c]]
        elif t == "MultiLineString":
            linjer = [[tuple(p[:2]) for p in l] for l in c]
        elif t == "Point":
            linjer = [[tuple(c[:2])]]
        elif t in ("Polygon", "MultiPolygon"):
            ringe = c if t == "Polygon" else [r for poly in c for r in poly]
            linjer = [[tuple(p[:2]) for p in r] for r in ringe[:1]]
    elif isinstance(g, str):
        for del_ in re.findall(r"\(([^()]+)\)", g):
            tal = [tuple(map(float, p.split()[:2])) for p in del_.split(",") if p.strip()]
            if tal:
                linjer.append(tal)
    if any(abs(p[0]) > 180 for l in linjer for p in l):
        linjer = [[utm32_til_wgs84(*p) for p in l] for l in linjer]
    return linjer


def i_danmark(p: Punkt) -> bool:
    return DK[0] <= p[1] <= DK[1] and DK[2] <= p[0] <= DK[3]


# ---------- opslag ----------

def _norm(s: str) -> str:
    s = s.casefold().replace("allé", "alle").replace("aa", "å")
    return re.sub(r"[^a-z0-9æøå]", "", s)


FORKORTELSER = [(r"\bSkt\.\s*", "Sankt "), (r"\bLl\.\s*", "Lille ")]


def navnevarianter(vej: str) -> list[str]:
    ud = [vej]
    for mønster, erstatning in FORKORTELSER:
        ny = re.sub(mønster, erstatning, vej)
        if ny != vej:
            ud.append(ny)
    return ud


def samme_vej(osm_navn: str, vej: str) -> bool:
    """Tillader små stavefejl i politiets vejnavne (fx 'Ingerslev Boulevard' = 'Ingerslevs Boulevard')."""
    a = _norm(osm_navn)
    for v in navnevarianter(vej):
        b = _norm(v)
        if a == b:
            return True
        if min(len(a), len(b)) >= 6 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
            return True
    return False


# Områder, hvis bydele alle ligger i én kommune
OMRAADE_KOMMUNE = {"Aarhus": "Aarhus", "Aalborg": "Aalborg", "Randers": "Randers"}
# Groft rektangel om hver politikreds (vest, nord, øst, syd) til Nominatims viewbox
KREDS_BOKS = {
    "Østjyllands Politi": "9.55,56.80,11.75,55.80",
    "Nordjyllands Politi": "8.15,57.80,11.25,56.45",
    "Sydøstjyllands Politi": "8.85,56.05,10.65,55.15",
    "Midt- og Vestjyllands Politi": "8.05,57.15,9.95,55.55",
    "Syd- og Sønderjyllands Politi": "8.05,55.75,10.15,54.75",
}


def by_uden_postdistrikt(by: str) -> str:
    return re.sub(r"\s+(C|N|V|J|S|Ø|NV|NØ|SV|SØ)$", "", by)


class Geokoder:
    def __init__(self, cache_fil: Path, token: str | None = None, pause: float = 1.1, i_dag: date | None = None):
        self.cache_fil = Path(cache_fil)
        self.token = token if token is not None else os.environ.get("DATAFORSYNINGEN_TOKEN") or None
        self.pause = pause
        self.i_dag = i_dag or date.today()
        self._sidste_kald = 0.0
        self.cache: dict = json.loads(self.cache_fil.read_text("utf-8")) if self.cache_fil.exists() else {}

    def gem(self):
        self.cache_fil.parent.mkdir(parents=True, exist_ok=True)
        self.cache_fil.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")

    # -- offentligt API --

    def vej(self, vej: str, by: str) -> dict | None:
        """Returnerer {'lat','lon','praecision','geokilde'} eller None."""
        if not vej:  # kun by oplyst (fx Nordjyllands nyhedsafsnit)
            c = self.by(by)
            return {"lon": c[0], "lat": c[1], "praecision": "by", "geokilde": "nominatim"} if c else None
        nøgle = f"{vej}|{by}"
        hit = self.cache.get(nøgle)
        if hit and not self._forældet_fejl(hit):
            return None if hit.get("fejl") else hit
        res = None
        centrum = self.by(by)
        if vej:
            for f in (self._gsearch, self._nominatim_vej):
                try:
                    res = f(vej, by, centrum)
                except Exception as e:  # netværk/format – prøv næste kilde
                    print(f"  geokodning {f.__name__} fejlede for {vej}, {by}: {e}")
                    res = None
                if res:
                    break
        if not res and centrum:
            res = {"lon": centrum[0], "lat": centrum[1], "praecision": "by", "geokilde": "nominatim",
                   "dato": self.i_dag.isoformat()}
        self.cache[nøgle] = res or {"fejl": True, "dato": self.i_dag.isoformat()}
        return res

    def by(self, by: str) -> Punkt | None:
        if not by:
            return None
        nøgle = f"|{by}"
        hit = self.cache.get(nøgle)
        if hit and not self._forældet_fejl(hit):
            return None if hit.get("fejl") else (hit["lon"], hit["lat"])
        p = None
        forespørgsler = [
            {"q": by, "featureType": "settlement"},
            {"q": by_uden_postdistrikt(by), "featureType": "settlement"},
            {"q": f"{by}, Danmark"},
        ]
        for q in forespørgsler:
            r = [x for x in self._nominatim({**q, "countrycodes": "dk", "limit": 3}) or []
                 if x.get("category") in ("place", "boundary")]
            if r:
                p = (float(r[0]["lon"]), float(r[0]["lat"]))
                break
        self.cache[nøgle] = {"lon": round(p[0], 6), "lat": round(p[1], 6)} if p else {"fejl": True, "dato": self.i_dag.isoformat()}
        return p

    def kommune(self, by: str, omraade: str = "", kreds: str = "") -> str | None:
        """Kommunen en by/bydel ligger i, fx 'Risskov' -> 'Aarhus' (navn uden 'Kommune').
        Søgningen holdes inden for politikredsen, så 'Hasle' ikke bliver til Hasle på Bornholm."""
        if not by:
            return None
        if by.endswith(" Kommune"):
            return by[: -len(" Kommune")]
        if omraade in OMRAADE_KOMMUNE:
            return OMRAADE_KOMMUNE[omraade]
        nøgle = f"kommune|{kreds}|{by}"
        hit = self.cache.get(nøgle)
        if hit is not None and not (isinstance(hit, dict) and self._forældet_fejl(hit)):
            return hit if isinstance(hit, str) else None
        navn = None
        for q in dict.fromkeys(x for x in (by, by_uden_postdistrikt(by), omraade) if x):
            try:
                boks = KREDS_BOKS.get(kreds)
                ekstra = {"viewbox": boks, "bounded": 1} if boks else {}
                r = self._nominatim({"q": q, "countrycodes": "dk", "featureType": "settlement", "addressdetails": 1,
                                     "limit": 1, **ekstra})
            except Exception as e:
                print(f"  kommuneopslag fejlede for {q}: {e}")
                return None
            m = (r[0].get("address", {}).get("municipality") if r else None) or ""
            if m:
                navn = re.sub(r"\s+Kommune$", "", m)
                break
        self.cache[nøgle] = navn or {"fejl": True, "dato": self.i_dag.isoformat()}
        return navn

    # -- kilder --

    def _forældet_fejl(self, hit: dict) -> bool:
        if not hit.get("fejl") and hit.get("praecision") != "by":
            return False
        if "dato" not in hit:
            return True
        return date.fromisoformat(hit["dato"]) < self.i_dag - timedelta(days=FEJL_DAGE)

    def _vent(self):
        dt = time.monotonic() - self._sidste_kald
        if dt < self.pause:
            time.sleep(self.pause - dt)
        self._sidste_kald = time.monotonic()

    def _nominatim(self, params: dict):
        self._vent()
        return net.hent_json(NOMINATIM, params={**params, "format": "jsonv2"})

    def _resultat(self, linjer: list[Linje], centrum: Punkt | None, kilde: str) -> dict | None:
        if centrum:
            linjer = [l for l in linjer if any(afstand_km(p, centrum) <= MAKS_AFSTAND_KM for p in l)]
        if not linjer:
            return None
        p = vejens_midte(linjer)
        if not i_danmark(p):
            return None
        return {"lon": round(p[0], 6), "lat": round(p[1], 6), "praecision": "vej", "geokilde": kilde}

    def _nominatim_vej(self, vej: str, by: str, centrum: Punkt | None) -> dict | None:
        forespørgsler: list[dict] = []
        if by:
            forespørgsler += [{"street": vej, "city": by}, {"street": vej, "city": by_uden_postdistrikt(by)}]
        if centrum:
            # OSM kalder ofte byen "Aarhus", hvor politiet skriver bydelen, så søg i en boks om byen.
            lon, lat = centrum
            boks = f"{lon - 0.15},{lat + 0.09},{lon + 0.15},{lat - 0.09}"
            for navn in navnevarianter(vej):
                forespørgsler.append({"q": navn, "viewbox": boks, "bounded": 1})
        set_ = set()
        for q in forespørgsler:
            nøgle = json.dumps(q, sort_keys=True)
            if nøgle in set_:
                continue
            set_.add(nøgle)
            r = self._nominatim({**q, "countrycodes": "dk", "polygon_geojson": 1, "limit": 10})
            linjer = []
            for x in r or []:
                navn = x.get("name") or x.get("display_name", "").split(",")[0]
                if x.get("category") == "highway" and samme_vej(navn, vej):
                    linjer += linjer_fra_geometri(x.get("geojson")) or [[(float(x["lon"]), float(x["lat"]))]]
            res = self._resultat(linjer, centrum, "nominatim")
            if res:
                return res
        return None

    def _gsearch(self, vej: str, by: str, centrum: Punkt | None) -> dict | None:
        if not self.token:
            return None
        data = net.hent_json(GSEARCH, params={"q": f"{vej} {by_uden_postdistrikt(by)}", "token": self.token, "limit": 10})
        resultater = data if isinstance(data, list) else data.get("results") or data.get("features") or []
        linjer = []
        for r in resultater:
            egenskaber = r.get("properties", r) if isinstance(r, dict) else {}
            navn = egenskaber.get("vejnavn") or egenskaber.get("navn") or egenskaber.get("visningstekst", "")
            if _norm(vej) not in _norm(str(navn)):
                continue
            geo = (r.get("geometry") or egenskaber.get("geometri") or egenskaber.get("geometry")
                   or egenskaber.get("vejnavnelinje"))
            linjer += linjer_fra_geometri(geo)
        return self._resultat(linjer, centrum, "dataforsyningen")
