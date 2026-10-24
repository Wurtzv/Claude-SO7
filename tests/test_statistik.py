from pathlib import Path

from indbrudskort.statistik import byg, er_jysk, parse_bulk

FIX = Path(__file__).parent / "fixtures"


def test_parse_bulk():
    r = parse_bulk((FIX / "statbank_straf11.csv").read_text("utf-8"))
    assert r[0] == ("000", "Hele landet", "2025K3", 3671)
    assert ("751", "Aarhus", "2026K3", 491) in r


def test_kun_jyske_kommuner():
    assert er_jysk("751") and er_jysk("851") and er_jysk("563")  # Aarhus, Aalborg, Fanø
    assert not er_jysk("461") and not er_jysk("101") and not er_jysk("083") and not er_jysk("998")


def test_byg():
    rækker = parse_bulk((FIX / "statbank_straf11.csv").read_text("utf-8"))
    d = byg(rækker, {"751": 378270}, lambda navn: (10.2, 56.15))
    navne = {k["navn"] for k in d["kommuner"]}
    assert {"Aarhus", "Viborg", "Herning", "Sønderborg", "Esbjerg"} <= navne
    assert not navne & {"Odense", "København", "Uoplyst kommune"}
    aarhus = next(k for k in d["kommuner"] if k["navn"] == "Aarhus")
    assert aarhus["antal"]["2026K3"] == 491 and aarhus["indbyggere"] == 378270
    assert d["kvartaler"][-1] == "2026K3" and len(d["kvartaler"]) == 5
