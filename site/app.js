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
    d.innerHTML = '<span><i class="sw"></i>Privat beboelse</span><span><i class="sw b"></i>Erhverv og andet</span><span><i class="sw a o"></i>Ca. placering (by)</span><span><i class="sw s"></i>Kommune: alle indbrud i kvartalet</span>';
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
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => { tegn(false); tegnStatistik(); });

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
  const tal = (n, d = 0) => n.toLocaleString("da-DK", { minimumFractionDigits: d, maximumFractionDigits: d });

  function tegnStatistik() {
    statLag.clearLayers();
    statMarkører.clear();
    if (!STAT || !$("visStat").checked) {
      statLag.remove();
      $("klist").innerHTML = '<p class="empty">Slå laget "Alle indbrud pr. kommune" til for at se kommunerne.</p>';
      return;
    }
    const k = $("kvartal").value;
    const kv = STAT.kvartaler, iFjor = kv[kv.indexOf(k) - 4];
    const rækker = STAT.kommuner.filter((x) => x.lat != null).map((x) => {
      const n = x.antal[k] || 0;
      return { ...x, n, rate: x.indbyggere ? (n / x.indbyggere) * 1000 : 0, fjor: iFjor ? x.antal[iFjor] || 0 : null };
    });
    const maksN = Math.max(1, ...rækker.map((r) => r.n));
    const maksRate = Math.max(0.01, ...rækker.map((r) => r.rate));
    for (const r of rækker) {
      const m = L.circleMarker([r.lat, r.lon], {
        pane: "statistik",
        radius: 4 + 26 * Math.sqrt(r.n / maksN),
        color: css("--stat"), weight: 2,
        fillColor: css("--stat"), fillOpacity: 0.2 + 0.6 * (r.rate / maksRate),
      });
      const fjor = r.fjor == null ? "" : `<div class="t">Samme kvartal året før: ${tal(r.fjor)}</div>`;
      m.bindPopup(`<div class="pop"><strong>${esc(r.navn)} Kommune</strong>${tal(r.n)} anmeldte indbrud i beboelse, ${kvt(k)}` +
        `<div class="t">${tal(r.rate, 2)} pr. 1.000 indbyggere</div>${fjor}` +
        `<div class="t">Kilde: <a href="${esc(STAT.kilde_url)}" target="_blank" rel="noopener">Danmarks Statistik, STRAF11</a></div></div>`, { maxWidth: 260 });
      m.bindTooltip(`${r.navn}: ${tal(r.n)}`, { direction: "top" });
      m.addTo(statLag);
      statMarkører.set(r.kode, m);
      if (r.n >= maksN * 0.04) {
        L.marker([r.lat, r.lon], {
          pane: "statistikTal", interactive: false, keyboard: false,
          icon: L.divIcon({ className: "stat-tal", html: tal(r.n), iconSize: [40, 16], iconAnchor: [20, 8] }),
        }).addTo(statLag);
      }
    }
    const sorteret = [...rækker].sort((a, b) => b.n - a.n || a.navn.localeCompare(b.navn, "da"));
    $("klist").innerHTML = `<div class="day">${esc(kvt(k))} · alle anmeldte indbrud i beboelse</div>` + sorteret.map((r) => {
      const ændring = r.fjor ? ` · året før ${tal(r.fjor)} (${r.n >= r.fjor ? "+" : "−"}${tal(Math.abs(Math.round(((r.n - r.fjor) / r.fjor) * 100)))} %)` : "";
      return `<button class="item" data-kode="${esc(r.kode)}"><i class="sw s"></i><span class="st">${esc(r.navn)} <b class="kn">${tal(r.n)}</b></span>` +
        `<span class="t">${tal(r.rate, 2)} pr. 1.000 indb.${ændring}</span></button>`;
    }).join("");
    statLag.addTo(map);
    const total = rækker.reduce((a, r) => a + r.n, 0);
    $("statInfo").textContent = `${tal(total)} anmeldte indbrud i beboelse i Jylland i ${kvt(k)} (alle politikredse).`;
  }

  hentData("statistik.json").then((d) => {
    STAT = d;
    $("kvartal").innerHTML = [...d.kvartaler].reverse().map((k) => `<option value="${k}">${kvt(k)}</option>`).join("");
    $("statGrp").hidden = false;
    tegnStatistik();
  }).catch(() => { /* statistikken er valgfri */ });
  $("visStat").addEventListener("change", tegnStatistik);
  $("klist").addEventListener("click", (e) => {
    const b = e.target.closest(".item"); if (!b) return;
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
