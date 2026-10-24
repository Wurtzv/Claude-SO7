"""Nyhedskilder. Tilføj en ny politikreds eller kilde ved at tilføje en linje i KILDER."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from . import net
from .parse import dato_fra_tekst


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

    def __init__(self, politikreds: str, distrikt: str, sti: str):
        self.politikreds = politikreds
        self.distrikt = distrikt  # fx "OEstjyllands-Politi"
        self.sti = sti  # fx "oestjyllands-politi"

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
        return net.hent_tekst(m.url)


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


KILDER = [
    PolitiDk("Østjyllands Politi", "OEstjyllands-Politi", "oestjyllands-politi"),
    Ritzau("Østjyllands Politi", 90721),
]


def siden(dage: int, i_dag: date | None = None) -> date:
    return (i_dag or date.today()) - timedelta(days=dage)


__all__ = ["Meddelelse", "PolitiDk", "Ritzau", "KILDER", "siden", "json"]
