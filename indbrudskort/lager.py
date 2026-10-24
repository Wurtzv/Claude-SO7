"""data/indbrud.json: indlæsning, fletning uden dubletter og gemning."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .parse import Indbrud, omraade_for, rens_sted


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9æøå]", "", s.casefold().replace("århus", "aarhus"))


def basisnøgle(vej: str, by: str, tid_fra: str | None, tid_til: str | None) -> str:
    """Samme vej + bydel + gerningstid = samme indbrud.

    Kun datoerne bruges, fordi den samme sag kan stå som "17/10" i én meddelelse
    og "17/10 kl. 03.03" i en anden. En slutdato lig startdatoen tæller som ingen.
    """
    fra = (tid_fra or "")[:10]
    til = (tid_til or "")[:10]
    if til == fra:
        til = ""
    return f"{_norm(vej)}|{_norm(by)}|{fra}|{til}"


def _detaljegrad(r: dict) -> int:
    return len(r.get("tid_fra") or "") + len(r.get("tid_til") or "")


class Lager:
    def __init__(self, fil: Path):
        self.fil = Path(fil)
        data = json.loads(self.fil.read_text("utf-8")) if self.fil.exists() else {}
        self.indbrud: list[dict] = data.get("indbrud", [])
        self.behandlet: dict[str, str] = data.get("behandlede_meddelelser", {})
        self._indeks = {r["id"]: r for r in self.indbrud}

    def tilføj_rapport(self, poster: list[Indbrud], *, url: str, titel: str, rapportdato: date,
                       udgiver: str, politikreds: str) -> int:
        """Fletter én meddelelses indbrud ind. Returnerer antal nye indbrud.

        To ens linjer i samme meddelelse (fx "2 indbrud på Reventlowsvej") er to
        indbrud; de får løbenummer 1 og 2. Står de igen i en anden meddelelse, er
        det de samme to.
        """
        kilde = {"url": url, "titel": titel, "rapportdato": rapportdato.isoformat(), "udgiver": udgiver}
        tælling: dict[str, int] = {}
        nye = 0
        for ib in poster:
            fra = ib.fra.iso() if ib.fra else None
            til = ib.til.iso() if ib.til else None
            basis = basisnøgle(ib.vej, ib.by, fra, til)
            tælling[basis] = tælling.get(basis, 0) + 1
            id_ = hashlib.sha1(f"{basis}|{tælling[basis]}".encode()).hexdigest()[:12]
            ny = {
                "id": id_,
                "vej": ib.vej,
                "by": ib.by,
                "omraade": ib.omraade,
                "type": ib.type,
                "gerningstid": ib.gerningstid(),
                "tid_fra": fra,
                "tid_til": til,
                "rapportdato": rapportdato.isoformat(),
                "kilde_url": url,
                "politikreds": politikreds,
                "kilder": [kilde],
            }
            if ib.beskrivelse:
                ny["beskrivelse"] = ib.beskrivelse
            gammel = self._indeks.get(id_)
            if gammel is None:
                self.indbrud.append(ny)
                self._indeks[id_] = ny
                nye += 1
                continue
            if url not in {k["url"] for k in gammel["kilder"]}:
                gammel["kilder"].append(kilde)
                gammel["kilder"].sort(key=lambda k: k["rapportdato"])
            if _detaljegrad(ny) > _detaljegrad(gammel):
                for k in ("gerningstid", "tid_fra", "tid_til"):
                    gammel[k] = ny[k]
            if ny["rapportdato"] < gammel["rapportdato"]:
                gammel["rapportdato"], gammel["kilde_url"] = ny["rapportdato"], url
        self.behandlet[url] = rapportdato.isoformat()
        return nye

    def normaliser(self) -> int:
        """Retter vej/by i gemte poster med den nuværende parser-logik og fletter poster,
        der derved bliver til det samme indbrud. Returnerer antal ændrede poster."""
        ændret = 0
        nye: dict[str, dict] = {}
        tælling: dict[tuple[str, str], int] = {}
        for r in sorted(self.indbrud, key=lambda r: (r["rapportdato"], r["kilde_url"], r["id"])):
            vej, by, nær = rens_sted(r["vej"], r["by"])
            if not by and re.match(r"^\d", vej):  # løsrevet linjestump, ikke et indbrud
                ændret += 1
                continue
            if (vej, by) != (r["vej"], r["by"]):
                ændret += 1
                r.update(vej=vej, by=by, omraade=omraade_for(nær or by))
                for k in ("lat", "lon", "praecision", "geokilde", "postnr"):
                    r.pop(k, None)
            basis = basisnøgle(vej, by, r.get("tid_fra"), r.get("tid_til"))
            k = (basis, r["kilde_url"])
            tælling[k] = tælling.get(k, 0) + 1
            id_ = hashlib.sha1(f"{basis}|{tælling[k]}".encode()).hexdigest()[:12]
            if id_ in nye:  # samme indbrud set i en tidligere meddelelse
                g = nye[id_]
                for kilde in r["kilder"]:
                    if kilde["url"] not in {x["url"] for x in g["kilder"]}:
                        g["kilder"].append(kilde)
                continue
            r["id"] = id_
            nye[id_] = r
        self.indbrud = list(nye.values())
        self._indeks = dict(nye)
        return ændret

    def mangler_koordinater(self) -> list[dict]:
        return [r for r in self.indbrud if r.get("lat") is None or r.get("praecision") == "by"]

    def gem(self):
        self.indbrud.sort(key=lambda r: (r["rapportdato"], r.get("tid_fra") or "", r["vej"]), reverse=True)
        data = {
            "opdateret": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "antal": len(self.indbrud),
            "indbrud": self.indbrud,
            "behandlede_meddelelser": dict(sorted(self.behandlet.items())),
        }
        self.fil.parent.mkdir(parents=True, exist_ok=True)
        self.fil.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
