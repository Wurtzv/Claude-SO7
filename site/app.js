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
  // Canvas tegner tusindvis af punkter langt hurtigere end SVG (historikken går flere år tilbage)
  const map = L.map("map", { zoomControl: true, scrollWheelZoom: true, preferCanvas: true }).setView([56.2, 10.1], 9);
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
    return `<div class="pop"><strong>${esc(r.vej || r.by)}</strong>${r.postnr ? esc(r.postnr) + " " : ""}${r.vej ? esc(r.by) + " · " : ""}${esc(TYPE[r.type] || r.type)}` +
      (tekst ? `<div class="t" style="font-family:inherit;margin:4px 0">${esc(tekst)}</div>` : "") +
      `<div class="t">Gerningstid: ${esc(r.gerningstid)}</div>` +
      `<div class="t">Døgnrapport ${esc(dag(r.rapportdato))}</div>` +
      (r.praecision === "by" ? `<div class="t">${r.vej ? "Vejen blev ikke fundet – punktet" : "Kun by/område oplyst – punktet"} sidder ved byens midte.</div>` : "") +
      naboHtml(r) +
      `<div class="t">${esc(r.politikreds)}</div>` +
      `<div class="t">Kilde: ${kilder}</div></div>`;
  }

  function tegn(tilpas) {
    const v = synlige();
    lag.clearLayers();
    markører.clear();
    for (const r of v) {
      if (!r._ll) continue;
      const m = L.circleMarker(r._ll, stil(r)).bindPopup(() => popup(r), { maxWidth: 280 });
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
    let h = "", vist = 0;
    const MAKS = 400; // listen viser de nyeste; kortet viser alle
    const pr = new Map();
    for (const r of v) { if (!pr.has(r.rapportdato)) pr.set(r.rapportdato, []); pr.get(r.rapportdato).push(r); }
    const datoer = [...pr.keys()].sort().reverse();
    for (const d of datoer) {
      if (vist >= MAKS) { h += `<p class="empty">… og ${tal(v.length - vist)} ældre indbrud. Vælg en kortere periode eller et område for at se dem i listen.</p>`; break; }
      const ds = pr.get(d);
      vist += ds.length;
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
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => { tegn(false); tegnStatistik(); tegnGraf(); tegnEgen(); });

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

  // Generisk linjegraf: perioder = [{kort, år, lang}], serier = [{navn, farve, v[], ref?}]
  function linjegraf(o) {
    const { svg, tip, tabel, tom, perioder, serier, dec = 0, kolonne = "Periode" } = o;
    const W = Math.max(320, svg.clientWidth || 600), H = 280, n = perioder.length;
    const smal = W < 560;
    const m = { l: 40, r: smal ? 96 : 124, t: 14, b: smal ? 26 : 40 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    if (!serier.length || !n) { svg.innerHTML = ""; tabel.innerHTML = ""; tom.hidden = false; return; }
    tom.hidden = true;
    const maks = Math.max(1e-9, ...serier.flatMap((s) => s.v.filter((x) => x != null)));
    const trin = pænTrin(maks), top = Math.ceil(maks / trin) * trin;
    const X = (i) => m.l + (n === 1 ? iw / 2 : (i * iw) / (n - 1));
    const Y = (v) => m.t + ih - (v / top) * ih;
    const afstand = n > 1 ? iw / (n - 1) : iw;
    let h = "";
    for (let t = 0; t <= top + 1e-9; t += trin) {
      h += `<line class="gl" x1="${m.l}" x2="${m.l + iw}" y1="${Y(t)}" y2="${Y(t)}"/>` +
        `<text class="ax" x="${m.l - 8}" y="${Y(t) + 4}" text-anchor="end">${tal(t, dec && trin < 1 ? 1 : 0)}</text>`;
    }
    const førsteÅr = perioder.findIndex((p) => p.år);
    perioder.forEach((p, i) => {
      if (!smal && afstand >= 30 && p.kort) h += `<text class="ax" x="${X(i)}" y="${m.t + ih + 16}" text-anchor="middle">${esc(p.kort)}</text>`;
      const år = p.år || (i === 0 && (førsteÅr < 0 || førsteÅr * afstand >= 36) ? p.årAltid : null);
      if (år) h += `<text class="ax år" x="${X(i)}" y="${m.t + ih + (smal || afstand < 30 ? 16 : 32)}" text-anchor="middle">${esc(år)}</text>`;
    });
    const prikker = afstand >= 14;
    for (const s of [...serier].sort((a, b) => (b.ref ? 1 : 0) - (a.ref ? 1 : 0))) {
      const pts = s.v.map((v, i) => (v == null ? null : [X(i), Y(v)])).filter(Boolean);
      h += `<polyline class="ln${s.ref ? " ref" : ""}" style="stroke:${s.farve}" points="${pts.map((q) => q.join(",")).join(" ")}"/>`;
      if (!s.ref && prikker) h += pts.map((q) => `<circle class="pt" cx="${q[0]}" cy="${q[1]}" r="4" style="fill:${s.farve}"/>`).join("");
    }
    const sidst = (s) => s.v[s.v.length - 1] ?? 0;
    const ender = serier.map((s) => ({ s, y: Y(sidst(s)) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ender.length; i++) if (ender[i].y - ender[i - 1].y < 15) ender[i].y = ender[i - 1].y + 15;
    for (const e of ender) {
      const x0 = X(n - 1);
      h += `<line class="lead" x1="${x0 + 6}" x2="${x0 + 14}" y1="${Y(sidst(e.s))}" y2="${e.y}" style="stroke:${e.s.farve}"/>` +
        `<text class="glbl" x="${x0 + 18}" y="${e.y + 4}">${esc(e.s.navn)} <tspan class="lv">${tal(sidst(e.s), dec)}</tspan></text>`;
    }
    h += `<line class="kryds" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/>` +
      `<rect class="hit" x="${m.l - 10}" y="${m.t}" width="${iw + 20}" height="${ih}" fill="transparent"/>`;
    svg.innerHTML = h;
    const kryds = svg.querySelector(".kryds");
    const vis = (ev) => {
      const r = svg.getBoundingClientRect(), sx = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(n - 1, Math.round(((sx - m.l) / iw) * (n - 1))));
      kryds.setAttribute("x1", X(i)); kryds.setAttribute("x2", X(i)); kryds.setAttribute("visibility", "visible");
      const rækker = serier.map((s) => ({ s, v: s.v[i] })).filter((x) => x.v != null).sort((a, b) => b.v - a.v);
      tip.innerHTML = `<b>${esc(perioder[i].lang)}</b>` + rækker.map((x) =>
        `<div><i style="background:${x.s.farve}"></i>${esc(x.s.navn)}<span>${tal(x.v, dec)}</span></div>`).join("");
      tip.hidden = false;
      tip.style.left = Math.min(r.width - tip.offsetWidth - 4, Math.max(4, (X(i) / W) * r.width + 12)) + "px";
    };
    const hit = svg.querySelector(".hit");
    hit.addEventListener("pointermove", vis); hit.addEventListener("pointerdown", vis);
    hit.addEventListener("pointerleave", () => { tip.hidden = true; kryds.setAttribute("visibility", "hidden"); });
    tabel.innerHTML = `<table><thead><tr><th>${esc(kolonne)}</th>${serier.map((s) => `<th>${esc(s.navn)}</th>`).join("")}</tr></thead><tbody>` +
      perioder.map((p, i) => `<tr><td>${esc(p.lang)}</td>${serier.map((s) => `<td>${s.v[i] == null ? "–" : tal(s.v[i], dec)}</td>`).join("")}</tr>`).reverse().join("") +
      "</tbody></table>";
  }

  function chips(valg, navn, boks, maks) {
    boks.innerHTML = valg.map((g) => `<span class="gchip"><i style="background:var(${g.slot})"></i>${esc(navn(g))}` +
      `<button type="button" data-fjern="${esc(g.kode)}" aria-label="Fjern ${esc(navn(g))}">×</button></span>`).join("") +
      (valg.length < maks ? "" : '<span class="ghint">Maks. 3 – en ny erstatter den ældste</span>');
  }

  function tegnGraf() {
    if (!STAT) return;
    const mål = $("maal").value, M = MÅL[mål] || MÅL.antal;
    const kv = STAT.kvartaler;
    const kom = new Map(STAT.kommuner.map((x) => [x.kode, x]));
    const serier = grafValg.filter((g) => kom.has(g.kode)).map((g) => ({
      navn: kom.get(g.kode).navn, farve: css(g.slot), v: kv.map((q) => grafVærdi(kom.get(g.kode), q, mål)),
    }));
    if (mål !== "antal") {
      const alle = STAT.kommuner;
      const nævner = (x) => (mål === "indbyggere" ? x.indbyggere : x.husstande) || 0;
      const total = alle.reduce((a, x) => a + nævner(x), 0);
      serier.push({ navn: "Jylland i alt", farve: css("--ref"), ref: true,
        v: kv.map((q) => (alle.reduce((a, x) => a + (x.antal[q] || 0), 0) / total) * 1000) });
    }
    $("grafTitel").textContent = `Anmeldte indbrud i beboelse pr. kvartal – ${M.navn}`;
    chips(grafValg, (g) => (kom.get(g.kode) || {}).navn || g.kode, $("grafValg"), SLOTS.length);
    $("grafTilføj").innerHTML = '<option value="">+ Tilføj kommune…</option>' +
      [...STAT.kommuner].sort((a, b) => a.navn.localeCompare(b.navn, "da"))
        .filter((x) => !grafValg.some((g) => g.kode === x.kode))
        .map((x) => `<option value="${esc(x.kode)}">${esc(x.navn)}</option>`).join("");
    linjegraf({
      svg: $("graf"), tip: $("grafTip"), tabel: $("grafTabel"), tom: $("grafTom"), dec: M.dec, kolonne: "Kvartal",
      perioder: kv.map((q) => ({ kort: `${q.slice(5)}. kv`, år: q.endsWith("K1") ? q.slice(0, 4) : null, årAltid: q.slice(0, 4), lang: kvt(q) })),
      serier,
    });
  }

  // ---------- egen langtidsstatistik fra døgnrapporterne ----------
  let OMR = null, egenValg = [];
  const MDR = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  const MDR_LANG = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober", "november", "december"];

  function månederMellem(fra, til) {
    const ud = []; let [y, m] = fra.split("-").map(Number); const [ty, tm] = til.split("-").map(Number);
    while (y < ty || (y === ty && m <= tm)) { ud.push(`${y}-${String(m).padStart(2, "0")}`); if (++m > 12) { m = 1; y++; } }
    return ud;
  }

  function egneEnheder() {
    const kreds = $("egenKreds").value, niveau = $("egenNiveau").value;
    const liste = niveau === "byer" ? OMR.byer : niveau === "kommuner" ? (OMR.kommuner || []) : OMR.omraader;
    return liste.filter((x) => x.kreds === kreds).map((x) => ({
      ...x, kode: niveau === "byer" ? `${x.omraade}|${x.navn}` : x.navn,
      vis: niveau === "byer" && x.omraade !== x.navn ? `${x.navn} (${x.omraade})` : niveau === "kommuner" ? `${x.navn} Kommune` : x.navn,
      total: Object.values(x.antal).reduce((a, b) => a + b, 0),
    }));
  }

  function egnePerioder() {
    const kreds = $("egenKreds").value, inddeling = $("egenInddeling").value, d = OMR.daekning[kreds];
    const mdr = månederMellem(d.fra.slice(0, 7), d.til.slice(0, 7));
    const igang = d.til.slice(0, 7);
    if (inddeling === "maaned") {
      return mdr.map((md) => {
        const [y, m] = md.split("-");
        return { mdr: [md], kort: MDR[+m - 1], år: m === "01" ? y : null, årAltid: y,
          lang: `${MDR_LANG[+m - 1]} ${y}${md === igang ? " (indtil nu)" : ""}` };
      });
    }
    const grupper = new Map();
    for (const md of mdr) {
      const [y, m] = md.split("-");
      const k = inddeling === "aar" ? y : `${y}K${Math.ceil(+m / 3)}`;
      if (!grupper.has(k)) grupper.set(k, []);
      grupper.get(k).push(md);
    }
    return [...grupper].map(([k, ms]) => {
      const igangværende = ms.includes(igang), delvis = igangværende || ms.length < (inddeling === "aar" ? 12 : 3);
      const lang = (inddeling === "aar" ? k : kvt(k)) + (igangværende ? " (indtil nu)" : delvis ? " (delvis)" : "");
      return inddeling === "aar"
        ? { mdr: ms, kort: k, år: null, årAltid: null, lang }
        : { mdr: ms, kort: `${k.slice(5)}. kv`, år: k.endsWith("K1") ? k.slice(0, 4) : null, årAltid: k.slice(0, 4), lang };
    });
  }

  function tilføjEgen(kode) {
    if (egenValg.some((g) => g.kode === kode)) return;
    if (egenValg.length >= SLOTS.length) egenValg.shift();
    const brugt = new Set(egenValg.map((g) => g.slot));
    egenValg.push({ kode, slot: SLOTS.find((s) => !brugt.has(s)) });
    tegnEgen();
  }

  function standardEgen() {
    egenValg = [];
    egneEnheder().sort((a, b) => b.total - a.total).slice(0, 3).forEach((x) => egenValg.push({ kode: x.kode, slot: SLOTS[egenValg.length] }));
  }

  function tegnEgen() {
    if (!OMR) return;
    const enheder = new Map(egneEnheder().map((x) => [x.kode, x]));
    egenValg = egenValg.filter((g) => enheder.has(g.kode));
    const perioder = egnePerioder();
    const sum = (x, mdr) => mdr.reduce((a, md) => a + (x.antal[md] || 0), 0);
    // Mål: antal, eller pr. 1.000 indbyggere/husstande (kun kommuner – Danmarks Statistiks tal findes pr. kommune)
    const niveauNu = $("egenNiveau").value;
    const kanRate = niveauNu === "kommuner" && STAT;
    for (const o of $("egenMaal").options) if (o.value !== "antal") o.disabled = !kanRate;
    if (!kanRate) $("egenMaal").value = "antal";
    const mål = $("egenMaal").value, M = MÅL[mål] || MÅL.antal;
    $("egenMaalHint").hidden = !!kanRate;
    const nævner = (x) => {
      if (mål === "antal") return 1;
      const k = STAT && STAT.kommuner.find((s) => s.navn === x.navn);
      const n = k && (mål === "indbyggere" ? k.indbyggere : k.husstande);
      return n ? n / 1000 : null;
    };
    const værdi = (x, mdr) => { const n = nævner(x); return n ? sum(x, mdr) / n : null; };
    const serier = egenValg.map((g) => ({ navn: enheder.get(g.kode).vis, farve: css(g.slot), v: perioder.map((p) => værdi(enheder.get(g.kode), p.mdr)) }));
    chips(egenValg, (g) => (enheder.get(g.kode) || {}).vis || g.kode, $("egenValg"), SLOTS.length);
    const niv = niveauNu === "byer" ? "by/bydel" : niveauNu === "kommuner" ? "kommune" : "område";
    $("egenTilføj").innerHTML = `<option value="">+ Tilføj ${niv}…</option>` +
      [...enheder.values()].filter((x) => !egenValg.some((g) => g.kode === x.kode))
        .sort((a, b) => a.vis.localeCompare(b.vis, "da")).map((x) => `<option value="${esc(x.kode)}">${esc(x.vis)} (${tal(x.total)})</option>`).join("");
    const kreds = $("egenKreds").value, d = OMR.daekning[kreds];
    const fmt = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("da-DK", { day: "numeric", month: "long", year: "numeric" });
    $("egenSub").textContent = `${kreds}: ${tal([...enheder.values()].reduce((a, x) => a + x.total, 0))} indbrud fra døgnrapporterne ${fmt(d.fra)} – ${fmt(d.til)}, talt efter rapportdato.` +
      (kreds === "Nordjyllands Politi" ? " Nordjylland nævner kun udvalgte indbrud." : " Østjylland lister alle anmeldte indbrud i privat beboelse.");
    $("egenTitel").textContent = `Egen statistik fra døgnrapporterne${mål === "antal" ? "" : " – " + M.navn}`;
    linjegraf({ svg: $("egenGraf"), tip: $("egenTip"), tabel: $("egenTabel"), tom: $("egenTom"), perioder, serier, dec: M.dec, kolonne: "Periode" });

    // rangliste: seneste 12 hele måneder mod de 12 før
    const alle = månederMellem(d.fra.slice(0, 7), d.til.slice(0, 7)).slice(0, -1);
    const nu = alle.slice(-12), før = alle.slice(-24, -12);
    const rang = [...enheder.values()].map((x) => ({ x, n: værdi(x, nu), f: før.length === 12 ? værdi(x, før) : null }))
      .filter((r) => r.n > 0).sort((a, b) => b.n - a.n).slice(0, 15);
    const periodeTekst = nu.length ? `${MDR_LANG[+nu[0].slice(5) - 1]} ${nu[0].slice(0, 4)} – ${MDR_LANG[+nu[nu.length - 1].slice(5) - 1]} ${nu[nu.length - 1].slice(0, 4)}` : "";
    $("egenRang").innerHTML = `<div class="day">Flest indbrud · ${esc(periodeTekst)}</div><table><thead><tr><th>#</th><th>${niv[0].toUpperCase() + niv.slice(1)}</th><th>${mål === "antal" ? "Indbrud" : "Indbrud " + esc(M.navn)}</th><th>12 mdr. før</th></tr></thead><tbody>` +
      rang.map((r, i) => {
        const æ = r.f ? ` <span class="${r.n > r.f ? "op" : r.n < r.f ? "ned" : ""}">(${r.n >= r.f ? "+" : "−"}${tal(Math.abs(Math.round(((r.n - r.f) / r.f) * 100)))} %)</span>` : "";
        return `<tr data-kode="${esc(r.x.kode)}"><td>${i + 1}</td><td>${esc(r.x.vis)}</td><td>${tal(r.n, M.dec)}</td><td>${r.f == null ? "–" : tal(r.f, M.dec) + æ}</td></tr>`;
      }).join("") + "</tbody></table>";
  }

  hentData("omraader.json").then((d) => {
    OMR = d;
    const kredse = Object.keys(d.daekning).sort((a, b) => (d.daekning[a].fra < d.daekning[b].fra ? -1 : 1));
    if (!kredse.length) return;
    $("egenKreds").innerHTML = kredse.map((k) => `<option>${esc(k)}</option>`).join("");
    $("egenBoks").hidden = false;
    standardEgen();
    tegnEgen();
  }).catch(() => { /* valgfri */ });
  for (const id of ["egenKreds", "egenNiveau"]) $(id).addEventListener("change", () => { standardEgen(); tegnEgen(); });
  $("egenInddeling").addEventListener("change", tegnEgen);
  $("egenMaal").addEventListener("change", tegnEgen);
  $("egenTilføj").addEventListener("change", (e) => { if (e.target.value) tilføjEgen(e.target.value); });
  $("egenValg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-fjern]"); if (!b) return;
    egenValg = egenValg.filter((g) => g.kode !== b.dataset.fjern); tegnEgen();
  });
  $("egenRang").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-kode]"); if (tr) tilføjEgen(tr.dataset.kode); });


  $("grafValg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-fjern]"); if (!b) return;
    grafValg = grafValg.filter((g) => g.kode !== b.dataset.fjern); tegnGraf();
  });
  $("grafTilføj").addEventListener("change", (e) => { if (e.target.value) tilføjGraf(e.target.value); });
  let grafTimer;
  addEventListener("resize", () => { clearTimeout(grafTimer); grafTimer = setTimeout(() => { tegnGraf(); tegnEgen(); }, 150); });

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
    tegnEgen(); // pr. indbygger/husstand i egen statistik bruger Danmarks Statistiks tal
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

  // ---------- naboveje og "nær mig" ----------
  let NABO = {};
  const naboNøgle = (r) => `${r.lat.toFixed(4)},${r.lon.toFixed(4)}`;
  function naboveje(r) { return r.praecision === "vej" && r.lat != null ? NABO[naboNøgle(r)] || null : null; }
  function naboHtml(r) {
    const v = naboveje(r);
    if (!v || !v.length) return "";
    return `<div class="nabo"><b>Naboveje (inden for ca. 500 m):</b> ${esc(v.map((x) => x.vej).join(", "))}</div>`;
  }
  hentData("naboveje.json").then((d) => { NABO = d; }).catch(() => { /* valgfri */ });

  const NÆR_KM = 5, NÆR_DAGE = 14;
  const nærLag = L.layerGroup().addTo(map);
  function afstandKm(a, b) {
    const k = Math.cos(((a[0] + b[0]) / 2) * Math.PI / 180);
    return Math.hypot((a[1] - b[1]) * k, a[0] - b[0]) * 111.32;
  }
  function visNær(pos) {
    const her = [pos.coords.latitude, pos.coords.longitude];
    const grænse = new Date(); grænse.setDate(grænse.getDate() - NÆR_DAGE);
    const fra = grænse.toISOString().slice(0, 10);
    const fund = DATA.filter((r) => r.rapportdato >= fra)
      .map((r) => ({ r, km: afstandKm(her, [r.lat, r.lon]) }))
      .filter((x) => x.km <= NÆR_KM).sort((a, b) => a.km - b.km);
    nærLag.clearLayers();
    L.circle(her, { radius: NÆR_KM * 1000, color: css("--sel"), weight: 1.5, fillOpacity: 0.04, interactive: false }).addTo(nærLag);
    L.circleMarker(her, { radius: 7, color: "#fff", weight: 2, fillColor: css("--sel"), fillOpacity: 1 }).bindTooltip("Du er her").addTo(nærLag);
    // vis de seneste 14 dage på kortet, så alle fundne punkter er tegnet
    state.dato = ""; state.periode = NÆR_DAGE; state.omraade = ""; state.kreds = "";
    fyldVælgere(); tegn(false);
    map.fitBounds(L.latLng(her).toBounds(NÆR_KM * 2000), { padding: [10, 10] });
    $("naerSub").textContent = fund.length
      ? `${fund.length} anmeldte indbrud i døgnrapporterne inden for ${NÆR_KM} km af din placering siden ${dag(fra)}. Nærmeste først.`
      : `Ingen indbrud i døgnrapporterne inden for ${NÆR_KM} km siden ${dag(fra)}. Bemærk: vej-data findes kun for Øst- og Nordjylland.`;
    $("naerListe").innerHTML = fund.map(({ r, km }) => {
      const nv = naboveje(r);
      return `<button class="item" data-id="${esc(r.id)}"><span class="km">${km < 1 ? Math.round(km * 1000) + " m" : tal(km, 1) + " km"}</span>` +
        `<span class="st">${esc(navn(r))}${r.postnr ? ` <span class="t">${esc(r.postnr)}</span>` : ""}</span>` +
        `<span class="t">${esc(dag(r.rapportdato))} · ${esc(r.gerningstid)}${r.praecision === "by" ? " · ca. placering (byens midte)" : ""}</span>` +
        (nv && nv.length ? `<span class="nabo">Naboveje: ${esc(nv.slice(0, 10).map((x) => x.vej).join(", "))}${nv.length > 10 ? " …" : ""}</span>` : "") +
        "</button>";
    }).join("");
  }
  $("naerKnap").addEventListener("click", () => {
    const knap = $("naerKnap");
    $("naerBoks").hidden = false;
    if (!navigator.geolocation) { $("naerSub").textContent = "Din browser kan ikke oplyse din placering."; return; }
    knap.disabled = true; $("naerSub").textContent = "Finder din placering …"; $("naerListe").innerHTML = "";
    navigator.geolocation.getCurrentPosition((pos) => { knap.disabled = false; visNær(pos); }, (fejl) => {
      knap.disabled = false;
      $("naerSub").textContent = fejl.code === 1
        ? "Siden fik ikke lov at se din placering. Tillad placering for siden i browserens indstillinger og prøv igen."
        : "Kunne ikke finde din placering. Prøv igen udenfor eller med GPS slået til.";
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
  });
  $("naerListe").addEventListener("click", (e) => {
    const b = e.target.closest(".item"); if (!b) return;
    $("map").scrollIntoView({ behavior: "smooth", block: "center" });
    vælg(b.dataset.id, "liste");
  });

  // ---------- hotspots ----------
  // Tæller efter rapportdato i de seneste N dage (regnet fra nyeste døgnrapport) mod de N dage før.
  let ALLE = [];
  const HOT_NØGLE = {
    bydele: (r) => r.by || null,
    postnumre: (r) => r.postnr || null,
    veje: (r) => (r.vej && r.by ? `${r.vej}, ${r.by}` : null),
  };
  function tegnHotspots() {
    const niveau = $("hotNiveau").value, dage = +$("hotDage").value, sort = $("hotSort").value, kreds = $("hotKreds").value;
    const slut = new Date(seneste + "T12:00:00");
    const dato = (n) => { const d = new Date(slut); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
    const nuFra = dato(dage - 1), førFra = dato(2 * dage - 1);
    const nøgle = HOT_NØGLE[niveau], rækker = new Map();
    for (const r of ALLE) {
      if (r.rapportdato < førFra || (kreds && r.politikreds !== kreds)) continue;
      const k = nøgle(r); if (!k) continue;
      if (!rækker.has(k)) rækker.set(k, { navn: k, n: 0, f: 0, byer: {}, ids: [] });
      const x = rækker.get(k);
      if (r.rapportdato >= nuFra) { x.n++; x.ids.push(r.id); if (r.by) x.byer[r.by] = (x.byer[r.by] || 0) + 1; } else x.f++;
    }
    let liste = [...rækker.values()].filter((x) => x.n > 0);
    if (sort === "forskel") liste = liste.filter((x) => x.n - x.f > 0 && x.n >= 2).sort((a, b) => (b.n - b.f) - (a.n - a.f) || b.n - a.n);
    else liste.sort((a, b) => b.n - a.n || (b.n - b.f) - (a.n - a.f) || a.navn.localeCompare(b.navn, "da"));
    liste = liste.slice(0, 25);
    const maks = Math.max(1, ...liste.map((x) => x.n));
    const kol = { bydele: "By/bydel", postnumre: "Postnummer", veje: "Vej" }[niveau];
    const manglerPnr = niveau === "postnumre" ? ALLE.filter((r) => r.rapportdato >= nuFra && r.lat != null && !r.postnr).length : 0;
    $("hotTabel").innerHTML = (liste.length
      ? `<table><thead><tr><th>#</th><th>${kol}</th><th>Indbrud</th><th>Før</th><th>Ændring</th></tr></thead><tbody>` +
        liste.map((x, i) => {
          const d = x.n - x.f;
          const byer = niveau === "postnumre" ? Object.entries(x.byer).sort((a, b) => b[1] - a[1]).slice(0, 3).map((e) => e[0]).join(", ") : "";
          return `<tr data-ids="${esc(x.ids.join(","))}"><td>${i + 1}</td><td>${esc(x.navn)}${byer ? ` <span class="sub">${esc(byer)}</span>` : ""}</td>` +
            `<td>${tal(x.n)}<i class="bar" style="width:${Math.round((x.n / maks) * 60)}px"></i></td><td>${tal(x.f)}</td>` +
            `<td class="${d > 0 ? "op" : d < 0 ? "ned" : ""}">${d > 0 ? "+" : d < 0 ? "−" : ""}${tal(Math.abs(d))}</td></tr>`;
        }).join("") + "</tbody></table>"
      : `<p class="empty">${sort === "forskel" ? "Ingen steder med mindst 2 indbrud og en stigning i perioden." : "Ingen indbrud i perioden."}</p>`) +
      (manglerPnr ? `<p class="ghint">${tal(manglerPnr)} indbrud i perioden mangler endnu postnummer – de slås op ved de daglige kørsler.</p>` : "");
  }
  ["hotNiveau", "hotDage", "hotSort", "hotKreds"].forEach((id) => $(id).addEventListener("change", tegnHotspots));
  $("hotTabel").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-ids]"); if (!tr) return;
    const ids = new Set(tr.dataset.ids.split(","));
    const punkter = DATA.filter((r) => ids.has(r.id) && r._ll);
    if (!punkter.length) return;
    // vis samme periode på kortet som i listen, så rækkens punkter er tegnet
    state.dato = ""; state.periode = +$("hotDage").value; state.omraade = ""; state.kreds = $("hotKreds").value;
    fyldVælgere(); tegn(false);
    $("map").scrollIntoView({ behavior: "smooth", block: "center" });
    map.fitBounds(L.latLngBounds(punkter.map((r) => r._ll)), { padding: [40, 40], maxZoom: 15 });
  });

  // ---------- ugens overblik ----------
  function tegnUge(d) {
    const u = d.uge, kort = (iso) => { const x = new Date(iso + "T12:00:00"); return `${x.getDate()}/${x.getMonth() + 1}`; };
    const diff = u.antal - u.foer;
    $("ugeSub").innerHTML = `<b>${tal(u.antal)}</b> anmeldte indbrud i døgnrapporterne ${kort(u.fra)}–${kort(u.til)} ` +
      `(${diff >= 0 ? "+" : "−"}${tal(Math.abs(diff))} mod ugen før). ${esc(d.kredse.join(", "))}.`;
    const blok = (titel, rækker, tom) => `<div><h3>${titel}</h3>` + (rækker.length
      ? `<ol>${rækker.slice(0, 5).map((r) => `<li>${esc(r.navn)}${r.byer ? ` <span>${esc(r.byer.join(", "))}</span>` : ""} <span>${tal(r.antal)} <b class="op">+${tal(r.forskel)}</b></span></li>`).join("")}</ol>`
      : `<p class="ghint">${tom}</p>`) + "</div>";
    const tom = "Ingen steder med mindst 2 indbrud og en stigning.";
    let h = blok("Størst stigning · bydele", u.bydele.stigning, tom) +
      blok("Størst stigning · postnumre", u.postnumre.stigning, tom) +
      blok("Størst stigning · veje", u.veje.stigning, tom);
    if (d.dst && d.dst.stigning.length) {
      h += `<div><h3>Danmarks Statistik · ${esc(d.dst.kvartal.replace("K", ". kvt. "))} mod året før</h3><ol>` +
        d.dst.stigning.slice(0, 5).map((r) => `<li>${esc(r.navn)} <span>${tal(r.antal)} <b class="op">+${tal(r.forskel)}</b></span></li>`).join("") + "</ol></div>";
    }
    $("ugeGrid").innerHTML = h;
    $("ugeBoks").hidden = false;
  }
  hentData("ugerapport.json").then(tegnUge).catch(() => { /* ugerapporten er valgfri */ });

  hentData().then((d) => {
    ALLE = d.indbrud;
    DATA = d.indbrud.filter((r) => r.lat != null);
    seneste = DATA.reduce((m, r) => (r.rapportdato > m ? r.rapportdato : m), "");
    spred(DATA);
    const datoer = DATA.map((r) => r.rapportdato).sort();
    if (datoer.length) $("eyebrow").textContent = `Jyske politikredse · døgnrapporter ${dag(datoer[0])} – ${dag(datoer[datoer.length - 1])}`;
    $("opdateret").innerHTML = `<b>Opdateret.</b> ${esc(new Date(d.opdateret).toLocaleString("da-DK", { dateStyle: "long", timeStyle: "short" }))}.`;
    fyldVælgere();
    tegn(false);
    const kredse = [...new Set(ALLE.map((r) => r.politikreds))].sort();
    $("hotKreds").innerHTML = '<option value="">Alle kredse</option>' + kredse.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join("");
    tegnHotspots();
    $("hotBoks").hidden = false;
    map.fitBounds([[54.8, 8.05], [57.75, 10.95]]); // hele Jylland ved første visning
  }).catch(() => {
    $("list").innerHTML = '<p class="empty">Kunne ikke hente data/indbrud.json.</p>';
  });
})();
