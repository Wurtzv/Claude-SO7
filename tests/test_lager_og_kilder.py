import json
from datetime import date
from pathlib import Path

from indbrudskort.geokod import (Geokoder, linjer_fra_geometri, midtpunkt, samme_vej,
                                 utm32_til_wgs84, vejens_midte)
from indbrudskort.kilder import PolitiDk, Ritzau
from indbrudskort.lager import Lager
from indbrudskort.parse import parse_rapport

FIX = Path(__file__).parent / "fixtures"


def _tilføj(lager, linjer, url, rd):
    return lager.tilføj_rapport(parse_rapport(linjer, rd, "indbrud i privat beboelse"), url=url, titel="t",
                                rapportdato=rd, udgiver="x", politikreds="Østjyllands Politi")


# ---------- dubletter ----------

def test_samme_indbrud_i_to_meddelelser_taelles_en_gang(tmp_path):
    lager = Lager(tmp_path / "indbrud.json")
    assert _tilføj(lager, ["Sophus Bauditz Vej i Åbyhøj d. 17/10 kl. 03.03"], "a", date(2026, 10, 17)) == 1
    assert _tilføj(lager, ["Sophus Bauditz Vej i Åbyhøj - gerningstid 17/10"], "b", date(2026, 10, 18)) == 0
    [r] = lager.indbrud
    assert r["rapportdato"] == "2026-10-17" and r["kilde_url"] == "a"
    assert [k["url"] for k in r["kilder"]] == ["a", "b"]
    assert r["gerningstid"] == "17/10 kl. 03.03"  # den mest detaljerede beholdes


def test_kun_dato_mod_tidsrum_samme_dag_er_samme_indbrud(tmp_path):
    lager = Lager(tmp_path / "indbrud.json")
    _tilføj(lager, ["På Sletterhagevej i Risskov begået torsdag d. 15/10"], "a", date(2026, 10, 16))
    _tilføj(lager, ["Sletterhagevej Risskov d. 15/10 mellem kl. 07.00 og kl. 15.20"], "b", date(2026, 10, 17))
    assert len(lager.indbrud) == 1


def test_to_indbrud_paa_samme_vej_bevares(tmp_path):
    lager = Lager(tmp_path / "indbrud.json")
    assert _tilføj(lager, ["2 indbrud på Reventlowsvej i Viby - gerningstid 18/10"], "a", date(2026, 10, 18)) == 2
    # samme to indbrud nævnt igen dagen efter
    assert _tilføj(lager, ["Reventlowsvej i Viby J d. 18/10", "Reventlowsvej i Viby J d. 18/10"], "b",
                   date(2026, 10, 19)) == 0
    assert len(lager.indbrud) == 2


def test_forskellig_gerningstid_er_forskellige_indbrud(tmp_path):
    lager = Lager(tmp_path / "indbrud.json")
    _tilføj(lager, ["På Cederlunden i Randers SØ begået mellem torsdag d. 8/10 og søndag d. 11/10"], "a", date(2026, 10, 12))
    _tilføj(lager, ["På Cederlunden i Randers SØ begået mellem søndag d. 4/10 og søndag d. 18/10"], "b", date(2026, 10, 19))
    assert len(lager.indbrud) == 2


def test_gem_og_genindlaes(tmp_path):
    lager = Lager(tmp_path / "indbrud.json")
    _tilføj(lager, ["På Klintevej i Hammel begået mellem onsdag d. 14/10 og søndag d. 18/10"], "u", date(2026, 10, 19))
    lager.gem()
    igen = Lager(tmp_path / "indbrud.json")
    assert igen.behandlet == {"u": "2026-10-19"}
    r = igen.indbrud[0]
    assert {"vej", "by", "omraade", "gerningstid", "tid_fra", "tid_til", "rapportdato", "kilde_url", "kilder"} <= r.keys()


# ---------- kilder ----------

def test_politi_oversigt():
    k = PolitiDk("Østjyllands Politi", "OEstjyllands-Politi", "oestjyllands-politi")
    m = k.parse_liste((FIX / "politi_liste_oestjylland.html").read_text("utf-8"))
    assert len(m) == 10
    assert {x.dato for x in m} >= {date(2026, 10, 13), date(2026, 10, 23)}
    assert all(x.url.startswith("https://politi.dk/oestjyllands-politi/doegnrapporter/") for x in m)


def test_ritzau_oversigt():
    data = json.loads((FIX / "ritzau_oestjylland.json").read_text("utf-8"))
    m = Ritzau("Østjyllands Politi", 90721).parse_liste(data)
    x = next(i for i in m if "15229519" in i.url)
    assert x.url.startswith("https://via.ritzau.dk/pressemeddelelse/15229519")
    assert x.dato == date(2026, 10, 17) and x.indhold


# ---------- geokodning (uden netværk) ----------

def test_midtpunkt_langs_vejen():
    lon, lat = midtpunkt([(10.0, 56.0), (10.0, 56.01), (10.02, 56.01)])
    assert abs(lat - 56.01) < 1e-3 and lon > 10.0  # halvvejs ligger på det andet stykke


def test_vejens_midte_ligger_paa_vejen():
    linjer = [[(10.0, 56.0), (10.01, 56.0)], [(10.05, 56.0), (10.06, 56.0)]]
    lon, lat = vejens_midte(linjer)
    assert lat == 56.0 and (10.0 <= lon <= 10.01 or 10.05 <= lon <= 10.06)


def test_utm32():
    lon, lat = utm32_til_wgs84(575000, 6223000)  # ca. Aarhus
    assert abs(lon - 10.2) < 0.05 and abs(lat - 56.15) < 0.05
    assert linjer_fra_geometri("MULTILINESTRING((575000 6223000, 575100 6223100))")[0][0][0] < 11


def test_samme_vej_tillader_smaa_stavefejl():
    assert samme_vej("Ingerslevs Boulevard", "Ingerslev Boulevard")
    assert samme_vej("Sankt Pauls Gade", "Skt. Pauls Gade")
    assert not samme_vej("Egernvej", "Egensvej")


def test_geokoder_bruger_cache(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({"Klintevej|Hammel": {"lat": 56.26, "lon": 9.86, "praecision": "vej", "geokilde": "nominatim"}}))
    g = Geokoder(cache, token="")
    assert g.vej("Klintevej", "Hammel")["lat"] == 56.26  # intet netværkskald
