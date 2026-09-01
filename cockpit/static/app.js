// Helfer-Cockpit 2 — Frontend. Läuft ausschliesslich gegen 127.0.0.1, ohne Framework,
// ohne CDN. Alle Daten kommen per fetch() von der lokalen JSON-API (cockpit/webapp.py).
"use strict";

// ------------------------------------------------------------------ Zustand ----
const S = {
  sicht: "saison",                          // "saison" | "halbjahr"
  daten: null,                              // letzte Antwort von /api/stand
  regeln: null,
  k: { filter: "alle", suche: "", sort: { key: "status", dir: "asc" }, offen: new Set() },
  h: { filter: "alle", suche: "", sort: { key: "name", dir: "asc" } },
};

const TYP_LABEL = { mitglied: "Mitglied", zweitaccount: "Zweitaccount", freiwillig: "Freiwillig",
                    unbekannt: "Unbekannt", unklassifiziert: "Unklassifiziert" };
const STATUS = {
  erfuellt: { label: "Erfüllt", cls: "ok", rang: 2 },
  auf_kurs: { label: "Auf Kurs", cls: "warn", rang: 1 },
  saeumig:  { label: "Säumig", cls: "crit", rang: 0 },
};
const SCHWERE = {
  kritisch: { titel: "Kritisch — jetzt bereinigen", cls: "crit", farbe: "var(--red)" },
  warnung:  { titel: "Warnung — beim nächsten Abgleich", cls: "warn", farbe: "var(--warn)" },
  hinweis:  { titel: "Hinweis — zur Kenntnis", cls: "info", farbe: "var(--info)" },
};

// ------------------------------------------------------------------ Helfer ----
const $ = (id) => document.getElementById(id);
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmt(n) { n = Number(n) || 0; return Number.isInteger(n) ? String(n) : n.toFixed(1).replace(".", ","); }
function ic(name, cls = "") { return `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`; }
function basename(p) { return String(p || "").split(/[\\/]/).pop(); }
function ausgabeLink(pfad) { return "/ausgabe/" + encodeURIComponent(basename(pfad)); }
function vergleich(a, b) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a ?? "").localeCompare(String(b ?? ""), "de", { sensitivity: "base", numeric: true });
}

// Fehler je Quelle — eine erfolgreiche Quelle darf den Fehler einer anderen nicht löschen.
const fehlerQuellen = new Map();
function zeigeFehler(quelle, msg) {
  if (msg) fehlerQuellen.set(quelle, msg); else fehlerQuellen.delete(quelle);
  const el = $("fehler-banner");
  $("fehler-text").textContent = [...fehlerQuellen.values()].join("  ·  ");
  el.hidden = fehlerQuellen.size === 0;
}
let toastTimer = null;
function toast(msg, link) {
  const el = $("toast");
  el.innerHTML = ic("check") + `<span>${esc(msg)}</span>` +
    (link ? ` <a href="${esc(link.href)}" target="_blank" rel="noopener">${esc(link.text)}</a>` : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, link ? 12000 : 5000);
}
async function holeJson(url, optionen) {
  let r;
  try { r = await fetch(url, optionen); }
  catch (e) { throw new Error(`Server nicht erreichbar (${url}) — läuft das Cockpit noch?`); }
  let daten = null;
  try { daten = await r.json(); } catch (e) { daten = null; }
  if (!r.ok) throw new Error((daten && daten.fehler) || `Serverfehler ${r.status} bei ${url}.`);
  return daten;
}

// ------------------------------------------------------------------ Navigation ----
function zeigePanel(id) {
  document.querySelectorAll(".navitem").forEach((b) => {
    if (b.dataset.panel === id) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  document.querySelectorAll("section.panel").forEach((p) => p.classList.toggle("active", p.id === id));
  window.scrollTo({ top: 0 });
}

// ------------------------------------------------------------------ Laden ----
async function ladeStand() {
  try { anwenden(await holeJson("/api/stand")); zeigeFehler("stand-transport", null); }
  catch (e) { zeigeFehler("stand-transport", e.message); }
}
async function abrufen() {
  const btn = $("btn-abrufen");
  btn.disabled = true; btn.querySelector(".ic").classList.add("spin"); btn.querySelector("span").textContent = "Wird abgerufen …";
  try {
    const d = await holeJson("/api/abruf", { method: "POST" });
    anwenden(d);
    zeigeFehler("abruf-transport", null);
    if (!d.fehler) toast(`Abgerufen: ${d.alle_accounts.length} Accounts, ${d.mitglieder.length} Mitglieder.`);
    ladeProtokoll();
  } catch (e) { zeigeFehler("abruf-transport", e.message); }
  finally { btn.disabled = false; btn.querySelector(".ic").classList.remove("spin"); btn.querySelector("span").textContent = "Daten neu abrufen"; }
}
async function ladeRegeln() {
  try { S.regeln = await holeJson("/api/regeln"); befuelleRegeln(); zeigeFehler("regeln-transport", null); }
  catch (e) { zeigeFehler("regeln-transport", e.message); }
}
async function ladeProtokoll() {
  try { renderProtokoll(await holeJson("/api/protokoll")); zeigeFehler("protokoll-transport", null); }
  catch (e) { zeigeFehler("protokoll-transport", e.message); }
}

function anwenden(d) {
  S.daten = d;
  zeigeFehler("stand", d.fehler || null);
  const geladen = d.mitglieder.length > 0 || d.alle_accounts.length > 0;
  $("stand-anzeige").textContent = geladen ? `${d.alle_accounts.length} Accounts · Stand ${d.stand}` : "Noch nicht abgerufen";
  $("nav-n-kontingent").textContent = geladen ? d.mitglieder.length : "";
  $("nav-n-helfende").textContent = geladen ? d.alle_accounts.length : "";
  const nDq = $("nav-n-dq");
  nDq.textContent = d.hinweise.length || "";
  nDq.className = "n num " + (d.hinweise.some((h) => h.schweregrad === "kritisch") ? "crit" : d.hinweise.length ? "warn" : "");
  $("abgleich-helfer-status").innerHTML = geladen
    ? ic("check") + `<span>Automatisch über die API — ${d.alle_accounts.length} Accounts, Stand ${esc(d.stand)}</span>`
    : ic("info") + `<span>Noch nicht abgerufen — «Daten neu abrufen» in der Seitenleiste.</span>`;
  renderKennzahlen(); renderTabelleK(); renderTabelleH(); renderBericht(); renderDQ();
}

// ------------------------------------------------------------------ Kontingent ----
function statusVon(m) { return S.sicht === "saison" ? m.status_saison : m.status_halbjahr; }
function zielVon(m) { return S.sicht === "saison" ? m.soll : (S.regeln ? S.regeln.halbjahresziel : 1); }
function prozent(m) { const z = zielVon(m); return z > 0 ? Math.min(100, Math.round(m.ist / z * 100)) : 100; }
function balken(m) {
  const s = statusVon(m); const cls = s === "erfuellt" ? "g" : s === "auf_kurs" ? "o" : "r";
  return `<span class="bar" aria-hidden="true"><i class="${cls}" style="width:${Math.max(prozent(m), m.ist > 0 ? 6 : 0)}%"></i></span>`;
}
function statusChip(s) { const st = STATUS[s] || STATUS.saeumig; return `<span class="status ${st.cls}">${st.label}</span>`; }

function setSicht(sicht) {
  S.sicht = sicht;
  document.querySelectorAll('.seg [data-sicht]').forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sicht === sicht)));
  $("sicht-label").textContent = sicht === "saison" ? "Sicht: Saison-Soll" : `Sicht: Halbjahresziel (mind. ${S.regeln ? S.regeln.halbjahresziel : 1} Einsatz)`;
  if (S.daten) { renderKennzahlen(); renderTabelleK(); renderBericht(); }
}

function renderKennzahlen() {
  const d = S.daten, k = d.kennzahlen, n = d.mitglieder.length;
  const of = (x) => `${fmt(x)}<span class="of">/ ${n}</span>`;
  const geladen = n > 0;
  $("kpi-erfuellt").innerHTML = geladen ? of(k.erfuellt) : "–";
  $("kpi-erfuellt-h").textContent = geladen ? `${Math.round(k.erfuellt / n * 100)} % der Mitglieder` : "";
  $("kpi-halbjahr").innerHTML = geladen ? of(k.halbjahr_erreicht) : "–";
  $("kpi-halbjahr-h").textContent = geladen ? `mind. ${S.regeln ? S.regeln.halbjahresziel : 1} Einsatz bis Halbjahr` : "";
  $("kpi-ohne").textContent = geladen ? fmt(k.ohne_einsatz) : "–";
  $("kpi-istsoll").innerHTML = geladen ? `${fmt(k.ist_summe)}<span class="of">/ ${fmt(k.soll_summe)}</span>` : "–";
  $("kpi-zweit").textContent = geladen ? fmt(k.zweitaccounts) : "–";
  // Chip-Zähler (immer über den Gesamtbestand, unabhängig vom aktiven Filter)
  const z = { alle: n, erfuellt: 0, auf_kurs: 0, saeumig: 0, zweitaccount: 0 };
  d.mitglieder.forEach((m) => { z[statusVon(m)]++; if (m.accounts.length > 1) z.zweitaccount++; });
  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => { c.querySelector(".c").textContent = z[c.dataset.filter] ?? 0; });
}

function gefilterteMitglieder() {
  const f = S.k.filter, q = S.k.suche.trim().toLowerCase();
  let liste = S.daten.mitglieder.filter((m) => {
    if (f === "zweitaccount" && m.accounts.length < 2) return false;
    if (f !== "alle" && f !== "zweitaccount" && statusVon(m) !== f) return false;
    if (q && !(m.name.toLowerCase().includes(q) || m.fg.toLowerCase().includes(q)
               || m.accounts.some((a) => a.name.toLowerCase().includes(q)))) return false;
    return true;
  });
  const { key, dir } = S.k.sort;
  const wert = (m) => ({
    name: m.name, gruppen: m.gruppen.join(", "), accounts: m.accounts.length, soll: m.soll, ist: m.ist,
    status: STATUS[statusVon(m)].rang,
  })[key];
  liste.sort((a, b) => (vergleich(wert(a), wert(b)) || vergleich(a.name, b.name)) * (dir === "asc" ? 1 : -1));
  return liste;
}

function hinweiseZu(m) {
  const namen = new Set(m.accounts.map((a) => a.name));
  return (S.daten.hinweise || []).filter((h) => h.betroffene.some((b) => b === m.fg || b.includes(m.fg) || namen.has(nameAus(b))));
}
function nameAus(betroffen) { return String(betroffen).split(/ \(|: |«/)[0].trim(); }

function renderTabelleK() {
  const liste = gefilterteMitglieder();
  const body = $("tab-mitglieder-body");
  const n = S.daten.mitglieder.length;
  if (!n) { body.innerHTML = `<tr><td colspan="7"><div class="empty"><b>Noch keine Daten</b>Klicke links auf «Daten neu abrufen», um die Helfenden aus dem Portal zu laden.</div></td></tr>`; $("tfoot-kontingent").textContent = ""; return; }
  if (!liste.length) { body.innerHTML = `<tr><td colspan="7"><div class="empty"><b>Kein Treffer</b>Filter oder Suchbegriff anpassen.</div></td></tr>`; }
  else body.innerHTML = liste.map(zeileK).join("");
  const sortName = { name: "Name", gruppen: "Gruppen", accounts: "Accounts", soll: "Soll", ist: "Ist", status: "Status" }[S.k.sort.key];
  $("tfoot-kontingent").innerHTML = `<span>${liste.length} von ${n} Mitgliedern</span><span>· sortiert nach ${sortName}</span><span style="margin-left:auto">Zusammenführung ausschliesslich über FG-Nummer</span>`;
  markiereSort("tab-mitglieder", S.k.sort);
}

function zeileK(m) {
  const offen = S.k.offen.has(m.fg);
  const mehrere = m.accounts.length > 1;
  const summanden = mehrere ? `<span class="sub">(${m.accounts.map((a) => fmt(a.ist)).join(" + ")})</span>` : "";
  const konflikt = m.soll_konflikt ? ` <span class="konflikt" title="Mehrere Mitglieds-Accounts mit dieser FG-Nummer — im Portal bereinigen">${ic("alert", "sm")}Konflikt</span>` : "";
  return `
    <tr class="row" data-fg="${esc(m.fg)}" role="button" tabindex="0" aria-expanded="${offen}">
      <td><div class="cell-name">${ic("chev", "sm chev")}<div><span class="name">${esc(m.name)}</span> <span class="fgtag">${esc(m.fg)}</span></div></div></td>
      <td class="sub">${esc(m.gruppen.join(", "))}</td>
      <td class="r num">${m.accounts.length}</td>
      <td class="r num">${fmt(m.soll)}${konflikt}</td>
      <td class="r num"><b>${fmt(m.ist)}</b> ${summanden}</td>
      <td>${balken(m)}</td>
      <td>${statusChip(statusVon(m))}</td>
    </tr>
    <tr class="detail" data-detail="${esc(m.fg)}" ${offen ? "" : "hidden"}><td colspan="7">${offen ? ledger(m) : ""}</td></tr>`;
}

function ledger(m) {
  const zeilen = m.accounts.map((a) => `
    <tr><td><b>${esc(a.name)}</b></td><td><span class="typ ${esc(a.typ)}">${TYP_LABEL[a.typ] || a.typ}</span></td>
    <td class="r num">${fmt(a.ist)}</td><td class="r num">${fmt(a.soll)}</td><td class="r num">${a.num_ok} / ${a.num_confirmed} / ${a.num_nok}</td>
    <td class="sub">${esc(a.bemerkung) || "—"}</td>
    <td><a class="plink" href="${esc(a.portal_url)}" target="_blank" rel="noopener" title="Im Helferportal öffnen">${ic("external", "sm")}Portal</a></td></tr>`).join("");
  const hinweise = hinweiseZu(m);
  const dq = hinweise.length ? `<div class="dq">${hinweise.map((h) => `<div><span class="code ${SCHWERE[h.schweregrad].cls}">${esc(h.code)}</span><span>${esc(h.text)}</span></div>`).join("")}</div>` : "";
  const ziel = zielVon(m);
  const sum = `Ist ${fmt(m.ist)} ${m.accounts.length > 1 ? "= " + m.accounts.map((a) => fmt(a.ist)).join(" + ") : ""} · Ziel ${fmt(ziel)} (${S.sicht === "saison" ? "Saison-Soll" : "Halbjahresziel"})`;
  return `<div class="ledger">
    <table><thead><tr><th>Account</th><th>Typ</th><th class="r">Ist</th><th class="r">Soll</th><th class="r" title="Geleistet / Zugesagt / Nicht erschienen">OK / Zug. / NOK</th><th>Bemerkung</th><th></th></tr></thead><tbody>${zeilen}</tbody></table>
    <div class="sum num">${esc(sum)}</div>${dq}</div>`;
}

function toggleZeile(fg) {
  if (S.k.offen.has(fg)) S.k.offen.delete(fg); else S.k.offen.add(fg);
  renderTabelleK();
}

function springeZuMitglied(fg) {
  S.k.filter = "alle"; S.k.suche = ""; $("suche-kontingent").value = "";
  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.filter === "alle")));
  S.k.offen.add(fg);
  zeigePanel("p-kontingent"); renderTabelleK();
  const tr = document.querySelector(`#tab-mitglieder-body tr.row[data-fg="${CSS.escape(fg)}"]`);
  if (tr) { tr.scrollIntoView({ block: "center" }); tr.classList.add("flash"); tr.focus(); }
}

// ------------------------------------------------------------------ Alle Helfenden ----
function gefilterteAccounts() {
  const f = S.h.filter, q = S.h.suche.trim().toLowerCase();
  let liste = S.daten.alle_accounts.filter((a) => {
    if (f === "aktiv" && !(a.num_ok + a.num_confirmed > 0)) return false;
    if (f !== "alle" && f !== "aktiv" && a.typ !== f) return false;
    if (q && !(a.name.toLowerCase().includes(q) || (a.fg || "").toLowerCase().includes(q)
               || a.gruppen.join(", ").toLowerCase().includes(q))) return false;
    return true;
  });
  const { key, dir } = S.h.sort;
  const wert = (a) => key === "gruppen" ? a.gruppen.join(", ") : key === "typ" ? (TYP_LABEL[a.typ] || a.typ) : a[key];
  liste.sort((a, b) => (vergleich(wert(a), wert(b)) || vergleich(a.name, b.name)) * (dir === "asc" ? 1 : -1));
  return liste;
}
function renderTabelleH() {
  const d = S.daten, alle = d.alle_accounts;
  const z = { alle: alle.length, aktiv: 0 };
  alle.forEach((a) => { z[a.typ] = (z[a.typ] || 0) + 1; if (a.num_ok + a.num_confirmed > 0) z.aktiv++; });
  document.querySelectorAll("#chips-helfende .chip").forEach((c) => {
    const t = c.dataset.typ; c.querySelector(".c").textContent = z[t] || 0;
    if (t === "unklassifiziert") c.hidden = !z[t];
  });
  const liste = gefilterteAccounts(), body = $("tab-helfende-body");
  if (!alle.length) { body.innerHTML = `<tr><td colspan="8"><div class="empty"><b>Noch keine Daten</b>Klicke links auf «Daten neu abrufen».</div></td></tr>`; $("tfoot-helfende").textContent = ""; return; }
  if (!liste.length) body.innerHTML = `<tr><td colspan="8"><div class="empty"><b>Kein Treffer</b>Filter oder Suchbegriff anpassen.</div></td></tr>`;
  else body.innerHTML = liste.map((a) => `
    <tr data-id="${a.id}">
      <td><span class="name">${esc(a.name)}</span> ${a.fg ? `<span class="fgtag">${esc(a.fg)}</span>` : ""}</td>
      <td><span class="typ ${esc(a.typ)}">${TYP_LABEL[a.typ] || esc(a.typ)}</span></td>
      <td class="sub">${esc(a.gruppen.join(", "))}</td>
      <td class="r num"><b>${a.num_ok}</b></td>
      <td class="r num">${a.num_confirmed}</td>
      <td class="r num">${a.num_nok ? `<span style="color:var(--red-ink);font-weight:600">${a.num_nok}</span>` : "0"}</td>
      <td class="r num sub">${fmt(a.ist_wert)}${a.zielwert ? ` / ${fmt(a.zielwert)}` : ""}</td>
      <td><a class="plink" href="${esc(a.portal_url)}" target="_blank" rel="noopener" title="Im Helferportal öffnen">${ic("external", "sm")}Öffnen</a></td>
    </tr>`).join("");
  const sortName = { name: "Name", typ: "Typ", gruppen: "Gruppen", num_ok: "Geleistet", num_confirmed: "Zugesagt", num_nok: "Nicht erschienen", ist_wert: "Wert" }[S.h.sort.key];
  $("tfoot-helfende").innerHTML = `<span>${liste.length} von ${alle.length} Accounts</span><span>· sortiert nach ${sortName}</span><span style="margin-left:auto">Wert = angerechnete Einsatzwerte (bei Gutschrift beim Begünstigten)</span>`;
  markiereSort("tab-helfende", S.h.sort);
}
function springeZuHelfer(id, name) {
  S.h.filter = "alle"; S.h.suche = name || ""; $("suche-helfende").value = S.h.suche;
  document.querySelectorAll("#chips-helfende .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.typ === "alle")));
  zeigePanel("p-helfende"); renderTabelleH();
  const tr = document.querySelector(`#tab-helfende-body tr[data-id="${CSS.escape(String(id))}"]`);
  if (tr) { tr.classList.add("row", "flash"); tr.scrollIntoView({ block: "center" }); }
}

// ------------------------------------------------------------------ Sortierung ----
function markiereSort(tableId, sort) {
  document.querySelectorAll(`#${tableId} th[data-sort]`).forEach((th) => {
    const aktiv = th.dataset.sort === sort.key;
    th.setAttribute("aria-sort", aktiv ? (sort.dir === "asc" ? "ascending" : "descending") : "none");
    th.querySelector(".sorticon").textContent = aktiv ? (sort.dir === "asc" ? "↑" : "↓") : "↕";
  });
}
function bindeSort(tableId, sort, neuRendern) {
  document.querySelectorAll(`#${tableId} th[data-sort]`).forEach((th) => th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (sort.key === key) sort.dir = sort.dir === "asc" ? "desc" : "asc";
    else { sort.key = key; sort.dir = ["soll", "ist", "num_ok", "num_confirmed", "num_nok", "ist_wert", "accounts"].includes(key) ? "desc" : "asc"; }
    neuRendern();
  }));
}

// ------------------------------------------------------------------ Bericht ----
function renderBericht() {
  const d = S.daten, k = d.kennzahlen, n = d.mitglieder.length, geladen = n > 0;
  $("b-stand").textContent = geladen ? `Stand ${d.stand}` : "";
  const pct = geladen && k.soll_summe > 0 ? Math.round(k.ist_summe / k.soll_summe * 100) : 0;
  $("b-pct").textContent = geladen ? `${pct} %` : "–";
  $("b-ring-fill").setAttribute("stroke-dasharray", `${(Math.min(pct, 100) / 100 * 263.9).toFixed(1)} 263.9`);
  $("b-ring-fill").setAttribute("stroke", pct >= 100 ? "var(--ok)" : "var(--red)");
  $("b-sub").innerHTML = geladen ? `${fmt(k.ist_summe)} geleistete von ${fmt(k.soll_summe)} geforderten Einsätzen.<br>Zwischenziel Halbjahr: mind. ${S.regeln ? S.regeln.halbjahresziel : 1} Einsatz pro Mitglied.` : "Noch keine Daten abgerufen.";
  const of = (x) => `${fmt(x)}<span class="of">/ ${n}</span>`;
  $("b-erfuellt").innerHTML = geladen ? of(k.erfuellt) : "–";
  $("b-halbjahr").innerHTML = geladen ? of(k.halbjahr_erreicht) : "–";
  $("b-ohne").textContent = geladen ? fmt(k.ohne_einsatz) : "–";
  $("b-accounts").textContent = geladen ? d.alle_accounts.length : "–";
  $("b-zweit").textContent = geladen ? fmt(k.zweitaccounts) : "–";
  $("b-konflikt").textContent = geladen ? d.mitglieder.filter((m) => m.soll_konflikt).length : "–";
  $("b-nok").textContent = geladen ? fmt(k.nok_summe) : "–";
  $("b-dq").textContent = geladen ? d.hinweise.length : "–";

  // Kategorie-Erfüllung nur mit Fairgate-Export
  const ke = d.kategorie_erfuellung || [];
  $("b-kategorie-card").hidden = ke.length === 0;
  if (ke.length) {
    const ges = ke.reduce((s, e) => s + e.gesamt, 0), err = ke.reduce((s, e) => s + e.erreicht, 0);
    const schnitt = ges ? err / ges : 0;
    $("b-kategorie-bars").innerHTML = ke.map((e) => {
      const p = e.gesamt ? e.erreicht / e.gesamt : 0;
      return `<div class="gbar"><span>${esc(e.kategorie)}</span><span class="track"><span class="fill ${p < schnitt ? "lo" : ""}" style="width:${Math.round(p * 100)}%"></span></span><span class="val">${e.erreicht} / ${e.gesamt} · ${Math.round(p * 100)} %</span></div>`;
    }).join("") + `<div class="hintline">Vereinsschnitt: ${Math.round(schnitt * 100)} % der Mitglieder haben das Halbjahresziel erreicht.</div>`;
  }
  // Wer leistet
  const wer = d.wer_leistet || {}, total = Object.values(wer).reduce((s, v) => s + v, 0);
  const reihenfolge = ["mitglied", "zweitaccount", "freiwillig", "unbekannt", "unklassifiziert"];
  const labels = { mitglied: "Mitglieder", zweitaccount: "Zweitaccounts (Eltern)", freiwillig: "Freiwillige", unbekannt: "Unbekannte", unklassifiziert: "Unklassifiziert" };
  $("b-wer-bars").innerHTML = geladen ? reihenfolge.filter((t) => t in wer || t !== "unklassifiziert").map((t) => {
    const v = wer[t] || 0, p = total ? v / total : 0;
    const cls = t === "unbekannt" && v > 0 ? "lo" : "n";
    return `<div class="gbar"><span>${labels[t]}</span><span class="track"><span class="fill ${cls}" style="width:${Math.round(p * 100)}%"></span></span><span class="val">${v} · ${Math.round(p * 100)} %</span></div>`;
  }).join("") + (wer.unbekannt ? `<div class="hintline">Unbekannte sollten 0 Einsätze haben — Umteilung siehe Datenqualität.</div>` : "") : `<div class="empty">Noch keine Daten.</div>`;
  // Säumige
  const saeumige = d.mitglieder.filter((m) => statusVon(m) === "saeumig").sort((a, b) => vergleich(a.name, b.name));
  $("b-saeumige-sub").textContent = S.sicht === "saison"
    ? `${saeumige.length} Mitglieder ohne Einsatz. Vollständige Liste über «Säumigen-CSV».`
    : `${saeumige.length} Mitglieder unter dem Halbjahresziel. Vollständige Liste über «Säumigen-CSV».`;
  $("b-saeumige-body").innerHTML = saeumige.length ? saeumige.slice(0, 15).map((m) => `
    <tr><td><span class="name">${esc(m.name)}</span> <span class="fgtag">${esc(m.fg)}</span></td><td class="sub">${esc(m.gruppen.join(", "))}</td>
    <td class="r num">${fmt(m.soll)}</td><td class="r num">${fmt(m.ist)}</td><td class="sub">${m.accounts.length > 1 ? `${m.accounts.length} verknüpft` : "1"}</td></tr>`).join("")
    + (saeumige.length > 15 ? `<tr><td colspan="5" class="sub">… und ${saeumige.length - 15} weitere — siehe CSV.</td></tr>` : "")
    : `<tr><td colspan="5" class="sub">${geladen ? "Niemand säumig — alle im Soll." : "Noch keine Daten."}</td></tr>`;
}

// ------------------------------------------------------------------ Abgleich ----
async function fairgateHochladen(datei) {
  if (!datei) return;
  const dz = $("dropzone");
  dz.innerHTML = ic("refresh", "spin") + `<br>Wird geprüft: <b>${esc(datei.name)}</b> …`;
  try {
    const d = await holeJson("/api/fairgate", { method: "POST", body: await datei.arrayBuffer() });
    zeigeFehler("fairgate", null);
    dz.innerHTML = ic("check") + `<br><b>${esc(datei.name)}</b> geladen · ${esc(String(d.geprueft ?? ""))}<span class="hint">Andere Datei: klicken oder hierher ziehen</span>`;
    renderAbgleich(d);
    const offen = d.handarbeit.length + d.klaerliste.length + d.duplikat_warnungen.length;
    $("nav-n-abgleich").textContent = offen || "";
    toast("Abgleich abgeschlossen — " + d.zusammenfassung);
    ladeProtokoll(); ladeStand();
  } catch (e) {
    zeigeFehler("fairgate", e.message);
    dz.innerHTML = ic("alert") + `<br><b>Datei abgewiesen.</b><span class="hint">${esc(e.message)}</span><span class="hint">Andere Datei: klicken oder hierher ziehen</span>`;
  }
}
function renderAbgleich(d) {
  const imp = basename(d.dateien.import), liste = basename(d.dateien.liste);
  const nImport = d.neueintritte + d.korrekturen;
  const warn = [
    ...(d.unbekannte_kategorien || []).map((w) => ({ t: w, k: "Unbekannte Kategorie" })),
    ...(d.duplikat_warnungen || []).map((w) => ({ t: w, k: "Duplikat-Warnung" })),
  ];
  $("abgleich-ergebnis").innerHTML = `
    <p class="lead"><b>${esc(d.zusammenfassung)}</b></p>
    <div class="artifacts">
      <div class="artifact"><div class="count num">${d.handarbeit.length}</div><h3>Handarbeits-Liste</h3>
        <p>Zuerst im Portal von Hand erledigen: Schlüssel-Änderungen, Austritte, Feld-Leerungen. Abhakbar und druckbar.</p>
        <div class="row"><a class="btn" href="${ausgabeLink(liste)}" target="_blank" rel="noopener">${ic("file")}Öffnen</a></div></div>
      <div class="artifact"><div class="count num">${nImport}</div><h3>Import-Datei</h3>
        <p>Danach im Portal hochladen (Helfende → Import): ${d.neueintritte} Neueintritte, ${d.korrekturen} Korrekturen. Leere Zellen überschreiben nichts.</p>
        <div class="row"><a class="btn" href="${ausgabeLink(imp)}">${ic("download")}${esc(imp)}</a></div></div>
      <div class="artifact"><div class="count num">${d.klaerliste.length}</div><h3>Klärliste</h3>
        <p>In Fairgate nachtragen (fehlende E-Mail, belegtes Bemerkungsfeld u. ä.). Steht auch in der Handarbeits-Liste.</p>
        ${d.klaerliste.length ? `<ul class="warnlist">${d.klaerliste.slice(0, 5).map((t) => `<li>${ic("info", "sm")}<span>${esc(t)}</span></li>`).join("")}${d.klaerliste.length > 5 ? `<li class="sub">… ${d.klaerliste.length - 5} weitere in der Liste</li>` : ""}</ul>` : ""}</div>
    </div>
    ${warn.length ? `<ul class="warnlist">${warn.map((w) => `<li>${ic("alert", "sm")}<span><b>${esc(w.k)}:</b> ${esc(w.t)}</span></li>`).join("")}</ul>` : ""}
    <p class="hintline">Reihenfolge ist Pflicht: erst die Handarbeits-Liste abarbeiten, dann die Import-Datei hochladen — sonst entstehen Duplikate. Dateien liegen im Ordner «Ausgabe».</p>`;
}

// ------------------------------------------------------------------ Datenqualität ----
function renderDQ() {
  const d = S.daten, el = $("dq-gruppen");
  $("dq-meta").textContent = d.hinweise.length ? `${d.hinweise.length} offene Hinweise · Stand ${d.stand}` : (d.mitglieder.length ? "Keine Hinweise — Datenbestand sauber." : "Wird bei jedem Abruf geprüft");
  if (!d.hinweise.length) { el.innerHTML = `<div class="card"><div class="empty"><b>${d.mitglieder.length ? "Alles sauber" : "Noch keine Daten"}</b>${d.mitglieder.length ? "Keine Regelverstösse im aktuellen Bestand." : "Nach dem ersten Abruf erscheinen hier die Prüfergebnisse."}</div></div>`; return; }
  const gruppen = ["kritisch", "warnung", "hinweis"].map((s) => ({ s, liste: d.hinweise.filter((h) => h.schweregrad === s) })).filter((g) => g.liste.length);
  el.innerHTML = gruppen.map((g) => `
    <div class="dqgroup"><h2><span class="dot" style="background:${SCHWERE[g.s].farbe}"></span>${SCHWERE[g.s].titel} <span class="sub">· ${g.liste.length}</span></h2>
      ${g.liste.map((h) => `<div class="card dqcard ${SCHWERE[g.s].cls}"><span class="code ${SCHWERE[g.s].cls}">${esc(h.code)}</span><div class="text">${esc(h.text)}</div>
        ${h.betroffene.length ? `<div class="betroffene">${h.betroffene.map(betroffenChip).join("")}</div>` : ""}</div>`).join("")}
    </div>`).join("");
}
function betroffenChip(b) {
  const d = S.daten;
  const fgMatch = String(b).match(/FG-\d+/);
  const name = nameAus(b);
  let m = null;
  if (fgMatch) m = d.mitglieder.find((x) => x.fg === fgMatch[0]);
  if (!m) m = d.mitglieder.find((x) => x.name === name || x.accounts.some((a) => a.name === name));
  if (m) return `<button class="pchip" data-fg="${esc(m.fg)}" title="Im Kontingent anzeigen">${ic("chev", "sm")}${esc(b)}</button>`;
  const a = d.alle_accounts.find((x) => x.name === name);
  if (a) return `<button class="pchip" data-id="${a.id}" data-name="${esc(a.name)}" title="Bei allen Helfenden anzeigen">${ic("users", "sm")}${esc(b)}</button>`;
  return `<span class="pchip static">${esc(b)}</span>`;
}

// ------------------------------------------------------------------ Regeln ----
function befuelleRegeln() {
  const r = S.regeln; if (!r) return;
  $("regeln-kategorien").innerHTML = r.kategorien.map(kategorieZeile).join("");
  $("regel-altersgrenze").value = r.altersgrenze;
  $("regel-halbjahr").value = r.halbjahresziel;
  setSicht(S.sicht);
}
function kategorieZeile(k = { name: "", pflichtig: true, zielwert: 2, portal_gruppe: "Mitglied" }) {
  return `<tr>
    <td><input type="text" class="k-name" value="${esc(k.name)}" placeholder="z. B. Aktivmitglied"></td>
    <td><input type="checkbox" class="k-pflichtig" ${k.pflichtig ? "checked" : ""}></td>
    <td><input type="number" class="k-ziel" value="${Number(k.zielwert) || 0}" min="0" max="50"></td>
    <td><input type="text" class="k-gruppe" value="${esc(k.portal_gruppe)}" placeholder="Mitglied"></td>
    <td><button class="btn ghost icon k-del" title="Zeile entfernen" aria-label="Zeile entfernen">${ic("x")}</button></td></tr>`;
}
async function speichereRegeln() {
  const kategorien = [...document.querySelectorAll("#regeln-kategorien tr")].map((tr) => ({
    name: tr.querySelector(".k-name").value.trim(),
    pflichtig: tr.querySelector(".k-pflichtig").checked,
    zielwert: Number(tr.querySelector(".k-ziel").value) || 0,
    portal_gruppe: tr.querySelector(".k-gruppe").value.trim(),
  })).filter((k) => k.name);
  const body = { kategorien, altersgrenze: Number($("regel-altersgrenze").value) || 16, halbjahresziel: Number($("regel-halbjahr").value) || 1 };
  try {
    await holeJson("/api/regeln", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    zeigeFehler("regeln-speichern", null);
    toast("Regeln gespeichert.");
    await ladeRegeln(); await ladeStand();
  } catch (e) { zeigeFehler("regeln-speichern", e.message); }
}

// ------------------------------------------------------------------ Protokoll ----
function formatZeit(iso) {
  const d = new Date(iso); if (isNaN(d)) return esc(iso);
  return d.toLocaleDateString("de-CH", { day: "2-digit", month: "2-digit", year: "numeric" }) + " " + d.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
}
function beschreibe(e) {
  const dateien = (e.dateien || []).map((f) => `<a href="${ausgabeLink(f)}" target="_blank" rel="noopener">${esc(f)}</a>`).join(", ");
  switch (e.aktion) {
    case "api-abruf": return { a: "API-Abruf", d: `${e.accounts} Accounts${e.hinweise != null ? ` · ${e.hinweise} Hinweise` : ""}` };
    case "abgleich": return { a: "Quartals-Abgleich", d: `${e.geprueft} geprüft · ${e.neueintritte} Neueintritte · ${e.korrekturen} Korrekturen · ${e.handarbeit} Handarbeit${dateien ? " · " + dateien : ""}` };
    case "saeumigen-csv": return { a: "Säumigen-CSV", d: `${e.anzahl} Einträge (${e.sicht === "halbjahr" ? "Halbjahresziel" : "Saison-Soll"})${dateien ? " · " + dateien : ""}` };
    case "gesamtexport": return { a: "Excel-Gesamtexport", d: `${e.anzahl} Mitglieder${dateien ? " · " + dateien : ""}` };
    default: return { a: esc(e.aktion), d: dateien };
  }
}
function renderProtokoll(liste) {
  const el = $("protokoll-liste");
  if (!liste.length) { el.innerHTML = `<li><div class="empty" style="grid-column:1/-1"><b>Noch keine Einträge</b>Abrufe, Abgleiche und Exporte erscheinen hier chronologisch.</div></li>`; return; }
  el.innerHTML = liste.map((e) => { const b = beschreibe(e); return `<li><span class="z">${formatZeit(e.zeit)}</span><div><div class="a">${b.a}</div><div class="d">${b.d}</div></div></li>`; }).join("");
}

// ------------------------------------------------------------------ Exporte ----
async function saeumigenCsv() {
  try {
    const d = await holeJson(`/api/export/saeumige?sicht=${encodeURIComponent(S.sicht)}`, { method: "POST" });
    zeigeFehler("saeumigen-csv", null);
    toast(`Säumigen-CSV erstellt: ${d.anzahl} Einträge.`, { href: ausgabeLink(d.datei), text: basename(d.datei) });
    ladeProtokoll();
  } catch (e) { zeigeFehler("saeumigen-csv", e.message); }
}
async function gesamtexport() {
  try {
    const d = await holeJson("/api/export/gesamt", { method: "POST" });
    zeigeFehler("gesamtexport", null);
    toast(`Excel-Gesamtexport erstellt: ${d.anzahl} Mitglieder, drei Blätter.`, { href: ausgabeLink(d.datei), text: basename(d.datei) });
    ladeProtokoll();
  } catch (e) { zeigeFehler("gesamtexport", e.message); }
}

// ------------------------------------------------------------------ Start ----
document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".navitem").forEach((b) => b.addEventListener("click", () => zeigePanel(b.dataset.panel)));
  $("btn-abrufen").addEventListener("click", abrufen);
  document.querySelectorAll(".seg [data-sicht]").forEach((b) => b.addEventListener("click", () => setSicht(b.dataset.sicht)));

  // Kontingent: Chips, Suche, Sortierung, Zeilen
  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => c.addEventListener("click", () => {
    S.k.filter = c.dataset.filter;
    document.querySelectorAll("#chips-kontingent .chip").forEach((x) => x.setAttribute("aria-pressed", String(x === c)));
    renderTabelleK();
  }));
  $("suche-kontingent").addEventListener("input", (e) => { S.k.suche = e.target.value; renderTabelleK(); });
  bindeSort("tab-mitglieder", S.k.sort, renderTabelleK);
  $("tab-mitglieder-body").addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const tr = e.target.closest("tr.row"); if (tr) toggleZeile(tr.dataset.fg);
  });
  $("tab-mitglieder-body").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr.row");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggleZeile(tr.dataset.fg); }
  });
  $("btn-saeumige-csv").addEventListener("click", saeumigenCsv);
  $("btn-saeumige-csv-2").addEventListener("click", saeumigenCsv);
  $("btn-gesamtexport").addEventListener("click", gesamtexport);
  $("btn-gesamtexport-2").addEventListener("click", gesamtexport);
  ["btn-print-kontingent", "btn-print-helfende", "btn-print-bericht"].forEach((id) => $(id).addEventListener("click", () => window.print()));

  // Alle Helfenden
  document.querySelectorAll("#chips-helfende .chip").forEach((c) => c.addEventListener("click", () => {
    S.h.filter = c.dataset.typ;
    document.querySelectorAll("#chips-helfende .chip").forEach((x) => x.setAttribute("aria-pressed", String(x === c)));
    renderTabelleH();
  }));
  $("suche-helfende").addEventListener("input", (e) => { S.h.suche = e.target.value; renderTabelleH(); });
  bindeSort("tab-helfende", S.h.sort, renderTabelleH);

  // Datenqualität: Sprungmarken
  $("dq-gruppen").addEventListener("click", (e) => {
    const b = e.target.closest("button.pchip"); if (!b) return;
    if (b.dataset.fg) springeZuMitglied(b.dataset.fg); else if (b.dataset.id) springeZuHelfer(b.dataset.id, b.dataset.name);
  });

  // Abgleich: Drop-Zone
  const dz = $("dropzone"), input = $("datei-input");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => fairgateHochladen(e.dataTransfer.files[0]));
  input.addEventListener("change", () => { fairgateHochladen(input.files[0]); input.value = ""; });

  // Regeln
  $("btn-kategorie-plus").addEventListener("click", () => $("regeln-kategorien").insertAdjacentHTML("beforeend", kategorieZeile()));
  $("regeln-kategorien").addEventListener("click", (e) => { const b = e.target.closest(".k-del"); if (b) b.closest("tr").remove(); });
  $("btn-regeln-speichern").addEventListener("click", speichereRegeln);

  // Start: jeder Schritt fängt seine Fehler selbst (Startkette bricht nie still ab)
  try { setSicht("saison"); } catch (e) { zeigeFehler("start-sicht", e.message); }
  await ladeRegeln();
  await ladeStand();
  await ladeProtokoll();
});
