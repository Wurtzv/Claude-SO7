"""Tests med gemte rapporter, så ændringer i politiets formulering opdages."""

import json
from datetime import date
from pathlib import Path

import pytest

from indbrudskort.parse import parse_linje, parse_rapport, ret_ocr, omraade_for, dato_fra_tekst

FIX = Path(__file__).parent / "fixtures"
RD = date(2026, 10, 19)


def politi(dato: str):
    return parse_rapport((FIX / f"politi_{dato}.html").read_text("utf-8"), date.fromisoformat(dato))


def ritzau(release_id: int):
    data = json.loads((FIX / "ritzau_oestjylland.json").read_text("utf-8"))
    r = next(x for x in data["releases"] if x["id"] == release_id)
    return parse_rapport(r["body"], date.fromisoformat(r["published"][:10]), r["title"])


# ---------- enkelte linjer ----------

def test_standardformat():
    ib = parse_linje("På Klintevej i Hammel begået mellem onsdag d. 14/10 og søndag d. 18/10", RD)
    assert (ib.vej, ib.by) == ("Klintevej", "Hammel")
    assert ib.fra.iso() == "2026-10-14" and ib.til.iso() == "2026-10-18"
    assert ib.gerningstid() == "14/10 – 18/10"
    assert ib.type == "privat"


def test_enkelt_dag():
    ib = parse_linje("På Skt. Pauls Gade i Aarhus C begået mandag d. 19/10", RD)
    assert (ib.vej, ib.by, ib.gerningstid()) == ("Skt. Pauls Gade", "Aarhus C", "19/10")
    assert ib.til is None


def test_klokkeslaet_med_kolon_og_samme_dag():
    ib = parse_linje("På Farøvænget i Tilst begået den 10/10 mellem kl. 10:45 og den kl. 17:07.", RD)
    assert ib.fra.iso() == "2026-10-10T10:45" and ib.til.iso() == "2026-10-10T17:07"
    assert ib.gerningstid() == "10/10 kl. 10.45 – 17.07"


def test_aaben_periode():
    ib = parse_linje("På Åskrænten i Egå begået mellem torsdag d. 15/10", RD)
    assert ib.aaben and ib.gerningstid() == "fra 15/10"


def test_ocr_fejl_rettes():
    assert ret_ocr("d. 16/l0 kl. 15.00") == "d. 16/10 kl. 15.00"
    assert ret_ocr("d. l5/10 kl. l0.59") == "d. 15/10 kl. 10.59"
    ib = parse_linje("Østervænget i Tilst d. l5/10 kl. l0.59", RD)
    assert ib.fra.iso() == "2026-10-15T10:59"


def test_mangler_i_mellem_vej_og_by():
    ib = parse_linje("Sletterhagevej Risskov d. 15/10 mellem kl. 07.00 og kl. 15.20", RD)
    assert (ib.vej, ib.by) == ("Sletterhagevej", "Risskov")
    ib = parse_linje("På Holmgårdsvej Randers SØ begået den 10/10 kl. 18:30.", RD)
    assert (ib.vej, ib.by) == ("Holmgårdsvej", "Randers SØ")


def test_stavefejl_i_bynavn():
    assert parse_linje("Kanehaven i Riiskov - gerningstid 12/10-17/10", RD).by == "Risskov"
    assert parse_linje("Visbygade i Århus N - 09/10-17/10", RD).by == "Aarhus N"
    assert parse_linje("Frodesvej I Åbyhøj - gerningstid 13/10-17/10", RD).by == "Åbyhøj"


def test_antal_indbrud_paa_samme_vej():
    ib = parse_linje("2 indbrud på Reventlowsvej i Viby - gerningstid 18/10", RD)
    assert (ib.antal, ib.vej, ib.by) == (2, "Reventlowsvej", "Viby J")


def test_aarsskifte():
    ib = parse_linje("På Testvej i Hammel begået mellem d. 28/12 og d. 2/1", date(2027, 1, 3))
    assert ib.fra.iso() == "2026-12-28" and ib.til.iso() == "2027-01-02"


def test_omraade():
    assert omraade_for("Viby J") == "Aarhus"
    assert omraade_for("Randers NØ") == "Randers"
    assert omraade_for("Hammel") == "Hammel"


def test_dato_fra_tekst():
    assert dato_fra_tekst("Østjyllands Politi: uddrag af døgnrapporten 22. oktober 2026") == date(2026, 10, 22)
    assert dato_fra_tekst("2026-10-17T10:50:58+02:00") == date(2026, 10, 17)


# ---------- hele, gemte rapporter ----------

@pytest.mark.parametrize("dato,antal,første", [
    ("2026-10-11", 6, ("Energivej", "Randers NV")),       # <p>-afsnit, "Indbrud i privat beboelse" som h3
    ("2026-10-12", 1, ("Cederlunden", "Randers SØ")),
    ("2026-10-13", 4, ("Kornbakken", "Malling")),         # <br>-linjer i stedet for <li>
    ("2026-10-15", 1, ("Frederiksgade", "Randers NØ")),
    ("2026-10-16", 5, ("Østervænget", "Tilst")),
    ("2026-10-19", 8, ("Klintevej", "Hammel")),           # anden overskrift "Indbrud udviklede sig til røveri" først
    ("2026-10-20", 6, ("Karetmagervej", "Randers NV")),
    ("2026-10-21", 1, ("Åskrænten", "Egå")),
    ("2026-10-22", 1, ("Ingerslev Boulevard", "Aarhus C")),
    ("2026-10-23", 7, ("Solbakkevej", "Viby J")),
])
def test_politi_rapporter(dato, antal, første):
    r = politi(dato)
    assert len(r) == antal
    assert (r[0].vej, r[0].by) == første
    assert all(i.fra is not None for i in r)


def test_ingen_falske_indbrud_fra_brodtekst():
    # 22/10 nævner "10 forskellige indbrud", Låsby, Harlev J osv. i en anden artikel.
    r = politi("2026-10-22")
    assert [(i.vej, i.by) for i in r] == [("Ingerslev Boulevard", "Aarhus C")]


def test_ritzau_doegnets_indbrud():
    r = ritzau(15229519)
    assert len(r) == 8
    assert r[0].gerningstid() == "12/10 kl. 10.00 – 16/10 kl. 08.15"
    assert r[1].gerningstid() == "13/10 kl. 13.00 – 16/10 kl. 15.00"  # "16/l0"


def test_ritzau_doegnrapport_med_to_paa_samme_vej():
    r = ritzau(15230173)
    assert len(r) == 7
    assert [i.vej for i in r].count("Reventlowsvej") == 2
    assert r[-1].vej == "Visbygade" and r[-1].gerningstid() == "9/10 – 17/10"


def test_ritzau_andre_meddelelser_ignoreres():
    assert ritzau(15229496) == []  # "Indbrud i frisørsalon" er ikke døgnets liste
    assert ritzau(15225189) == []  # døgnrapport udgivet som billeder


# ---------- ældre formater (2026 og tidligere) ----------

@pytest.mark.parametrize("linje,vej,by", [
    ("På Hellerupvej 003 8000 Aarhus C fredag den 21/8 26 kl.1700 til lørdag den 22/8 26 kl.08.30", "Hellerupvej", "Aarhus C"),
    ("På Søkjærvej 009 8260 Viby J i Aarhus begået den fredag den 14/8 26 kl.12.30", "Søkjærvej", "Viby J"),
    ("På Tornhøjvej, 8260 Viby J, begået mellem fredag den 28/8 kl. 14:00 og lørdag den 29/8 kl. 09:45", "Tornhøjvej", "Viby J"),
    ("På J. L. Heibergs Vej, 8230 Åbyhøj, begået mellem onsdag den 26/8 kl. 17:00 og fredag den 28/8", "J. L. Heibergs Vej", "Åbyhøj"),
    ("På Møllevangen i Hammelegået mellem d. 19/9 og d. 20/9", "Møllevangen", "Hammel"),
    ("På Balagervej i Viby i begået mellem den 06/07 kl. 08.00 og den 10/07 kl. 13.45.", "Balagervej", "Viby J"),
    ("På Markedsgade i Grenå begået mellem den 09/7 kl. 08.13 og den 10/7 kl. 08.00.", "Markedsgade", "Grenaa"),
])
def test_aeldre_formater(linje, vej, by):
    ib = parse_linje(linje, date(2026, 8, 30))
    assert (ib.vej, ib.by) == (vej, by)


def test_loesrevet_stump_ignoreres():
    assert parse_linje("00 og lørdag den 29/8 kl. 08:00", date(2026, 8, 30)) is None
