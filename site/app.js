(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const UGEDAG = ["Søn", "Man", "Tir", "Ons", "Tor", "Fre", "Lør"];
  const MD = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  const dag = (iso) => { const d = new Date(iso + "T12:00:00"); return `${UGEDAG[d.getDay()]} ${d.getDate()}. ${MD[d.getMonth()]}`; };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  const state = { periode: 14, dato: "", omraade: "", kreds: "", valgt: null };
  const TYPE = { privat: "privat beboelse", erhverv: "erhverv", andet: "andet (fx garage)" };
  const navn = (r) => (r.vej ? `${r.vej}, ${r.by}` : r.by);
  let DATA = [], seneste = "";

  // ---------- kort ----------
  const map = L.map("map", { zoomControl: true, scrollWheelZoom: true }).setView([56.2, 10.1], 9);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  const lag = L.layerGroup().addTo(map);
  const markører = new Map();

  const legend = L.control({ position: "bottomleft" });
  legend.onAdd = () => {
    const d = L.DomUtil.create("div", "legend");
    d.innerHTML = '<span><i class="sw"></i>Privat beboelse</span><span><i class="sw b"></i>Erhverv og andet</span><span><i class="sw a o"></i>Ca. placering (by)</span><span><i class="sw s"></i>Kommune: alle indbrud i perioden</span>';
    return d;
  };
  legend.addTo(map);

  // Indbrud på samme vej får samme punkt; spred dem lidt, så alle kan klikkes.
  function spred(rækker) {
    const set = new Map();
    for (const r of rækker) {
      const k = `${r.lat},${r.lon}`;
      const n = set.get(k) || 0;
      set.set(k, n + 1);
      const a = n * 2.39996, d = n ? 0.00022 * Math.sqrt(n) : 0;
      r._ll = [r.lat + d * Math.sin(a), r.lon + (d * Math.cos(a)) / Math.cos((r.lat * Math.PI) / 180)];
    }
  }

  // ---------- filtre ----------
  function iPeriode(r) {
    if (state.dato) return r.rapportdato === state.dato;
    if (!state.periode) return true;
    const grænse = new Date(seneste + "T12:00:00");
    grænse.setDate(grænse.getDate() - state.periode + 1);
    return new Date(r.rapportdato + "T12:00:00") >= grænse;
  }
  const iKreds = (r) => !state.kreds || r.politikreds === state.kreds;
  const synlige = () => DATA.filter((r) => iPeriode(r) && iKreds(r) && (!state.omraade || r.omraade === state.omraade));

  function fyldVælgere() {
    const inden = DATA.filter((r) => iPeriode(r) && iKreds(r));
    const kredse = [...new Set(DATA.map((r) => r.politikreds))].sort((a, b) => a.localeCompare(b, "da"));
    $("kreds").innerHTML = '<option value="">Alle jyske kredse</option>' +
      kredse.map((k) => `<option value="${esc(k)}"${k === state.kreds ? " selected" : ""}>${esc(k)} (${DATA.filter((r) => r.politikreds === k && iPeriode(r)).length})</option>`).join("");
    const datoer = [...new Set(DATA.map((r) => r.rapportdato))].sort().reverse();
    $("dato").innerHTML = '<option value="">Alle i perioden</option>' +
      datoer.map((d) => `<option value="${d}"${d === state.dato ? " selected" : ""}>${dag(d)} (${DATA.filter((r) => r.rapportdato === d).length})</option>`).join("");
    const tæl = {};
    for (const r of inden) tæl[r.omraade] = (tæl[r.omraade] || 0) + 1;
    if (state.omraade && !tæl[state.omraade]) tæl[state.omraade] = 0;
    const områder = Object.keys(tæl).sort((a, b) => tæl[b] - tæl[a] || a.localeCompare(b, "da"));
    $("omraade").innerHTML = '<option value="">Hele området</option>' +
      områder.map((o) => `<option value="${esc(o)}"${o === state.omraade ? " selected" : ""}>${esc(o)} (${tæl[o]})</option>`).join("");
    document.querySelectorAll("#periode .chip").forEach((b) =>
      b.setAttribute("aria-pressed", String(!state.dato && +b.dataset.p === state.periode)));
  }

  // ---------- tegning ----------
  function popup(r) {
    const kilder = r.kilder.map((k) => `<a href="${esc(k.url)}" target="_blank" rel="noopener">${esc(k.udgiver)} ${esc(dag(k.rapportdato))}</a>`).join(" · ");
    const tekst = r.beskrivelse ? (r.beskrivelse.length > 240 ? r.beskrivelse.slice(0, 237) + "…" : r.beskrivelse) : "";
    return `<div class="pop"><strong>${esc(r.vej || r.by)}</strong>${r.vej ? esc(r.by) + " · " : ""}${esc(TYPE[r.type] || r.type)}` +
      (tekst ? `<div class="t" style="font-family:inherit;margin:4px 0">${esc(tekst)}</div>` : "") +
      `<div class="t">Gerningstid: ${esc(r.gerningstid)}</div>` +
      `<div class="t">Døgnrapport ${esc(dag(r.rapportdato))}</div>` +
      (r.praecision === "by" ? `<div class="t">${r.vej ? "Vejen blev ikke fundet – punktet" : "Kun by/område oplyst – punktet"} sidder ved byens midte.</div>` : "") +
      `<div class="t">${esc(r.politikreds)}</div>` +
      `<div class="t">Kilde: ${kilder}</div></div>`;
  }

  function tegn(tilpas) {
    const v = synlige();
    lag.clearLayers();
    markører.clear();
    for (const r of v) {
      if (!r._ll) continue;
      const m = L.circleMarker(r._ll, stil(r)).bindPopup(popup(r), { maxWidth: 280 });
      m.bindTooltip(navn(r), { direction: "top", offset: [0, -6] });
      m.on("click", () => vælg(r.id, "kort"));
      m.addTo(lag);
      markører.set(r.id, m);
    }
    if (tilpas && v.some((r) => r._ll)) {
      map.fitBounds(L.latLngBounds(v.filter((r) => r._ll).map((r) => r._ll)), { padding: [30, 30], maxZoom: 14 });
    }
    liste();
    stats(v);
  }

  function liste() {
    const v = synlige();
    $("cnt").textContent = `(${v.length})`;
    let h = "";
    const datoer = [...new Set(v.map((r) => r.rapportdato))].sort().reverse();
    for (const d of datoer) {
      const ds = v.filter((r) => r.rapportdato === d);
      h += `<div class="day">Døgnrapport ${esc(dag(d))} · ${ds.length}</div>`;
      for (const r of ds) {
        h += `<button class="item${state.valgt === r.id ? " sel" : ""}" data-id="${esc(r.id)}" id="it-${esc(r.id)}">` +
          `<i class="sw${r.type !== "privat" ? " b" : ""}${r.praecision === "by" ? " a" : ""}"></i>` +
          `<span class="st">${esc(navn(r))}</span><span class="t">${esc(r.gerningstid)}</span></button>`;
      }
    }
    $("list").innerHTML = h || '<p class="empty">Ingen indbrud med de valgte filtre.</p>';
  }

  function stats(v) {
    const byer = new Set(v.map((r) => r.by)).size;
    const kredse = new Set(v.map((r) => r.politikreds)).size;
    $("stats").innerHTML = `<span><b>${v.length}</b>anmeldte indbrud</span><span><b>${byer}</b>byer og bydele</span><span><b>${kredse}</b>politikredse</span>`;
  }

  function stil(r) {
    const valgt = state.valgt === r.id, ca = r.praecision === "by";
    return {
      radius: valgt ? 10 : 7,
      color: ca ? css("--approx") : css("--panel") || "#fff",
      weight: ca ? 2.5 : 1.5,
      dashArray: ca ? "3 3" : null,
      fillColor: valgt ? css("--sel") : r.type === "privat" ? css("--hit") : css("--biz"),
      fillOpacity: 0.9,
    };
  }

  function vælg(id, fra) {
    const før = state.valgt;
    state.valgt = id;
    for (const x of [før, id]) {
      const r = DATA.find((d) => d.id === x), m = markører.get(x);
      if (r && m) m.setStyle(stil(r)).setRadius(stil(r).radius);
    }
    liste();
    const m = markører.get(id);
    if (!m) return;
    if (fra === "liste") {
      map.setView(m.getLatLng(), Math.max(map.getZoom(), 14));
      m.openPopup();
    } else {
      const el = $("it-" + id);
      if (el) el.scrollIntoView({ block: "nearest" });
    }
  }

  // ---------- hændelser ----------
  $("periode").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    state.periode = +b.dataset.p; state.dato = ""; state.valgt = null;
    fyldVælgere(); tegn(true);
  });
  $("dato").addEventListener("change", (e) => { state.dato = e.target.value; state.valgt = null; fyldVælgere(); tegn(true); });
  $("omraade").addEventListener("change", (e) => { state.omraade = e.target.value; state.valgt = null; fyldVælgere(); tegn(true); });
  $("kreds").addEventListener("change", (e) => { state.kreds = e.target.value; state.omraade = ""; state.valgt = null; fyldVælgere(); tegn(true); });
  $("nulstil").addEventListener("click", () => { Object.assign(state, { periode: 14, dato: "", omraade: "", kreds: "", valgt: null }); fyldVælgere(); tegn(true); });
  $("list").addEventListener("click", (e) => { const b = e.target.closest(".item"); if (b) vælg(b.dataset.id, "liste"); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => { tegn(false); tegnStatistik(); tegnGraf(); });

  // ---------- statistik pr. kommune (Danmarks Statistik) ----------
  map.createPane("statistik");
  map.getPane("statistik").style.zIndex = 350; // under de enkelte indbrud
  map.createPane("statistikTal");
  map.getPane("statistikTal").style.zIndex = 450;
  map.getPane("statistikTal").style.pointerEvents = "none";
  const statLag = L.layerGroup();
  const statMarkører = new Map();
  let STAT = null;
  const kvt = (k) => `${k.slice(5)}. kvt. ${k.slice(0, 4)}`;
  let PERIODER = [];
  const sum = (x, kvartaler) => kvartaler.reduce((a, q) => a + (x.antal[q] || 0), 0);

  // Hele kalenderår (det seneste også selvom det ikke er slut) og enkelte kvartaler.
  // "fjor" er de samme kvartaler året før, så et halvt år sammenlignes med et halvt år.
  function byggPerioder(kv) {
    const findes = new Set(kv), ud = [];
    const år = [...new Set(kv.map((q) => q.slice(0, 4)))].sort().reverse();
    år.forEach((å, i) => {
      const qs = kv.filter((q) => q.startsWith(å));
      if (qs.length < 4 && i > 0) return; // ufuldstændigt ældste år
      const fjor = qs.map((q) => String(+å - 1) + q.slice(4));
      const nr = qs.map((q) => q.slice(5));
      ud.push({
        id: "Y" + å, år: true, kvartaler: qs,
        navn: qs.length === 4 ? `Hele ${å}` : `${å} (${nr[0]}.–${nr[nr.length - 1]}. kvt.)`,
        fjor: fjor.every((q) => findes.has(q)) ? fjor : null,
        fjorNavn: qs.length === 4 ? `Hele ${+å - 1}` : `Samme kvartaler i ${+å - 1}`,
      });
    });
    for (const q of [...kv].reverse()) {
      const f = String(+q.slice(0, 4) - 1) + q.slice(4);
      ud.push({ id: q, år: false, kvartaler: [q], navn: kvt(q), fjor: findes.has(f) ? [f] : null, fjorNavn: "Samme kvartal året før" });
    }
    return ud;
  }
  const tal = (n, d = 0) => n.toLocaleString("da-DK", { minimumFractionDigits: d, maximumFractionDigits: d });

  // Hvad cirklerne og listen måler. "værdi" er det tal, der vises og sorteres efter.
  const MÅL = {
    antal: { navn: "antal indbrud", enhed: "", dec: 0, værdi: (r) => r.n },
    indbyggere: { navn: "pr. 1.000 indbyggere", enhed: " pr. 1.000 indb.", dec: 2, værdi: (r) => r.prInd },
    husstande: { navn: "pr. 1.000 husstande", enhed: " pr. 1.000 husst.", dec: 2, værdi: (r) => r.prHus },
  };

  function tegnStatistik() {
    statLag.clearLayers();
    statMarkører.clear();
    if (!STAT || !$("visStat").checked) {
      statLag.remove();
      $("klist").innerHTML = '<p class="empty">Slå laget "Alle indbrud pr. kommune" til for at se kommunerne.</p>';
      return;
    }
    const per = PERIODER.find((p) => p.id === $("kvartal").value) || PERIODER[0];
    const k = per.navn;
    const mål = MÅL[$("maal").value] || MÅL.antal;
    const rækker = STAT.kommuner.filter((x) => x.lat != null).map((x) => {
      const n = sum(x, per.kvartaler);
      return {
        ...x, n,
        prInd: x.indbyggere ? (n / x.indbyggere) * 1000 : 0,
        prHus: x.husstande ? (n / x.husstande) * 1000 : 0,
        fjor: per.fjor ? sum(x, per.fjor) : null,
      };
    });
    const maks = Math.max(1e-9, ...rækker.map(mål.værdi));
    const vis = (r) => tal(mål.værdi(r), mål.dec);
    for (const r of rækker) {
      const andel = mål.værdi(r) / maks;
      const m = L.circleMarker([r.lat, r.lon], {
        pane: "statistik",
        radius: 4 + 26 * Math.sqrt(andel),
        color: css("--stat"), weight: 2,
        fillColor: css("--stat"), fillOpacity: 0.2 + 0.6 * andel,
      });
      const fjor = r.fjor == null ? "" : `<div class="t">${esc(per.fjorNavn)}: ${tal(r.fjor)}</div>`;
      m.bindPopup(`<div class="pop"><strong>${esc(r.navn)} Kommune</strong>${tal(r.n)} anmeldte indbrud i beboelse, ${esc(k)}` +
        `<div class="t">${tal(r.prInd, 2)} pr. 1.000 indbyggere (${tal(r.indbyggere || 0)} indb.)</div>` +
        `<div class="t">${tal(r.prHus, 2)} pr. 1.000 husstande (${tal(r.husstande || 0)} husst.)</div>${fjor}` +
        `<div class="t">Kilde: <a href="${esc(STAT.kilde_url)}" target="_blank" rel="noopener">Danmarks Statistik</a></div></div>`, { maxWidth: 280 });
      m.bindTooltip(`${r.navn}: ${vis(r)}${mål.enhed}`, { direction: "top" });
      m.addTo(statLag);
      m.on("click", () => tilføjGraf(r.kode));
      statMarkører.set(r.kode, m);
      if (andel >= 0.04 || mål !== MÅL.antal) {
        L.marker([r.lat, r.lon], {
          pane: "statistikTal", interactive: false, keyboard: false,
          icon: L.divIcon({ className: "stat-tal", html: vis(r), iconSize: [44, 16], iconAnchor: [22, 8] }),
        }).addTo(statLag);
      }
    }
    const sorteret = [...rækker].sort((a, b) => mål.værdi(b) - mål.værdi(a) || a.navn.localeCompare(b.navn, "da"));
    $("klist").innerHTML = `<div class="day">${esc(k)} · sorteret efter ${esc(mål.navn)}</div>` + sorteret.map((r) => {
      const ændring = r.fjor ? ` · året før ${tal(r.fjor)} (${r.n >= r.fjor ? "+" : "−"}${tal(Math.abs(Math.round(((r.n - r.fjor) / r.fjor) * 100)))} %)` : "";
      return `<button class="item" data-kode="${esc(r.kode)}"><i class="sw s"></i><span class="st">${esc(r.navn)} <b class="kn">${vis(r)}</b><small class="enh">${esc(mål.enhed)}</small></span>` +
        `<span class="t">${tal(r.n)} indbrud · ${tal(r.prInd, 2)} pr. 1.000 indb. · ${tal(r.prHus, 2)} pr. 1.000 husst.${ændring}</span></button>`;
    }).join("");
    statLag.addTo(map);
    const total = rækker.reduce((a, r) => a + r.n, 0);
    const ind = rækker.reduce((a, r) => a + (r.indbyggere || 0), 0), hus = rækker.reduce((a, r) => a + (r.husstande || 0), 0);
    $("statInfo").textContent = `${tal(total)} anmeldte indbrud i beboelse i Jylland, ${esc(k)} – ` +
      `${tal((total / ind) * 1000, 2)} pr. 1.000 indbyggere, ${tal((total / hus) * 1000, 2)} pr. 1.000 husstande.`;
  }



  // ---------- graf: udvikling pr. kvartal for valgte kommuner ----------
  const SLOTS = ["--s1", "--s2", "--s3"]; // faste farver; en kommune beholder sin farve, mens den er valgt
  let grafValg = []; // [{kode, slot}]

  function grafVærdi(x, q, mål) {
    const n = x.antal[q] || 0;
    if (mål === "indbyggere") return x.indbyggere ? (n / x.indbyggere) * 1000 : null;
    if (mål === "husstande") return x.husstande ? (n / x.husstande) * 1000 : null;
    return n;
  }

  function tilføjGraf(kode) {
    if (!STAT || grafValg.some((g) => g.kode === kode)) return;
    if (grafValg.length >= SLOTS.length) grafValg.shift();
    const brugt = new Set(grafValg.map((g) => g.slot));
    grafValg.push({ kode, slot: SLOTS.find((s) => !brugt.has(s)) });
    tegnGraf();
  }

  function pænTrin(maks) {
    const rå = maks / 4, p = 10 ** Math.floor(Math.log10(rå || 1));
    const t = [1, 2, 2.5, 5, 10].map((m) => m * p).find((x) => x >= rå) || p * 10;
    return t;
  }

  function tegnGraf() {
    if (!STAT) return;
    const mål = $("maal").value, M = MÅL[mål] || MÅL.antal;
    const kv = STAT.kvartaler;
    const kom = new Map(STAT.kommuner.map((x) => [x.kode, x]));
    const serier = grafValg.filter((g) => kom.has(g.kode)).map((g) => ({
      navn: kom.get(g.kode).navn, farve: css(g.slot), kode: g.kode, slot: g.slot,
      v: kv.map((q) => grafVærdi(kom.get(g.kode), q, mål)),
    }));
    if (mål !== "antal") {
      const alle = STAT.kommuner;
      const nævner = (x) => (mål === "indbyggere" ? x.indbyggere : x.husstande) || 0;
      const total = alle.reduce((a, x) => a + nævner(x), 0);
      serier.push({ navn: "Jylland i alt", farve: css("--ref"), ref: true,
        v: kv.map((q) => (alle.reduce((a, x) => a + (x.antal[q] || 0), 0) / total) * 1000) });
    }
    $("grafTitel").textContent = `Anmeldte indbrud i beboelse pr. kvartal – ${M.navn}`;
    $("grafValg").innerHTML = grafValg.map((g) => {
      const x = kom.get(g.kode);
      return `<span class="gchip"><i style="background:var(${g.slot})"></i>${esc(x ? x.navn : g.kode)}` +
        `<button type="button" data-fjern="${esc(g.kode)}" aria-label="Fjern ${esc(x ? x.navn : g.kode)}">×</button></span>`;
    }).join("") + (grafValg.length < SLOTS.length ? "" : '<span class="ghint">Maks. 3 – en ny erstatter den ældste</span>');
    $("grafTilføj").innerHTML = '<option value="">+ Tilføj kommune…</option>' +
      [...STAT.kommuner].sort((a, b) => a.navn.localeCompare(b.navn, "da"))
        .filter((x) => !grafValg.some((g) => g.kode === x.kode))
        .map((x) => `<option value="${esc(x.kode)}">${esc(x.navn)}</option>`).join("");

    const svg = $("graf"), W = Math.max(320, svg.clientWidth || 600), H = 280;
    const smal = W < 560;
    const m = { l: 40, r: smal ? 96 : 124, t: 14, b: smal ? 26 : 40 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    if (!serier.length) { svg.innerHTML = ""; $("grafTabel").innerHTML = ""; $("grafTom").hidden = false; return; }
    $("grafTom").hidden = true;
    const maks = Math.max(1e-9, ...serier.flatMap((s) => s.v.filter((x) => x != null)));
    const trin = pænTrin(maks), top = Math.ceil(maks / trin) * trin;
    const X = (i) => m.l + (kv.length === 1 ? iw / 2 : (i * iw) / (kv.length - 1));
    const Y = (v) => m.t + ih - (v / top) * ih;
    let h = "";
    for (let t = 0; t <= top + 1e-9; t += trin) {
      h += `<line class="gl" x1="${m.l}" x2="${m.l + iw}" y1="${Y(t)}" y2="${Y(t)}"/>` +
        `<text class="ax" x="${m.l - 8}" y="${Y(t) + 4}" text-anchor="end">${tal(t, M.dec && trin < 1 ? 1 : 0)}</text>`;
    }
    kv.forEach((q, i) => {
      if (!smal) h += `<text class="ax" x="${X(i)}" y="${m.t + ih + 16}" text-anchor="middle">${q.slice(5)}. kv</text>`;
      // årstal ved 1. kvartal; et ufuldstændigt første år kun hvis der er plads før næste årstal
      const førsteK1 = kv.findIndex((x) => x.endsWith("K1"));
      const vis = q.endsWith("K1") || (i === 0 && (førsteK1 < 0 || førsteK1 >= 3));
      if (vis) h += `<text class="ax år" x="${X(i)}" y="${m.t + ih + (smal ? 16 : 32)}" text-anchor="middle">${q.slice(0, 4)}</text>`;
    });
    // linjer: reference først, så de valgte kommuner ligger øverst
    for (const s of [...serier].sort((a, b) => (b.ref ? 1 : 0) - (a.ref ? 1 : 0))) {
      const pts = s.v.map((v, i) => (v == null ? null : [X(i), Y(v)])).filter(Boolean);
      h += `<polyline class="ln${s.ref ? " ref" : ""}" style="stroke:${s.farve}" points="${pts.map((p) => p.join(",")).join(" ")}"/>`;
      if (!s.ref) h += pts.map((p) => `<circle class="pt" cx="${p[0]}" cy="${p[1]}" r="4" style="fill:${s.farve}"/>`).join("");
    }
    // direkte etiketter ved linjernes ende, skubbet fra hinanden hvis de overlapper
    const ender = serier.map((s) => ({ s, y: Y(s.v[s.v.length - 1] ?? 0) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ender.length; i++) if (ender[i].y - ender[i - 1].y < 15) ender[i].y = ender[i - 1].y + 15;
    for (const e of ender) {
      const yEnd = Y(e.s.v[e.s.v.length - 1] ?? 0), x0 = X(kv.length - 1);
      h += `<line class="lead" x1="${x0 + 6}" x2="${x0 + 14}" y1="${yEnd}" y2="${e.y}" style="stroke:${e.s.farve}"/>` +
        `<text class="glbl" x="${x0 + 18}" y="${e.y + 4}">${esc(e.s.navn)} <tspan class="lv">${tal(e.s.v[e.s.v.length - 1] ?? 0, M.dec)}</tspan></text>`;
    }
    h += `<line id="kryds" class="kryds" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/>` +
      `<rect id="grafHit" x="${m.l - 10}" y="${m.t}" width="${iw + 20}" height="${ih}" fill="transparent"/>`;
    svg.innerHTML = h;

    const tip = $("grafTip");
    const vis = (ev) => {
      const r = svg.getBoundingClientRect(), sx = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(kv.length - 1, Math.round(((sx - m.l) / iw) * (kv.length - 1))));
      const k = svg.querySelector("#kryds");
      k.setAttribute("x1", X(i)); k.setAttribute("x2", X(i)); k.setAttribute("visibility", "visible");
      const rækker = serier.map((s) => ({ s, v: s.v[i] })).filter((x) => x.v != null).sort((a, b) => b.v - a.v);
      tip.innerHTML = `<b>${esc(kvt(kv[i]))}</b>` + rækker.map((x) =>
        `<div><i style="background:${x.s.farve}"></i>${esc(x.s.navn)}<span>${tal(x.v, M.dec)}</span></div>`).join("");
      tip.hidden = false;
      const px = (X(i) / W) * r.width;
      tip.style.left = Math.min(r.width - tip.offsetWidth - 4, Math.max(4, px + 12)) + "px";
    };
    const skjul = () => { tip.hidden = true; svg.querySelector("#kryds")?.setAttribute("visibility", "hidden"); };
    const hit = svg.querySelector("#grafHit");
    hit.addEventListener("pointermove", vis); hit.addEventListener("pointerdown", vis); hit.addEventListener("pointerleave", skjul);

    // tabelvisning (samme tal som grafen)
    $("grafTabel").innerHTML = `<table><thead><tr><th>Kvartal</th>${serier.map((s) => `<th>${esc(s.navn)}</th>`).join("")}</tr></thead><tbody>` +
      kv.map((q, i) => `<tr><td>${esc(kvt(q))}</td>${serier.map((s) => `<td>${s.v[i] == null ? "–" : tal(s.v[i], M.dec)}</td>`).join("")}</tr>`).reverse().join("") +
      "</tbody></table>";
  }

  $("grafValg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-fjern]"); if (!b) return;
    grafValg = grafValg.filter((g) => g.kode !== b.dataset.fjern); tegnGraf();
  });
  $("grafTilføj").addEventListener("change", (e) => { if (e.target.value) tilføjGraf(e.target.value); });
  let grafTimer;
  addEventListener("resize", () => { clearTimeout(grafTimer); grafTimer = setTimeout(tegnGraf, 150); });

  hentData("statistik.json").then((d) => {
    STAT = d;
    PERIODER = byggPerioder(d.kvartaler);
    const opt = (p) => `<option value="${p.id}">${esc(p.navn)}</option>`;
    $("kvartal").innerHTML =
      `<optgroup label="Hele år">${PERIODER.filter((p) => p.år).map(opt).join("")}</optgroup>` +
      `<optgroup label="Kvartaler">${PERIODER.filter((p) => !p.år).map(opt).join("")}</optgroup>`;
    $("statGrp").hidden = false;
    tegnStatistik();
    // Start grafen med de tre kommuner med flest indbrud i det seneste kvartal
    const sidste = d.kvartaler[d.kvartaler.length - 1];
    [...d.kommuner].sort((a, b) => (b.antal[sidste] || 0) - (a.antal[sidste] || 0)).slice(0, 3).forEach((x) => tilføjGraf(x.kode));
    $("grafBoks").hidden = false;
    tegnGraf();
  }).catch(() => { /* statistikken er valgfri */ });
  $("visStat").addEventListener("change", tegnStatistik);
  $("klist").addEventListener("click", (e) => {
    const b = e.target.closest(".item"); if (!b) return;
    tilføjGraf(b.dataset.kode);
    const m = statMarkører.get(b.dataset.kode); if (!m) return;
    map.setView(m.getLatLng(), Math.max(map.getZoom(), 10));
    m.openPopup();
  });
  document.querySelectorAll(".fane").forEach((f) => f.addEventListener("click", () => {
    document.querySelectorAll(".fane").forEach((x) => x.setAttribute("aria-selected", String(x === f)));
    $("list").hidden = f.dataset.fane !== "indbrud";
    $("klist").hidden = f.dataset.fane !== "kommuner";
  }));
  $("kvartal").addEventListener("change", tegnStatistik);
  $("maal").addEventListener("change", () => { tegnStatistik(); tegnGraf(); });
  $("visEnkelte").addEventListener("change", (e) => { if (e.target.checked) lag.addTo(map); else lag.remove(); });

  // ---------- data ----------
  async function hentData(navn = "indbrud.json") {
    for (const url of [navn, "../data/" + navn]) {
      try { const r = await fetch(url, { cache: "no-store" }); if (r.ok) return r.json(); } catch (e) { /* prøv næste */ }
    }
    throw new Error("data mangler");
  }

  hentData().then((d) => {
    DATA = d.indbrud.filter((r) => r.lat != null);
    seneste = DATA.reduce((m, r) => (r.rapportdato > m ? r.rapportdato : m), "");
    spred(DATA);
    const datoer = DATA.map((r) => r.rapportdato).sort();
    if (datoer.length) $("eyebrow").textContent = `Jyske politikredse · døgnrapporter ${dag(datoer[0])} – ${dag(datoer[datoer.length - 1])}`;
    $("opdateret").innerHTML = `<b>Opdateret.</b> ${esc(new Date(d.opdateret).toLocaleString("da-DK", { dateStyle: "long", timeStyle: "short" }))}.`;
    fyldVælgere();
    tegn(false);
    map.fitBounds([[54.8, 8.05], [57.75, 10.95]]); // hele Jylland ved første visning
  }).catch(() => {
    $("list").innerHTML = '<p class="empty">Kunne ikke hente data/indbrud.json.</p>';
  });
})();
