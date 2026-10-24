"""Nyhedskilder. Tilføj en ny politikreds eller kilde ved at tilføje en linje i KILDER."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from . import net
from .afsnit import parse_afsnit_rapport
from .parse import Indbrud, dato_fra_tekst, parse_rapport


@dataclass
class Meddelelse:
    url: str
    titel: str
    dato: date
    udgiver: str  # "politi.dk" eller "Via Ritzau"
    politikreds: str
    indhold: str | None = None  # HTML; hentes først når den skal bruges


class PolitiDk:
    """Døgnrapporter på politi.dk.

    Oversigtssiden https://politi.dk/doegnrapporter?district=<distrikt> har
    rapportlisten som JSON indlejret i HTML'en (felterne Link, ListDate, Headline).
    """

    udgiver = "politi.dk"

    def __init__(self, politikreds: str, distrikt: str, sti: str, format: str = "liste",
                 historik: tuple[str, ...] = ()):
        self.politikreds = politikreds
        # Skabeloner for ældre rapporters adresser (oversigten viser kun ca. 30 dage).
        # Pladsholdere: {d} {dd} {m} {mm} {mnavn} {yyyy} {yy}
        self.historik = historik
        self.distrikt = distrikt  # fx "OEstjyllands-Politi"
        self.sti = sti  # fx "oestjyllands-politi"
        # "liste": fast liste over indbrud i privat beboelse (Østjylland)
        # "afsnit": indbrud skrevet som nyhedsafsnit med overskriften "Indbrud i ..." (Nordjylland)
        self.format = format

    def liste_url(self) -> str:
        return f"https://politi.dk/doegnrapporter?district={self.distrikt}"

    def parse_liste(self, side: str) -> list[Meddelelse]:
        s = html.unescape(side)
        ud, set_ = [], set()
        for m in re.finditer(r'\{[^{}]*"Link":"(https://politi\.dk/[^"]+)"[^{}]*\}', s):
            obj = m.group(0)
            url = m.group(1)
            if f"/{self.sti}/doegnrapporter/" not in url or url in set_:
                continue
            set_.add(url)
            dato_s = re.search(r'"ListDate":"([^"]+)"', obj)
            titel = re.search(r'"Headline":"([^"]*)"', obj)
            dato = dato_fra_tekst(dato_s.group(1)) if dato_s else None
            if dato is None:
                m2 = re.search(r"/(\d{4})/(\d{2})/(\d{2})/?$", url)
                dato = date(*map(int, m2.groups())) if m2 else None
            if dato:
                ud.append(Meddelelse(url, titel.group(1) if titel else "", dato, self.udgiver, self.politikreds))
        return ud

    def find(self, siden: date) -> list[Meddelelse]:
        return [m for m in self.parse_liste(net.hent_tekst(self.liste_url())) if m.dato >= siden]

    def hent(self, m: Meddelelse) -> str:
        return m.indhold or net.hent_tekst(m.url)

    def historiske_urls(self, dato: date) -> list[str]:
        v = {"d": dato.day, "dd": f"{dato.day:02d}", "m": dato.month, "mm": f"{dato.month:02d}",
             "mnavn": MÅNEDER[dato.month - 1], "yyyy": dato.year, "yy": f"{dato.year % 100:02d}"}
        sti = f"https://politi.dk/{self.sti}/doegnrapporter/"
        return [sti + s.format(**v) + f"/{dato.year}/{dato.month:02d}/{dato.day:02d}" for s in self.historik]

    def hent_historisk(self, dato: date) -> Meddelelse | None:
        """Prøver skabelonerne en for en; None hvis ingen rapport findes for dagen."""
        for url in self.historiske_urls(dato):
            try:
                side = net.hent_tekst(url, forsøg=2)
            except Exception as e:  # 404 = ikke denne skabelon
                if getattr(e, "code", None) == 404:
                    continue
                raise
            titel = re.search(r"<title>\s*([^<|]+)", side)
            return Meddelelse(url, html.unescape(titel.group(1).strip()) if titel else f"Døgnrapport {dato}",
                              dato, self.udgiver, self.politikreds, side)
        return None

    def parse(self, m: Meddelelse, indhold: str) -> list[Indbrud]:
        if self.format == "afsnit":
            return parse_afsnit_rapport(indhold, m.dato)
        return parse_rapport(indhold, m.dato, m.titel)


class Ritzau:
    """Pressemeddelelser på via.ritzau.dk fra én udgiver (politikredsens nyhedsrum)."""

    udgiver = "Via Ritzau"
    API = "https://via.ritzau.dk/json/v2/releases"

    def __init__(self, politikreds: str, publisher_id: int):
        self.politikreds = politikreds
        self.publisher_id = publisher_id

    def parse_liste(self, data: dict) -> list[Meddelelse]:
        ud = []
        for r in data.get("releases", []):
            dato = dato_fra_tekst(r.get("published", ""))
            if not dato:
                continue
            url = r.get("url") or f"https://via.ritzau.dk/pressemeddelelse/{r['id']}"
            if url.startswith("/"):
                url = "https://via.ritzau.dk" + url
            ud.append(Meddelelse(url, r.get("title", ""), dato, self.udgiver, self.politikreds, r.get("body") or ""))
        return ud

    def find(self, siden: date) -> list[Meddelelse]:
        data = net.hent_json(self.API, params={"publisher": self.publisher_id, "limit": 50})
        return [m for m in self.parse_liste(data) if m.dato >= siden]

    def hent(self, m: Meddelelse) -> str:
        return m.indhold or ""

    def parse(self, m: Meddelelse, indhold: str) -> list[Indbrud]:
        """Først listeformatet ("Døgnets indbrud i privat beboelse"); ellers en enkeltsag,
        hvis titlen begynder med "Indbrud" (fx "Indbrud i frisørsalon i Åbyhøj")."""
        return parse_rapport(indhold, m.dato, m.titel) or parse_afsnit_rapport(indhold, m.dato, m.titel)


# De fem jyske politikredse. Kun Øst- og Nordjylland lægger døgnrapporter på politi.dk;
# de tre andre udgiver kun enkeltsager på Via Ritzau.
KILDER = [
    PolitiDk("Østjyllands Politi", "OEstjyllands-Politi", "oestjyllands-politi", historik=(
        "oestjyllands-politi-uddrag-af-doegnrapporten-{d}-{mnavn}-{yyyy}",
        "doegnrapport{dd}{mm}{yyyy}",
        "oestjyllands-politi-uddrag-af-doegnrapporten-{d}-{mnavn}",
        "uddrag-af-doegnrapporten-{d}-{mnavn}-{yyyy}",
    )),
    PolitiDk("Nordjyllands Politi", "Nordjyllands-Politi", "nordjyllands-politi", format="afsnit"),
    Ritzau("Østjyllands Politi", 90721),
    Ritzau("Sydøstjyllands Politi", 90720),
    Ritzau("Midt- og Vestjyllands Politi", 90687),
    Ritzau("Syd- og Sønderjyllands Politi", 90686),
]


MÅNEDER = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
           "september", "oktober", "november", "december"]


def siden(dage: int, i_dag: date | None = None) -> date:
    return (i_dag or date.today()) - timedelta(days=dage)


__all__ = ["Meddelelse", "PolitiDk", "Ritzau", "KILDER", "siden", "json"]
