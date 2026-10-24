from datetime import date

from indbrudskort import ugerapport


def _r(dato, by, vej="", pnr=None, kreds="Østjyllands Politi"):
    r = {"rapportdato": dato, "by": by, "vej": vej, "politikreds": kreds}
    if pnr:
        r["postnr"] = pnr
    return r


DATA = [
    # denne uge (17.–23. okt.)
    _r("2026-10-23", "Viby J", "Reventlowsvej", "8260"),
    _r("2026-10-22", "Viby J", "Reventlowsvej", "8260"),
    _r("2026-10-20", "Viby J", "Skanderborgvej", "8260"),
    _r("2026-10-17", "Risskov", "Sletterhagevej", "8240"),
    _r("2026-10-18", "Risskov", "Fortevej", "8240"),
    _r("2026-10-19", "Hammel", "Klintevej", "8450"),
    # ugen før (10.–16. okt.)
    _r("2026-10-16", "Risskov", "Fortevej", "8240"),
    _r("2026-10-15", "Risskov", "Fortevej", "8240"),
    _r("2026-10-14", "Risskov", "Fortevej", "8240"),
    _r("2026-10-12", "Hammel", "Klintevej", "8450"),
    # for gammel
    _r("2026-10-01", "Viby J", "Reventlowsvej", "8260"),
]


def test_sammenlign_uge_mod_ugen_foer():
    u = ugerapport.sammenlign(DATA, date(2026, 10, 23))
    assert (u["fra"], u["til"], u["foer_fra"], u["foer_til"]) == ("2026-10-17", "2026-10-23", "2026-10-10", "2026-10-16")
    assert (u["antal"], u["foer"]) == (6, 4)
    stig = u["bydele"]["stigning"]
    assert [(r["navn"], r["antal"], r["foer"]) for r in stig] == [("Viby J", 3, 0)]  # Risskov faldt, Hammel kun 1
    assert u["postnumre"]["stigning"][0]["navn"] == "8260"
    assert u["postnumre"]["stigning"][0]["byer"] == ["Viby J"]
    assert u["veje"]["stigning"][0]["navn"] == "Reventlowsvej, Viby J"
    assert u["bydele"]["flest"][0]["navn"] == "Viby J"


def test_byg_bruger_nyeste_rapportdato_og_dst():
    stat = {"kvartaler": ["2025K3", "2026K2", "2026K3"], "kommuner": [
        {"navn": "Aarhus", "husstande": 170000, "antal": {"2025K3": 348, "2026K3": 491}},
        {"navn": "Odder", "husstande": 10000, "antal": {"2025K3": 20, "2026K3": 12}},
    ]}
    d = ugerapport.byg(DATA, stat)
    assert d["uge"]["til"] == "2026-10-23"
    assert d["kredse"] == ["Østjyllands Politi"]
    assert d["dst"]["kvartal"] == "2026K3" and d["dst"]["fjor"] == "2025K3"
    assert [r["navn"] for r in d["dst"]["stigning"]] == ["Aarhus"]
    md = ugerapport.markdown(d, "https://eksempel.dk/")
    assert "Viby J | 3 | 0 | +3" in md
    assert "8260 (Viby J)" in md
    assert "Aarhus: 491 indbrud (+143)" in md
    assert "https://eksempel.dk/" in md
