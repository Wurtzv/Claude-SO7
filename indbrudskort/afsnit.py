"""Indbrud beskrevet som nyhedsafsnit, sådan som fx Nordjyllands Politi skriver dem:

    Indbrud i villa
    Onsdag aften blev der anmeldt et indbrud i Vodskov. Gerningspersonerne var ...

    Indbrud i Aalborg
    Natten til onsdag har der været indbrud i to villaer i Vejgaard-området. ...

Her står der som regel kun by eller bydel og en ugedag, ikke en vej. Punkterne
placeres derfor ved byen (praecision "by"), medmindre afsnittet nævner en vej.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .parse import (ANKER_RE, BY_ALIASER, Indbrud, Tidspunkt, VEJ_ENDELSE_RE, _tidspunkter,
                    html_til_linjer)

UGEDAGE = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
TAL = {"to": 2, "tre": 3, "fire": 4, "fem": 5, "seks": 6}

OVERSKRIFT_RE = re.compile(r"^(?:indbrud|indbrudstyveri)\b", re.I)
UDELAD_RE = re.compile(r"forsøg|forebyg|forebryg|røveri|anholdt|sigtet|bil\b|varebil|bilen|båd", re.I)
PRIVAT_RE = re.compile(
    r"villa|rækkehus|parcelhus|lejlighed|bolig|beboelse|fritidshus|sommerhus|landejendom|"
    r"kolonihave|\bhus\b|\bhuse\b|huset|husene|\bhjem|køkken|soveværelse|\bstue\b|skuffer og skabe", re.I)
ERHVERV_RE = re.compile(
    r"virksomhed|butik|prøvehus|værksted|firma|kontor|lager|forretning|salon|byggeplads|restaurant|"
    r"kiosk|skole|institution|kirke|lade|klub|hal\b|frisør|tankstation|fabrik", re.I)
STED_RE = re.compile(
    r"\bi ([A-ZÆØÅ][\wæøåÆØÅ]+(?:[ -](?:[A-ZÆØÅ][\wæøåÆØÅ]*|kommune|midtby|Midtby|SØ|SV|NØ|NV|Ø|V|N|C|S))*)"
    r"(?:-området| området|-omr\.)?")
IKKE_STED = set(UGEDAGE) | {"weekenden", "løbet", "forbindelse", "den", "det"}


def _sted(tekst: str) -> str | None:
    for m in STED_RE.finditer(tekst):
        s = m.group(1).strip()
        if s.split()[0].casefold() in IKKE_STED:
            continue
        s = re.sub(r"[ -](?:midtby|Midtby)$", "", s)
        s = re.sub(r"\bkommune$", "Kommune", s)
        s = re.sub(r"^(\w+)s (Vestby|Østby|Nordby|Sydby|Midtby)$", r"\1", s)  # "Aalborgs Vestby"
        return BY_ALIASER.get(s.casefold(), s)
    return None


def _vej(tekst: str) -> str:
    m = re.search(r"\bpå ([A-ZÆØÅ][\wæøåÆØÅ.\- ]{2,40}?)(?= i |[.,]| ved )", tekst)
    if m and VEJ_ENDELSE_RE.match(m.group(1) + " x"):
        return m.group(1).strip()
    return ""


def _dato_for_ugedag(navn: str, rapportdato: date) -> date:
    """Seneste dato med den ugedag på eller før rapportdatoen."""
    mål = UGEDAGE.index(navn.lower())
    return rapportdato - timedelta(days=(rapportdato.weekday() - mål) % 7)


def _tid(tekst: str, rapportdato: date) -> tuple[str, Tidspunkt | None, Tidspunkt | None]:
    eksplicit = _tidspunkter(tekst, rapportdato)
    if eksplicit:
        return "", eksplicit[0], eksplicit[-1] if len(eksplicit) > 1 else None
    if re.search(r"i løbet af weekenden|over weekenden", tekst, re.I):
        lør = _dato_for_ugedag("lørdag", rapportdato)
        return "Weekenden", Tidspunkt(lør), Tidspunkt(lør + timedelta(days=1))
    m = re.search(r"(natten til |i løbet af )?(" + "|".join(UGEDAGE) + r")(?:\s+(morgen|formiddag|middag|eftermiddag|aften|nat))?",
                  tekst, re.I)
    if not m:
        return "", None, None
    d = _dato_for_ugedag(m.group(2), rapportdato)
    tekst_ = " ".join(x.strip() for x in (m.group(1) or "", m.group(2).lower(), m.group(3) or "") if x.strip())
    return tekst_[:1].upper() + tekst_[1:], Tidspunkt(d), None


def find_afsnit(linjer: list[str]) -> list[tuple[str, str]]:
    """(overskrift, brødtekst) for hvert afsnit, hvis overskrift begynder med 'Indbrud'."""
    ud = []
    for i, l in enumerate(linjer):
        if not (OVERSKRIFT_RE.match(l) and len(l) < 70 and not l.rstrip().endswith((".", ":"))):
            continue
        brød = []
        for næste in linjer[i + 1 : i + 5]:
            if len(næste) < 70 and not næste.rstrip().endswith((".", "!", "?")):
                break  # næste overskrift
            if næste.startswith(("Har du set", "Har du oplysninger")):
                break
            brød.append(næste)
        if brød:
            ud.append((l.strip(), " ".join(brød)))
    return ud


def parse_afsnit(overskrift: str, brød: str, rapportdato: date) -> list[Indbrud]:
    hele = f"{overskrift}. {brød}"
    første = re.split(r"(?<=\.)\s", brød, maxsplit=1)[0]
    if (UDELAD_RE.search(overskrift) or ANKER_RE.search(brød)
            or re.search(r"\b(?:fra|i) en (?:vare)?bil\b", første, re.I)):
        return []
    if ERHVERV_RE.search(overskrift) or (ERHVERV_RE.search(første) and not PRIVAT_RE.search(overskrift)):
        type_ = "erhverv"
    elif PRIVAT_RE.search(overskrift) or PRIVAT_RE.search(brød):
        type_ = "privat"
    else:
        type_ = "andet"  # fx garage, skur, kælderrum

    by = _sted(første) or _sted(overskrift)
    if not by:
        return []
    vej = _vej(første)
    tidsangivelse, fra, til = _tid(første, rapportdato)
    m = re.search(r"\bi (" + "|".join(TAL) + r") (?:villaer|huse|lejligheder|rækkehuse|boliger|fritidshuse|sommerhuse)", første, re.I)
    antal = TAL[m.group(1).lower()] if m else 1
    ib = Indbrud(
        vej=vej, by=by, gerningstid_tekst=tidsangivelse or "ikke oplyst", fra=fra, til=til, antal=antal,
        type=type_, linje=hele, beskrivelse=brød.strip(), tidsangivelse=tidsangivelse,
    )
    return [ib] * antal


def parse_afsnit_rapport(markup_eller_linjer, rapportdato: date, titel: str = "") -> list[Indbrud]:
    linjer = (html_til_linjer(markup_eller_linjer) if isinstance(markup_eller_linjer, str)
              else list(markup_eller_linjer))
    if titel and OVERSKRIFT_RE.match(titel):  # en Ritzau-meddelelse er ét afsnit med titlen som overskrift
        linjer = [titel] + linjer
    ud: list[Indbrud] = []
    for overskrift, brød in find_afsnit(linjer):
        ud += parse_afsnit(overskrift, brød, rapportdato)
    return ud
