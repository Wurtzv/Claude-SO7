"""Udtræk af indbrud fra døgnrapporternes tekst.

Politiet skriver listen med mange små variationer, fx

    På Klintevej i Hammel begået mellem onsdag d. 14/10 og søndag d. 18/10
    Sehierupsvej i Højbjerg mellem d. 12/10 kl. 10.00 til d. 16/10 kl. 08.15
    2 indbrud på Reventlowsvej i Viby - gerningstid 18/10
    Sletterhagevej Risskov d. 15/10 mellem kl. 07.00 og kl. 15.20

Parseren arbejder derfor i to trin: først findes de linjer, der hører til
indbrudslisten (html_til_linjer + find_indbrudslinjer), derefter tolkes hver
linje for sig (parse_linje).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime

# Stavefejl og varianter, der er set i rapporterne.
BY_ALIASER = {
    "riiskov": "Risskov",
    "århus c": "Aarhus C",
    "århus n": "Aarhus N",
    "århus v": "Aarhus V",
    "århus": "Aarhus",
    "viby": "Viby J",
    "tranbjerg": "Tranbjerg J",
    "harlev": "Harlev J",
    "gjerlev": "Gjerlev J",
}

# Byer og bydele, der vises samlet som "Aarhus" i områdefilteret.
AARHUS_OMRAADE = {
    "Aarhus", "Aarhus C", "Aarhus N", "Aarhus V", "Højbjerg", "Risskov", "Egå",
    "Åbyhøj", "Viby J", "Tranbjerg J", "Tilst", "Beder", "Sabro", "Brabrand",
    "Hasle", "Lystrup", "Malling", "Mårslet", "Trige", "Skødstrup", "Harlev J",
    "Solbjerg", "Hjortshøj", "Hjortshøj", "Kolt", "Lisbjerg", "Elsted", "Skejby",
    "Gellerup", "Holme", "Stavtrup", "Hårup", "Ormslev", "Tiset",
}

UGEDAGE = r"(?:mandag|tirsdag|onsdag|torsdag|fredag|lørdag|søndag)"
TAL_ORD = {"et": 1, "ét": 1, "en": 1, "to": 2, "tre": 3, "fire": 4, "fem": 5}

DATO_RE = re.compile(r"(?<![\d/])(\d{1,2})\s?/\s?(\d{1,2})(?![\d/])")
KL_RE = re.compile(r"kl\.?\s*(\d{1,2})[.:](\d{2})")
ANKER_RE = re.compile(r"anmeldt[^.]{0,60}?indbrud i (?:i )?privat beboelse", re.I)
TITEL_RE = re.compile(r"indbrud i privat beboelse", re.I)

# Ord, der markerer hvor bynavnet slutter og gerningstiden begynder.
TID_START_RE = re.compile(
    r"\s+(?:-\s*)?(?:(?:begået|mellem|gerningstid|natten|i tidsrummet|fra|den)\b|d\.|"
    + UGEDAGE + r"|\d{1,2}\s?/)|\s+-\s+|\s*\d{1,2}\s?/\s?\d",
    re.I,
)
VEJ_ENDELSE_RE = re.compile(
    r"^(.*?(?:vej|gade|allé|alle|vænget|vænge|boulevard|stræde|torv|plads|parken|"
    r"haven|bakken|bakke|have|park|sti|stien|toften|lunden|høj|ager|agre|vang|holm|"
    r"engen|marken|kvarter|kæret|kær|dal|dalen|gyde|skov|ringen|krogen|tofte))\s+(\S.*)$",
    re.I,
)


@dataclass
class Tidspunkt:
    dato: date
    tid: str | None = None  # "HH:MM"

    def iso(self) -> str:
        return f"{self.dato.isoformat()}T{self.tid}" if self.tid else self.dato.isoformat()

    def vis(self) -> str:
        s = f"{self.dato.day}/{self.dato.month}"
        return f"{s} kl. {self.tid.replace(':', '.')}" if self.tid else s


@dataclass
class Indbrud:
    vej: str
    by: str
    gerningstid_tekst: str
    fra: Tidspunkt | None = None
    til: Tidspunkt | None = None
    aaben: bool = False  # "begået mellem torsdag d. 15/10" uden slutdato
    antal: int = 1
    type: str = "privat"
    linje: str = field(default="", repr=False)

    @property
    def omraade(self) -> str:
        return omraade_for(self.by)

    def gerningstid(self) -> str:
        """Ensartet visning, fx '12/10 kl. 10.00 – 16/10 kl. 08.15'."""
        if not self.fra:
            return self.gerningstid_tekst
        if self.til is None:
            return ("fra " if self.aaben else "") + self.fra.vis()
        if self.til.dato == self.fra.dato and self.fra.tid and self.til.tid:
            return f"{self.fra.vis()} – {self.til.tid.replace(':', '.')}"
        return f"{self.fra.vis()} – {self.til.vis()}"


def ret_ocr(s: str) -> str:
    """Retter l/I/O, der står for 1 og 0 i datoer og klokkeslæt (fx '16/l0', 'kl. l0.59')."""
    s = re.sub(r"(?<=[\d/.:])[lI]|[lI](?=\d)|(?<=/)[lI]", "1", s)
    s = re.sub(r"(?<=\d)O|O(?=\d)", "0", s)
    return s


def html_til_linjer(markup: str) -> list[str]:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    s = re.sub(r"(?i)<br\s*/?>|</(p|li|div|h\d|tr)>|<(h\d|li|p|ul|ol)\b[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    linjer = (re.sub(r"[ \t\r\f\v]+", " ", l).strip() for l in s.split("\n"))
    return [l for l in linjer if l]


def find_indbrudslinjer(linjer: list[str], titel: str = "") -> list[str]:
    """Returnerer linjerne i listen over indbrud i privat beboelse.

    Listen starter efter sætningen "Der er det seneste døgn anmeldt ... indbrud i
    privat beboelse". Findes den ikke, men handler meddelelsen om døgnets indbrud
    (titlen), bruges hele teksten. Listen stopper ved første linje uden dato.
    """
    start = None
    for i, l in enumerate(linjer):
        if ANKER_RE.search(l):
            start = i + 1
            rest = ANKER_RE.split(l, 1)[-1]
            rest = re.sub(r"^[^:]*?:\s*", "", rest) if ":" in rest else ""
            if rest and DATO_RE.search(ret_ocr(rest)):
                linjer = linjer[: i + 1] + [rest] + linjer[i + 1 :]
            break
    if start is None:
        if not TITEL_RE.search(titel):
            return []
        start = 0
    ud: list[str] = []
    for l in linjer[start:]:
        if l in {"**", "*"}:
            if ud:
                break
            continue
        if not DATO_RE.search(ret_ocr(l)):
            if ud:
                break
            continue
        ud.extend(del_sammenskrevne(l))
    return ud


def del_sammenskrevne(linje: str) -> list[str]:
    """Deler en linje med flere indbrud skrevet i ét, fx
    'Frodesvej I Åbyhøj - gerningstid 13/10-17/10 Kanehaven i Riiskov - gerningstid 12/10-17/10'."""
    if len(re.findall(r"gerningstid", linje, re.I)) < 2:
        return [linje]
    dele = re.split(
        r"(?<=\d)\s+(?=(?:\d+\s+indbrud\s+på\s+)?[A-ZÆØÅ][^\d]*?\s+-\s+(?:gerningstid\s+)?\d)",
        linje,
    )
    return [d.strip() for d in dele if d.strip()]


def _rens_by(by: str) -> str:
    by = by.strip(" ,.-")
    by = re.sub(r"\s+", " ", by)
    key = by.casefold()
    if key in BY_ALIASER:
        return BY_ALIASER[key]
    return by[:1].upper() + by[1:]


def omraade_for(by: str) -> str:
    if by in AARHUS_OMRAADE:
        return "Aarhus"
    return re.sub(r"\s+(C|N|V|J|S|Ø|NV|NØ|SV|SØ)$", "", by)


def _tidspunkter(tekst: str, rapportdato: date) -> list[Tidspunkt]:
    tokens = sorted(
        [(m.start(), "d", m) for m in DATO_RE.finditer(tekst)]
        + [(m.start(), "t", m) for m in KL_RE.finditer(tekst)],
        key=lambda t: t[0],
    )
    # Datoer, der også er en del af et klokkeslæt ("kl. 10/..."), forekommer ikke,
    # men "kl. 10.00" må ikke læses som dato; DATO_RE kræver '/', så det er sikkert.
    ud: list[Tidspunkt] = []
    aktuel: date | None = None
    for _, art, m in tokens:
        if art == "d":
            dag, md = int(m.group(1)), int(m.group(2))
            if not (1 <= md <= 12 and 1 <= dag <= 31):
                continue
            aar = rapportdato.year - (1 if md > rapportdato.month + 1 else 0)
            try:
                aktuel = date(aar, md, dag)
            except ValueError:
                continue
            ud.append(Tidspunkt(aktuel))
        elif aktuel is not None:
            tid = f"{int(m.group(1)):02d}:{m.group(2)}"
            if ud and ud[-1].tid is None and ud[-1].dato == aktuel:
                ud[-1].tid = tid
            else:
                ud.append(Tidspunkt(aktuel, tid))
    return ud


def parse_linje(linje: str, rapportdato: date) -> Indbrud | None:
    rå = linje
    s = ret_ocr(re.sub(r"\s+", " ", linje)).strip(" .;")
    antal = 1
    m = re.match(r"^(\d+|to|tre|fire|fem)\s+indbrud\s+på\s+", s, re.I)
    if m:
        g = m.group(1).lower()
        antal = int(g) if g.isdigit() else TAL_ORD[g]
        s = s[m.end():]
    s = re.sub(r"^(?:på|i)\s+", "", s, flags=re.I)

    t = TID_START_RE.search(s)
    if not t:
        return None
    sted, tid = s[: t.start()].strip(" ,-"), s[t.start():].strip(" ,-")
    if not sted or not DATO_RE.search(tid):
        return None

    m = re.match(r"^(.*?)\s+[iI]\s+(.+)$", sted)
    if m:
        vej, by = m.group(1), m.group(2)
    else:
        m = VEJ_ENDELSE_RE.match(sted)
        vej, by = (m.group(1), m.group(2)) if m else (sted, "")
    vej = re.sub(r"\s+", " ", vej).strip(" ,.")
    if not vej:
        return None

    tid = re.sub(r"^(?:-\s*)?(?:begået|gerningstid)\s*", "", tid, flags=re.I).strip()
    tidspunkter = _tidspunkter(tid, rapportdato)
    ib = Indbrud(
        vej=vej,
        by=_rens_by(by),
        gerningstid_tekst=tid,
        antal=antal,
        linje=rå,
        aaben=bool(re.match(r"(?:mellem|fra)\b", tid, re.I)) and len(tidspunkter) == 1,
    )
    if tidspunkter:
        ib.fra = tidspunkter[0]
        ib.til = tidspunkter[-1] if len(tidspunkter) > 1 else None
    if re.search(r"erhverv|butik|virksomhed|kontor|lager|salon", rå, re.I):
        ib.type = "erhverv"
    return ib


def parse_rapport(markup_eller_linjer, rapportdato: date, titel: str = "") -> list[Indbrud]:
    """Hele kæden: HTML (eller færdige linjer) -> liste af indbrud.

    "2 indbrud på X" bliver til to poster, så optællingen passer.
    """
    linjer = (
        html_til_linjer(markup_eller_linjer)
        if isinstance(markup_eller_linjer, str)
        else list(markup_eller_linjer)
    )
    ud: list[Indbrud] = []
    for l in find_indbrudslinjer(linjer, titel):
        ib = parse_linje(l, rapportdato)
        if ib:
            ud.extend([ib] * ib.antal)
    return ud


def dato_fra_tekst(s: str) -> date | None:
    """'22. oktober 2026' eller ISO-dato -> date."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    md = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
          "september", "oktober", "november", "december"]
    m = re.search(r"(\d{1,2})\.\s*(" + "|".join(md) + r")\s+(\d{4})", s, re.I)
    if m:
        return date(int(m.group(3)), md.index(m.group(2).lower()) + 1, int(m.group(1)))
    return None


__all__ = [
    "Indbrud", "Tidspunkt", "parse_rapport", "parse_linje", "html_til_linjer",
    "find_indbrudslinjer", "omraade_for", "ret_ocr", "dato_fra_tekst", "datetime",
]
