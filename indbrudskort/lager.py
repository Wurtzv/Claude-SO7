"""data/indbrud.json: indlæsning, fletning uden dubletter og gemning."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .parse import Indbrud


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
