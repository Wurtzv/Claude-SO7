"""Indbrud skrevet som nyhedsafsnit (Nordjyllands Politi og enkeltsager på Via Ritzau)."""

import json
from datetime import date
from pathlib import Path

import pytest

from indbrudskort.afsnit import parse_afsnit, parse_afsnit_rapport
from indbrudskort.kilder import KILDER, Meddelelse, PolitiDk, Ritzau

FIX = Path(__file__).parent / "fixtures"
FRE = date(2026, 10, 23)  # fredag


def nord(dato: str):
    return parse_afsnit_rapport((FIX / f"nordjylland_{dato}.html").read_text("utf-8"), date.fromisoformat(dato))


def test_to_villaer_i_bydel():
    r = parse_afsnit("Indbrud i Aalborg", "Natten til onsdag har der været indbrud i to villaer i Vejgaard-området. "
                     "I begge tilfælde er gerningspersonerne kommet ind gennem et opbrudt vindue.", FRE)
    assert len(r) == 2
    assert (r[0].vej, r[0].by, r[0].omraade, r[0].type) == ("", "Vejgaard", "Aalborg", "privat")
    assert r[0].fra.iso() == "2026-10-21" and r[0].gerningstid() == "Natten til onsdag 21/10"


def test_by_kun_i_overskriften():
    [ib] = parse_afsnit("Indbrud i Støvring", "Der blev onsdag eftermiddag anmeldt et indbrud i flere huse under renovering.", FRE)
    assert (ib.by, ib.type) == ("Støvring", "privat")


def test_vej_naevnt_og_erhverv():
    [ib] = parse_afsnit("Indbrud i prøvehus", "Der har natten til torsdag været indbrud i et prøvehus på Boysenbærvej i Ålbæk. "
                        "Tyvene kom ind gennem en opbrudt dør.", date(2026, 10, 16))
    assert (ib.vej, ib.by, ib.type) == ("Boysenbærvej", "Ålbæk", "erhverv")


def test_kommune_og_genitiv():
    [ib] = parse_afsnit("Indbrud i villa", "Der blev lørdag formiddag anmeldt et indbrud i Vesthimmerlands kommune. "
                        "Tyvene havde fundet vej gennem en knust rude.", date(2026, 10, 6))
    assert ib.by == "Vesthimmerlands Kommune" and ib.fra.iso() == "2026-10-03"
    [ib] = parse_afsnit("Indbrud i Vestbyen", "Der har i løbet af weekenden været indbrud i et hus i Aalborgs Vestby.",
                        date(2026, 9, 29))
    assert ib.by == "Aalborg" and ib.gerningstid() == "Weekenden 26/9 – 27/9"


@pytest.mark.parametrize("overskrift,brød", [
    ("Indbrud i varebil", "Der blev lørdag morgen anmeldt et indbrud fra en varebil i Nørresundby."),
    ("Forsøg på indbrud", "Natten til fredag forsøgte to mænd at bryde ind i et hus i Hobro."),
    ("Tyveri fra kælderrum", "Der blev onsdag aften anmeldt et tyveri fra Aalborg midtby."),
])
def test_ikke_indbrud_i_bygning(overskrift, brød):
    assert parse_afsnit_rapport([overskrift, brød], FRE) == []


@pytest.mark.parametrize("dato,antal", [
    ("2026-09-25", 1), ("2026-09-29", 3), ("2026-10-02", 2), ("2026-10-06", 4), ("2026-10-09", 3),
    ("2026-10-13", 3), ("2026-10-16", 3), ("2026-10-20", 1), ("2026-10-23", 7),
])
def test_nordjylland_rapporter(dato, antal):
    r = nord(dato)
    assert len(r) == antal
    assert all(i.by and i.fra for i in r)


def test_nordjylland_23_oktober():
    r = nord("2026-10-23")
    assert [(i.by, i.type) for i in r] == [
        ("Vejgaard", "privat"), ("Vejgaard", "privat"), ("Svenstrup", "erhverv"), ("Vodskov", "privat"),
        ("Hirtshals", "erhverv"), ("Løkken", "privat"), ("Hobro", "privat"),
    ]


def test_oestjyllands_liste_tolkes_ikke_som_afsnit():
    # Østjyllands "Indbrud"-overskrift efterfølges af listen, ikke af et nyhedsafsnit.
    oj = KILDER[0]
    html = (FIX / "politi_2026-10-22.html").read_text("utf-8")
    m = Meddelelse("u", "t", date(2026, 10, 22), "politi.dk", "Østjyllands Politi")
    assert [(i.vej, i.by) for i in oj.parse(m, html)] == [("Ingerslev Boulevard", "Aarhus C")]


def test_nordjylland_oversigt():
    k = PolitiDk("Nordjyllands Politi", "Nordjyllands-Politi", "nordjyllands-politi", format="afsnit")
    m = k.parse_liste((FIX / "politi_liste_nordjylland.html").read_text("utf-8"))
    assert len(m) == 9 and all("/nordjyllands-politi/doegnrapporter/" in x.url for x in m)


def test_ritzau_enkeltsag_og_liste():
    data = json.loads((FIX / "ritzau_oestjylland.json").read_text("utf-8"))
    k = Ritzau("Østjyllands Politi", 90721)
    med = {m.url.split("/")[4]: m for m in k.parse_liste(data)}
    [ib] = k.parse(med["15229496"], med["15229496"].indhold)  # "Indbrud i frisørsalon i Åbyhøj"
    assert (ib.by, ib.type, ib.fra.iso()) == ("Åbyhøj", "erhverv", "2026-10-16")
    assert len(k.parse(med["15229519"], med["15229519"].indhold)) == 8  # listeformatet vinder
    assert k.parse(med["15229508"], med["15229508"].indhold) == []  # "Brand i personbiler i Risskov"


def test_alle_jyske_kredse_er_med():
    assert {k.politikreds for k in KILDER} == {
        "Østjyllands Politi", "Nordjyllands Politi", "Sydøstjyllands Politi",
        "Midt- og Vestjyllands Politi", "Syd- og Sønderjyllands Politi",
    }
