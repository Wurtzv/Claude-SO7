"""Ugentlig opsummering: hvor steg indbruddene mest den seneste uge?

Sammenligner de seneste 7 dages døgnrapporter med de 7 dage før – pr. bydel, postnummer
og vej – og tager de største stigninger i Danmarks Statistiks kommunetal med. Resultatet
gemmes som data/ugerapport.json (til kortsiden) og som Markdown (til GitHub-issuet,
som sendes på mail til dem, der følger repoet).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DAGE = 7
TOP = 10


def _periode(slut: date, dage: int) -> tuple[str, str]:
    return (slut - timedelta(days=dage - 1)).isoformat(), slut.isoformat()


def _nøgler(r: dict) -> dict[str, str | None]:
    return {
        "bydele": r.get("by") or None,
        "postnumre": r.get("postnr") or None,
        "veje": f"{r['vej']}, {r['by']}" if r.get("vej") and r.get("by") else None,
    }


def sammenlign(indbrud: list[dict], slut: date, dage: int = DAGE) -> dict:
    """Tæller indbrud pr. bydel/postnummer/vej i perioden, der slutter `slut`, og i
    perioden lige før. Rapportdatoen bruges, da gerningstiden ofte er et interval."""
    nu_fra, nu_til = _periode(slut, dage)
    før_fra, før_til = _periode(slut - timedelta(days=dage), dage)
    nu: dict[str, Counter] = {k: Counter() for k in ("bydele", "postnumre", "veje")}
    før: dict[str, Counter] = {k: Counter() for k in nu}
    kreds: dict[tuple[str, str], str] = {}
    by_for_pnr: dict[str, Counter] = {}
    i_alt = [0, 0]
    for r in indbrud:
        d = r["rapportdato"]
        if nu_fra <= d <= nu_til:
            tæl, i = nu, 0
        elif før_fra <= d <= før_til:
            tæl, i = før, 1
        else:
            continue
        i_alt[i] += 1
        for niveau, n in _nøgler(r).items():
            if n:
                tæl[niveau][n] += 1
                kreds.setdefault((niveau, n), r.get("politikreds", ""))
        if r.get("postnr") and r.get("by"):
            by_for_pnr.setdefault(r["postnr"], Counter())[r["by"]] += 1

    def rækker(niveau: str) -> list[dict]:
        ud = []
        for n in set(nu[niveau]) | set(før[niveau]):
            a, b = nu[niveau][n], før[niveau][n]
            række = {"navn": n, "antal": a, "foer": b, "forskel": a - b, "kreds": kreds[(niveau, n)]}
            if niveau == "postnumre" and n in by_for_pnr:
                række["byer"] = [x for x, _ in by_for_pnr[n].most_common(3)]
            ud.append(række)
        return ud

    resultat = {"fra": nu_fra, "til": nu_til, "foer_fra": før_fra, "foer_til": før_til,
                "antal": i_alt[0], "foer": i_alt[1]}
    for niveau in nu:
        alle = rækker(niveau)
        resultat[niveau] = {
            "flest": sorted((r for r in alle if r["antal"]), key=lambda r: (-r["antal"], -r["forskel"], r["navn"]))[:TOP],
            # Mindst 2 indbrud i ugen, så ét enkelt indbrud et nyt sted ikke tæller som en stigning
            "stigning": sorted((r for r in alle if r["forskel"] > 0 and r["antal"] >= 2),
                               key=lambda r: (-r["forskel"], -r["antal"], r["navn"]))[:TOP],
        }
    return resultat


def dst_stigninger(statistik: dict | None, top: int = TOP) -> dict | None:
    """Kommuner med størst stigning i seneste kvartal i forhold til samme kvartal året før."""
    if not statistik or not statistik.get("kvartaler"):
        return None
    sidste = statistik["kvartaler"][-1]
    år, k = sidste.split("K")
    fjor = f"{int(år) - 1}K{k}"
    rækker = []
    for x in statistik["kommuner"]:
        a, b = x["antal"].get(sidste), x["antal"].get(fjor)
        if a is None or b is None:
            continue
        r = {"navn": x["navn"], "antal": a, "foer": b, "forskel": a - b}
        if x.get("husstande"):
            r["pr_1000_husstande"] = round(a / x["husstande"] * 1000, 2)
        rækker.append(r)
    return {"kvartal": sidste, "fjor": fjor,
            "stigning": sorted((r for r in rækker if r["forskel"] > 0), key=lambda r: -r["forskel"])[:top]}


def byg(indbrud: list[dict], statistik: dict | None = None, slut: date | None = None) -> dict:
    """`slut` er som standard den seneste rapportdato i data (ikke i dag), så en uge
    uden døgnrapport i weekenden ikke ser ud som et fald."""
    if slut is None:
        slut = date.fromisoformat(max(r["rapportdato"] for r in indbrud)) if indbrud else date.today()
    kredse = sorted({r.get("politikreds", "") for r in indbrud if r["rapportdato"] >= _periode(slut, DAGE)[0]} - {""})
    return {
        "opdateret": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uge": sammenlign(indbrud, slut),
        "kredse": kredse,
        "dst": dst_stigninger(statistik),
    }


def _dk(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day}/{d.month}"


def _forskel(r: dict) -> str:
    return f"+{r['forskel']}" if r["forskel"] > 0 else str(r["forskel"])


def markdown(rapport: dict, side_url: str = "") -> str:
    u = rapport["uge"]
    linjer = [
        f"## Indbrud uge til {_dk(u['til'])}: {u['antal']} anmeldte indbrud "
        f"({_forskel({'forskel': u['antal'] - u['foer']})} i forhold til ugen før)",
        "",
        f"Døgnrapporter {_dk(u['fra'])}–{_dk(u['til'])} sammenlignet med {_dk(u['foer_fra'])}–{_dk(u['foer_til'])}. "
        f"Dækker: {', '.join(rapport['kredse']) or 'ingen kredse'}.",
        "",
    ]
    navne = {"bydele": ("Bydel/by", "bydele"), "postnumre": ("Postnummer", "postnumre"), "veje": ("Vej", "veje")}
    for niveau, (kolonne, ord_) in navne.items():
        stig = u[niveau]["stigning"]
        linjer += [f"### Her steg indbruddene mest – {ord_}", ""]
        if not stig:
            linjer += ["Ingen steder med mindst 2 indbrud og en stigning.", ""]
        else:
            linjer += [f"| {kolonne} | Denne uge | Ugen før | Ændring |", "|---|--:|--:|--:|"]
            for r in stig[:5]:
                navn = r["navn"] + (f" ({', '.join(r['byer'])})" if r.get("byer") else "")
                linjer.append(f"| {navn} | {r['antal']} | {r['foer']} | {_forskel(r)} |")
            linjer.append("")
    flest = u["postnumre"]["flest"][:5] or u["bydele"]["flest"][:5]
    if flest:
        linjer += ["### Flest indbrud i ugen", ""]
        linjer += [f"- {r['navn']}" + (f" ({', '.join(r['byer'])})" if r.get("byer") else "") + f": {r['antal']}"
                   for r in flest]
        linjer.append("")
    dst = rapport.get("dst")
    if dst and dst["stigning"]:
        linjer += [f"### Danmarks Statistik: størst stigning {dst['kvartal']} mod {dst['fjor']} (alle jyske kommuner)", ""]
        linjer += [f"- {r['navn']}: {r['antal']} indbrud ({_forskel(r)})" for r in dst["stigning"][:5]]
        linjer.append("")
    if side_url:
        linjer += [f"Se kortet og hotspot-listen: {side_url}", ""]
    linjer.append("_Døgnrapporterne nævner ikke alle indbrud (ca. 55–60 % af Danmarks Statistiks tal), "
                  "så brug tallene til at se, hvor det stiger, ikke som det præcise antal._")
    return "\n".join(linjer) + "\n"


def gem(indbrud: list[dict], fil: Path, statistik: dict | None = None) -> dict:
    data = byg(indbrud, statistik)
    fil.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return data
