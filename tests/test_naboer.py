import json
from datetime import date

from indbrudskort import naboer
from indbrudskort.geokod import afstand_km


def test_proevepunkter_ligger_i_ringene():
    pkt = naboer.prøvepunkter(56.124357, 10.160625)
    assert len(pkt) == 20
    for meter, la, lo in pkt:
        assert abs(afstand_km((10.160625, 56.124357), (lo, la)) * 1000 - meter) < 5


def _falsk_vejnavn(la, lo):
    # nord for punktet: Bernstorffsvej; syd: Sønderhøj; øst/vest: indbruddets egen vej
    if la > 56.1255:
        return "Bernstorffsvej"
    if la < 56.1232:
        return "Sønderhøj"
    return "Reventlowsvej"


def test_naboveje_udelader_egen_vej_og_tager_mindste_afstand():
    v = naboer.naboveje(56.124357, 10.160625, "Reventlowsvej", _falsk_vejnavn)
    assert [x["vej"] for x in v] == ["Bernstorffsvej", "Sønderhøj"]
    assert all(x["m"] == 150 for x in v)


def test_opdater_genbruger_og_rydder_gamle(tmp_path):
    fil = tmp_path / "naboveje.json"
    fil.write_text(json.dumps({"56.1244,10.1606": [{"vej": "Gemt", "m": 150}], "55.0000,9.0000": []}))
    indbrud = [
        {"rapportdato": "2026-10-23", "lat": 56.124357, "lon": 10.160625, "praecision": "vej", "vej": "Reventlowsvej"},
        {"rapportdato": "2026-10-22", "lat": 56.2, "lon": 10.2, "praecision": "vej", "vej": "Reventlowsvej"},
        {"rapportdato": "2026-10-22", "lat": 56.3, "lon": 10.3, "praecision": "by", "vej": ""},
        {"rapportdato": "2026-08-01", "lat": 56.4, "lon": 10.4, "praecision": "vej", "vej": "X"},
    ]
    kald = []
    d = naboer.opdater(indbrud, fil, lambda la, lo: kald.append(1) or "Nabovej", i_dag=date(2026, 10, 24))
    assert d["56.1244,10.1606"] == [{"vej": "Gemt", "m": 150}]      # genbrugt
    assert d["56.2000,10.2000"] == [{"vej": "Nabovej", "m": 150}]   # nyt punkt
    assert set(d) == {"56.1244,10.1606", "56.2000,10.2000"}          # by-præcision og gamle udeladt
    assert len(kald) == 20
