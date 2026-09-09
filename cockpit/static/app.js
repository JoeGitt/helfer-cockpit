// Helfer-Cockpit 2 — Frontend. Läuft ausschliesslich gegen 127.0.0.1, ohne Framework,
// ohne CDN. Alle Daten kommen per fetch() von der lokalen JSON-API (cockpit/webapp.py).
"use strict";

// ------------------------------------------------------------------ Zustand ----
const S = {
  sicht: "saison", daten: null, regeln: null,
  k: { filter: "alle", suche: "", sort: { key: "status", dir: "asc" }, offen: new Set() },
  h: { filter: "alle", suche: "", sort: { key: "name", dir: "asc" } },
};
// Geführter Abgleich: step 0 = Start, 1–4 = Schritte, 5 = fertig. checks = abgehakte Punkte
// (nur Schlüssel wie "h:3", keine Personendaten) — bleiben im Browser-Speicher erhalten.
const W = { step: 0, abgleich: null, checks: {}, ack: false, runId: null, dateiName: "" };
const WIZ_KEY = "hc2-abgleich";

const TYP_LABEL = { mitglied: "Mitglied", zweitaccount: "Zweitaccount", freiwillig: "Freiwillig",
                    unbekannt: "Unbekannt", unklassifiziert: "Ohne Zuordnung" };
const STATUS = {
  erfuellt: { label: "Erfüllt", cls: "ok", rang: 2 },
  auf_kurs: { label: "Auf Kurs", cls: "warn", rang: 1 },
  saeumig:  { label: "Säumig", cls: "crit", rang: 0 },
};
const SCHWERE = {
  kritisch: { titel: "Kritisch — vor dem Abgleich bereinigen", cls: "crit", farbe: "var(--red)" },
  warnung:  { titel: "Warnung — im Abgleich oder danach", cls: "warn", farbe: "var(--warn)" },
  hinweis:  { titel: "Hinweis — zur Kenntnis", cls: "info", farbe: "var(--info)" },
};
const ART_LABEL = { schluessel: "E-Mail im Portal nachführen", austritt: "Im Portal deaktivieren", leerung: "Feld im Portal leeren" };

// ------------------------------------------------------------------ Helfer ----
const $ = (id) => document.getElementById(id);
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function fmt(n) { n = Number(n) || 0; return Number.isInteger(n) ? String(n) : n.toFixed(1).replace(".", ","); }
function ic(name, cls = "") { return `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`; }
function basename(p) { return String(p || "").split(/[\\/]/).pop(); }
function ausgabeLink(pfad) { return "/ausgabe/" + encodeURIComponent(basename(pfad)); }
function vergleich(a, b) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a ?? "").localeCompare(String(b ?? ""), "de", { sensitivity: "base", numeric: true });
}
function formatZeit(iso) {
  const d = new Date(iso); if (isNaN(d)) return esc(iso);
  return d.toLocaleDateString("de-CH", { day: "2-digit", month: "2-digit", year: "numeric" }) + " " + d.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
}
function plink(url, text = "Portal") { return url ? `<a class="plink" href="${esc(url)}" target="_blank" rel="noopener" title="Im Helferportal öffnen">${ic("external", "sm")}${esc(text)}</a>` : ""; }

const fehlerQuellen = new Map();
function zeigeFehler(quelle, msg) {
  if (msg) fehlerQuellen.set(quelle, msg); else fehlerQuellen.delete(quelle);
  $("fehler-text").textContent = [...fehlerQuellen.values()].join("  ·  ");
  $("fehler-banner").hidden = fehlerQuellen.size === 0;
}
let toastTimer = null;
function toast(msg, link) {
  const el = $("toast");
  el.innerHTML = ic("check") + `<span>${esc(msg)}</span>` + (link ? ` <a href="${esc(link.href)}" target="_blank" rel="noopener">${esc(link.text)}</a>` : "");
  el.hidden = false; clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, link ? 12000 : 5000);
}
async function holeJson(url, optionen) {
  let r;
  try { r = await fetch(url, optionen); } catch (e) { throw new Error(`Server nicht erreichbar (${url}) — läuft das Cockpit noch?`); }
  let daten = null; try { daten = await r.json(); } catch (e) { daten = null; }
  if (!r.ok) throw new Error((daten && daten.fehler) || `Serverfehler ${r.status} bei ${url}.`);
  return daten;
}

// ------------------------------------------------------------------ Navigation ----
function zeigePanel(id) {
  document.querySelectorAll(".navitem, #btn-einstellungen").forEach((b) => {
    if (b.dataset.panel === id) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  document.querySelectorAll("section.panel").forEach((p) => p.classList.toggle("active", p.id === id));
  window.scrollTo({ top: 0 });
}
function zeigeSub(id) {
  document.querySelectorAll(".subtabs [data-sub]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sub === id)));
  document.querySelectorAll(".subpanel").forEach((p) => p.classList.toggle("active", p.id === id));
}

// ------------------------------------------------------------------ Laden ----
async function ladeStand() {
  try { anwenden(await holeJson("/api/stand")); zeigeFehler("stand-transport", null); return true; }
  catch (e) { zeigeFehler("stand-transport", e.message); return false; }
}
let abrufLaeuft = false;
async function abrufen(still = false) {
  if (abrufLaeuft) return false;
  abrufLaeuft = true;
  const btn = $("btn-abrufen");
  btn.disabled = true; btn.querySelector(".ic").classList.add("spin"); btn.querySelector("span").textContent = "Holt …";
  let ok = false;
  try {
    const d = await holeJson("/api/abruf", { method: "POST" });
    anwenden(d); zeigeFehler("abruf-transport", null);
    ok = !d.fehler;
    if (ok && !still) toast(`Abgerufen: ${d.alle_accounts.length} Accounts, ${d.mitglieder.length} Mitglieder.`);
    ladeProtokoll();
  } catch (e) { zeigeFehler("abruf-transport", e.message); }
  finally { abrufLaeuft = false; btn.disabled = false; btn.querySelector(".ic").classList.remove("spin"); btn.querySelector("span").textContent = "Neu abrufen"; }
  return ok;
}
async function ladeRegeln() {
  try { S.regeln = await holeJson("/api/regeln"); befuelleRegeln(); zeigeFehler("regeln-transport", null); }
  catch (e) { zeigeFehler("regeln-transport", e.message); }
}
async function ladeProtokoll() {
  try { renderProtokoll(await holeJson("/api/protokoll")); zeigeFehler("protokoll-transport", null); }
  catch (e) { zeigeFehler("protokoll-transport", e.message); }
}
function geladen() { return !!(S.daten && (S.daten.mitglieder.length || S.daten.alle_accounts.length)); }

function anwenden(d) {
  S.daten = d;
  zeigeFehler("stand", d.fehler || null);
  const g = geladen();
  $("stand-anzeige").textContent = g ? `${d.alle_accounts.length} Accounts · Stand ${d.stand}` : "Noch nicht abgerufen";
  $("nav-n-kontingent").textContent = g ? d.mitglieder.length : "";
  $("nav-n-helfende").textContent = g ? d.alle_accounts.length : "";
  const kritisch = d.hinweise.filter((h) => h.schweregrad === "kritisch").length;
  const nAb = $("nav-n-abgleich");
  nAb.textContent = kritisch || ""; nAb.className = "n num " + (kritisch ? "crit" : "");
  $("sub-n-dq").textContent = d.hinweise.length ? `· ${d.hinweise.length}` : "";
  renderKennzahlen(); renderTabelleK(); renderTabelleH(); renderBericht(); renderDQ($("dq-gruppen"), $("dq-meta"));
  renderWizardStart();
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
  const d = S.daten, k = d.kennzahlen, n = d.mitglieder.length, g = n > 0;
  const of = (x) => `${fmt(x)}<span class="of">/ ${n}</span>`;
  $("kpi-erfuellt").innerHTML = g ? of(k.erfuellt) : "–";
  $("kpi-erfuellt-h").textContent = g ? `${Math.round(k.erfuellt / n * 100)} % der Mitglieder` : "";
  $("kpi-halbjahr").innerHTML = g ? of(k.halbjahr_erreicht) : "–";
  $("kpi-halbjahr-h").textContent = g ? `mind. ${S.regeln ? S.regeln.halbjahresziel : 1} Einsatz bis Halbjahr` : "";
  $("kpi-ohne").textContent = g ? fmt(k.ohne_einsatz) : "–";
  $("kpi-istsoll").innerHTML = g ? `${fmt(k.ist_summe)}<span class="of">/ ${fmt(k.soll_summe)}</span>` : "–";
  $("kpi-zweit").textContent = g ? fmt(k.zweitaccounts) : "–";
  const z = { alle: n, erfuellt: 0, auf_kurs: 0, saeumig: 0, zweitaccount: 0 };
  d.mitglieder.forEach((m) => { z[statusVon(m)]++; if (m.accounts.length > 1) z.zweitaccount++; });
  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => { c.querySelector(".c").textContent = z[c.dataset.filter] ?? 0; });
}
function gefilterteMitglieder() {
  const f = S.k.filter, q = S.k.suche.trim().toLowerCase();
  const liste = S.daten.mitglieder.filter((m) => {
    if (f === "zweitaccount" && m.accounts.length < 2) return false;
    if (f !== "alle" && f !== "zweitaccount" && statusVon(m) !== f) return false;
    if (q && !(m.name.toLowerCase().includes(q) || m.fg.toLowerCase().includes(q) || m.accounts.some((a) => a.name.toLowerCase().includes(q)))) return false;
    return true;
  });
  const { key, dir } = S.k.sort;
  const wert = (m) => ({ name: m.name, gruppen: m.gruppen.join(", "), accounts: m.accounts.length, soll: m.soll, ist: m.ist, status: STATUS[statusVon(m)].rang })[key];
  liste.sort((a, b) => (vergleich(wert(a), wert(b)) || vergleich(a.name, b.name)) * (dir === "asc" ? 1 : -1));
  return liste;
}
function nameAus(betroffen) { return String(betroffen).split(/ \(|: |«/)[0].trim(); }
function hinweiseZu(m) {
  const namen = new Set(m.accounts.map((a) => a.name));
  return (S.daten.hinweise || []).filter((h) => h.betroffene.some((b) => b === m.fg || b.includes(m.fg) || namen.has(nameAus(b))));
}
function renderTabelleK() {
  const liste = gefilterteMitglieder(), body = $("tab-mitglieder-body"), n = S.daten.mitglieder.length;
  if (!n) { body.innerHTML = `<tr><td colspan="7"><div class="empty"><b>Noch keine Daten</b>Der Portal-Bestand wird beim Start automatisch geholt — sonst links «Neu abrufen».</div></td></tr>`; $("tfoot-kontingent").textContent = ""; return; }
  body.innerHTML = liste.length ? liste.map(zeileK).join("") : `<tr><td colspan="7"><div class="empty"><b>Kein Treffer</b>Filter oder Suchbegriff anpassen.</div></td></tr>`;
  const sortName = { name: "Name", gruppen: "Gruppen", accounts: "Accounts", soll: "Soll", ist: "Ist", status: "Status" }[S.k.sort.key];
  $("tfoot-kontingent").innerHTML = `<span>${liste.length} von ${n} Mitgliedern</span><span>· sortiert nach ${sortName}</span><span style="margin-left:auto">Zusammenführung ausschliesslich über FG-Nummer</span>`;
  markiereSort("tab-mitglieder", S.k.sort);
}
function zeileK(m) {
  const offen = S.k.offen.has(m.fg), mehrere = m.accounts.length > 1;
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
    <td class="sub">${esc(a.bemerkung) || "—"}</td><td>${plink(a.portal_url)}</td></tr>`).join("");
  const hinweise = hinweiseZu(m);
  const dq = hinweise.length ? `<div class="dq">${hinweise.map((h) => `<div><span class="code ${SCHWERE[h.schweregrad].cls}">${esc(h.code)}</span><span>${esc(h.text)}</span></div>`).join("")}</div>` : "";
  const sum = `Ist ${fmt(m.ist)} ${m.accounts.length > 1 ? "= " + m.accounts.map((a) => fmt(a.ist)).join(" + ") : ""} · Ziel ${fmt(zielVon(m))} (${S.sicht === "saison" ? "Saison-Soll" : "Halbjahresziel"})`;
  return `<div class="ledger"><table><thead><tr><th>Account</th><th>Typ</th><th class="r">Ist</th><th class="r">Soll</th><th class="r" title="Geleistet / Zugesagt / Nicht erschienen">OK / Zug. / NOK</th><th>Bemerkung</th><th></th></tr></thead><tbody>${zeilen}</tbody></table><div class="sum num">${esc(sum)}</div>${dq}</div>`;
}
function toggleZeile(fg) { if (S.k.offen.has(fg)) S.k.offen.delete(fg); else S.k.offen.add(fg); renderTabelleK(); }
function springeZuMitglied(fg) {
  S.k.filter = "alle"; S.k.suche = ""; $("suche-kontingent").value = "";
  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.filter === "alle")));
  S.k.offen.add(fg); zeigePanel("p-kontingent"); renderTabelleK();
  const tr = document.querySelector(`#tab-mitglieder-body tr.row[data-fg="${CSS.escape(fg)}"]`);
  if (tr) { tr.scrollIntoView({ block: "center" }); tr.classList.add("flash"); tr.focus(); }
}

// ------------------------------------------------------------------ Alle Helfenden ----
function gefilterteAccounts() {
  const f = S.h.filter, q = S.h.suche.trim().toLowerCase();
  const liste = S.daten.alle_accounts.filter((a) => {
    if (f === "aktiv" && !(a.num_ok + a.num_confirmed > 0)) return false;
    if (f !== "alle" && f !== "aktiv" && a.typ !== f) return false;
    if (q && !(a.name.toLowerCase().includes(q) || (a.fg || "").toLowerCase().includes(q) || a.gruppen.join(", ").toLowerCase().includes(q))) return false;
    return true;
  });
  const { key, dir } = S.h.sort;
  const wert = (a) => key === "gruppen" ? a.gruppen.join(", ") : key === "typ" ? (TYP_LABEL[a.typ] || a.typ) : a[key];
  liste.sort((a, b) => (vergleich(wert(a), wert(b)) || vergleich(a.name, b.name)) * (dir === "asc" ? 1 : -1));
  return liste;
}
function renderTabelleH() {
  const alle = S.daten.alle_accounts, z = { alle: alle.length, aktiv: 0 };
  alle.forEach((a) => { z[a.typ] = (z[a.typ] || 0) + 1; if (a.num_ok + a.num_confirmed > 0) z.aktiv++; });
  document.querySelectorAll("#chips-helfende .chip").forEach((c) => { const t = c.dataset.typ; c.querySelector(".c").textContent = z[t] || 0; if (t === "unklassifiziert") c.hidden = !z[t]; });
  const liste = gefilterteAccounts(), body = $("tab-helfende-body");
  if (!alle.length) { body.innerHTML = `<tr><td colspan="8"><div class="empty"><b>Noch keine Daten</b>Der Portal-Bestand wird beim Start automatisch geholt.</div></td></tr>`; $("tfoot-helfende").textContent = ""; return; }
  body.innerHTML = liste.length ? liste.map((a) => `
    <tr data-id="${a.id}">
      <td><span class="name">${esc(a.name)}</span> ${a.fg ? `<span class="fgtag">${esc(a.fg)}</span>` : ""}</td>
      <td><span class="typ ${esc(a.typ)}">${TYP_LABEL[a.typ] || esc(a.typ)}</span></td>
      <td class="sub">${esc(a.gruppen.join(", "))}</td>
      <td class="r num"><b>${a.num_ok}</b></td><td class="r num">${a.num_confirmed}</td>
      <td class="r num">${a.num_nok ? `<span style="color:var(--red-ink);font-weight:600">${a.num_nok}</span>` : "0"}</td>
      <td class="r num sub">${fmt(a.ist_wert)}${a.zielwert ? ` / ${fmt(a.zielwert)}` : ""}</td>
      <td>${plink(a.portal_url, "Öffnen")}</td></tr>`).join("")
    : `<tr><td colspan="8"><div class="empty"><b>Kein Treffer</b>Filter oder Suchbegriff anpassen.</div></td></tr>`;
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
  const d = S.daten, k = d.kennzahlen, n = d.mitglieder.length, g = n > 0;
  $("b-stand").textContent = g ? `Stand ${d.stand}` : "";
  const pct = g && k.soll_summe > 0 ? Math.round(k.ist_summe / k.soll_summe * 100) : 0;
  $("b-pct").textContent = g ? `${pct} %` : "–";
  $("b-ring-fill").setAttribute("stroke-dasharray", `${(Math.min(pct, 100) / 100 * 263.9).toFixed(1)} 263.9`);
  $("b-ring-fill").setAttribute("stroke", pct >= 100 ? "var(--ok)" : "var(--red)");
  $("b-sub").innerHTML = g ? `${fmt(k.ist_summe)} geleistete von ${fmt(k.soll_summe)} geforderten Einsätzen.<br>Zwischenziel Halbjahr: mind. ${S.regeln ? S.regeln.halbjahresziel : 1} Einsatz pro Mitglied.` : "Noch keine Daten abgerufen.";
  const of = (x) => `${fmt(x)}<span class="of">/ ${n}</span>`;
  $("b-erfuellt").innerHTML = g ? of(k.erfuellt) : "–"; $("b-halbjahr").innerHTML = g ? of(k.halbjahr_erreicht) : "–";
  $("b-ohne").textContent = g ? fmt(k.ohne_einsatz) : "–"; $("b-accounts").textContent = g ? d.alle_accounts.length : "–";
  $("b-zweit").textContent = g ? fmt(k.zweitaccounts) : "–"; $("b-konflikt").textContent = g ? d.mitglieder.filter((m) => m.soll_konflikt).length : "–";
  $("b-nok").textContent = g ? fmt(k.nok_summe) : "–"; $("b-dq").textContent = g ? d.hinweise.length : "–";
  const ke = d.kategorie_erfuellung || [];
  $("b-kategorie-card").hidden = ke.length === 0;
  if (ke.length) {
    const ges = ke.reduce((s, e) => s + e.gesamt, 0), err = ke.reduce((s, e) => s + e.erreicht, 0), schnitt = ges ? err / ges : 0;
    $("b-kategorie-bars").innerHTML = ke.map((e) => { const p = e.gesamt ? e.erreicht / e.gesamt : 0;
      return `<div class="gbar"><span>${esc(e.kategorie)}</span><span class="track"><span class="fill ${p < schnitt ? "lo" : ""}" style="width:${Math.round(p * 100)}%"></span></span><span class="val">${e.erreicht} / ${e.gesamt} · ${Math.round(p * 100)} %</span></div>`; }).join("")
      + `<div class="hintline">Vereinsschnitt: ${Math.round(schnitt * 100)} % der Mitglieder haben das Halbjahresziel erreicht.</div>`;
  }
  const wer = d.wer_leistet || {}, total = Object.values(wer).reduce((s, v) => s + v, 0);
  const labels = { mitglied: "Mitglieder", zweitaccount: "Zweitaccounts (Eltern)", freiwillig: "Freiwillige", unbekannt: "Unbekannte", unklassifiziert: "Ohne Zuordnung" };
  $("b-wer-bars").innerHTML = g ? ["mitglied", "zweitaccount", "freiwillig", "unbekannt", "unklassifiziert"].filter((t) => t in wer || t !== "unklassifiziert").map((t) => {
    const v = wer[t] || 0, p = total ? v / total : 0;
    return `<div class="gbar"><span>${labels[t]}</span><span class="track"><span class="fill ${t === "unbekannt" && v > 0 ? "lo" : "n"}" style="width:${Math.round(p * 100)}%"></span></span><span class="val">${v} · ${Math.round(p * 100)} %</span></div>`;
  }).join("") + (wer.unbekannt ? `<div class="hintline">Unbekannte sollten 0 Einsätze haben — Umteilung siehe Datenqualität (Einstellungen).</div>` : "") : `<div class="empty">Noch keine Daten.</div>`;
  const saeumige = d.mitglieder.filter((m) => statusVon(m) === "saeumig").sort((a, b) => vergleich(a.name, b.name));
  $("b-saeumige-sub").textContent = `${saeumige.length} Mitglieder ${S.sicht === "saison" ? "ohne Einsatz" : "unter dem Halbjahresziel"}. Vollständige Liste über «Säumigen-CSV».`;
  $("b-saeumige-body").innerHTML = saeumige.length ? saeumige.slice(0, 15).map((m) => `<tr><td><span class="name">${esc(m.name)}</span> <span class="fgtag">${esc(m.fg)}</span></td><td class="sub">${esc(m.gruppen.join(", "))}</td><td class="r num">${fmt(m.soll)}</td><td class="r num">${fmt(m.ist)}</td><td class="sub">${m.accounts.length > 1 ? `${m.accounts.length} verknüpft` : "1"}</td></tr>`).join("")
    + (saeumige.length > 15 ? `<tr><td colspan="5" class="sub">… und ${saeumige.length - 15} weitere — siehe CSV.</td></tr>` : "")
    : `<tr><td colspan="5" class="sub">${g ? "Niemand säumig — alle im Soll." : "Noch keine Daten."}</td></tr>`;
}

// ------------------------------------------------------------------ Datenqualität ----
function renderDQ(el, metaEl, nurKritisch = false) {
  const d = S.daten, hinweise = nurKritisch ? d.hinweise.filter((h) => h.schweregrad === "kritisch") : d.hinweise;
  if (metaEl) metaEl.textContent = d.hinweise.length ? `${d.hinweise.length} offene Hinweise · Stand ${d.stand}` : (geladen() ? "Keine Hinweise — Datenbestand sauber." : "Wird bei jedem Abruf geprüft.");
  if (!hinweise.length) { el.innerHTML = `<div class="card"><div class="empty"><b>${geladen() ? (nurKritisch ? "Keine kritischen Punkte" : "Alles sauber") : "Noch keine Daten"}</b>${geladen() ? "Nichts blockiert den Abgleich." : "Nach dem ersten Abruf erscheinen hier die Prüfergebnisse."}</div></div>`; return; }
  const gruppen = ["kritisch", "warnung", "hinweis"].map((s) => ({ s, liste: hinweise.filter((h) => h.schweregrad === s) })).filter((g) => g.liste.length);
  el.innerHTML = gruppen.map((g) => `
    <div class="dqgroup"><h2><span class="dot" style="background:${SCHWERE[g.s].farbe}"></span>${SCHWERE[g.s].titel} <span class="sub">· ${g.liste.length}</span></h2>
      ${g.liste.map((h) => `<div class="card dqcard ${SCHWERE[g.s].cls}"><span class="code ${SCHWERE[g.s].cls}">${esc(h.code)}</span><div class="text">${esc(h.text)}</div>
        ${h.betroffene.length ? `<div class="betroffene">${h.betroffene.slice(0, 40).map(betroffenChip).join("")}${h.betroffene.length > 40 ? `<span class="pchip static">… ${h.betroffene.length - 40} weitere</span>` : ""}</div>` : ""}</div>`).join("")}
    </div>`).join("");
}
function betroffenChip(b) {
  const d = S.daten, fgMatch = String(b).match(/FG-\d+/), name = nameAus(b);
  let m = null;
  if (fgMatch) m = d.mitglieder.find((x) => x.fg === fgMatch[0]);
  if (!m) m = d.mitglieder.find((x) => x.name === name || x.accounts.some((a) => a.name === name));
  if (m) return `<button class="pchip" data-fg="${esc(m.fg)}" title="Im Kontingent anzeigen">${ic("chev", "sm")}${esc(b)}</button>`;
  const a = d.alle_accounts.find((x) => x.name === name);
  if (a) return `<button class="pchip" data-id="${a.id}" data-name="${esc(a.name)}" title="Bei allen Helfenden anzeigen">${ic("users", "sm")}${esc(b)}</button>`;
  return `<span class="pchip static">${esc(b)}</span>`;
}
function bindeChips(container) {
  container.addEventListener("click", (e) => {
    const b = e.target.closest("button.pchip"); if (!b) return;
    if (b.dataset.fg) springeZuMitglied(b.dataset.fg); else if (b.dataset.id) springeZuHelfer(b.dataset.id, b.dataset.name);
  });
}

// ------------------------------------------------------------------ Geführter Abgleich ----
function wizSpeichern() {
  try { localStorage.setItem(WIZ_KEY, JSON.stringify({ runId: W.runId, step: W.step, checks: W.checks, ack: W.ack, dateiName: W.dateiName })); } catch (e) { /* Speicher optional */ }
}
function wizLaden() {
  try { const s = JSON.parse(localStorage.getItem(WIZ_KEY) || "null"); if (s && s.runId) { W.runId = s.runId; W.checks = s.checks || {}; W.ack = !!s.ack; W.dateiName = s.dateiName || ""; return s; } } catch (e) { /* ignorieren */ }
  return null;
}
function wizRunId(d) { return `${d.geprueft}|${d.zusammenfassung}|${basename((d.dateien || {}).import || "")}`; }

function wizZeige(step) {
  W.step = step; wizSpeichern();
  $("wiz-start").hidden = step !== 0;
  [1, 2, 3, 4].forEach((n) => { $(`wiz-${n}`).hidden = step !== n; });
  $("wiz-fertig").hidden = step !== 5;
  document.querySelectorAll("#wiz-steps li").forEach((li) => {
    const n = Number(li.dataset.step);
    li.dataset.state = step === 5 || n < step ? "fertig" : n === step ? "aktiv" : "offen";
  });
}
function renderWizardStart() {
  const d = S.daten, el = $("wiz-letzter");
  const l = d && d.letzter_abgleich;
  if (l) {
    el.innerHTML = `<span class="l">Letzter Abgleich</span><span class="num">${formatZeit(l.zeit)} — ${esc(l.zusammenfassung)}</span>
      <span class="l">Offen danach</span><span class="num">${l.handarbeit} Handarbeit · ${l.klaerliste} Klärfälle</span>`;
  } else {
    el.innerHTML = `<span class="l">Letzter Abgleich</span><span id="wiz-letzter-log">wird aus dem Verlauf gelesen …</span>`;
  }
}
function wizStartAusVerlauf(liste) {
  const el = $("wiz-letzter-log"); if (!el) return;
  const a = liste.find((e) => e.aktion === "abgleich");
  el.textContent = a ? `${formatZeit(a.zeit)} — ${a.geprueft} geprüft, ${a.neueintritte} Neueintritte, ${a.korrekturen} Korrekturen, ${a.handarbeit} Handarbeit` : "noch nie — heute ist ein guter Tag dafür";
}
async function wizStart() {
  wizZeige(1);
  const st = $("wiz-1-status");
  st.className = "statusline busy"; st.innerHTML = ic("refresh") + "<span>Portal-Bestand wird geholt …</span>";
  $("wiz-btn-1").disabled = true;
  let ok = geladen();
  if (S.daten && S.daten.api_verfuegbar) ok = await abrufen(true) || geladen();
  if (ok) {
    const d = S.daten, kritisch = d.hinweise.filter((h) => h.schweregrad === "kritisch").length;
    st.className = "statusline ok"; st.innerHTML = ic("check") + `<span><b>${d.alle_accounts.length} Accounts</b> geholt (${d.mitglieder.length} Mitglieder) · Stand ${esc(d.stand)}${kritisch ? ` · <b style="color:var(--red-ink)">${kritisch} kritische Punkte</b>` : " · keine kritischen Punkte"}</span>`;
    renderDQ($("wiz-1-dq"), null, true);
    const rest = d.hinweise.length - kritisch;
    if (rest) $("wiz-1-dq").insertAdjacentHTML("beforeend", `<details class="more"><summary>${rest} weitere Hinweise (Warnungen und Infos) — werden im Abgleich berücksichtigt</summary><div id="wiz-1-dq-rest" style="margin-top:8px"></div></details>`);
    if (rest) { const tmp = document.createElement("div"); const kopie = S.daten.hinweise; S.daten.hinweise = kopie.filter((h) => h.schweregrad !== "kritisch"); renderDQ(tmp, null, false); S.daten.hinweise = kopie; $("wiz-1-dq-rest").innerHTML = tmp.innerHTML; }
    $("wiz-btn-1").disabled = false;
  } else {
    st.className = "statusline err"; st.innerHTML = ic("alert") + "<span>Portal-Bestand konnte nicht geholt werden — siehe Meldung oben. Nochmals versuchen: links «Neu abrufen».</span>";
  }
}
async function fairgateHochladen(datei) {
  if (!datei) return;
  const dz = $("dropzone");
  dz.innerHTML = ic("refresh", "spin") + `<br>Wird geprüft: <b>${esc(datei.name)}</b> …`;
  $("wiz-btn-2").disabled = true; $("wiz-2-plausi").innerHTML = "";
  try {
    const d = await holeJson("/api/fairgate", { method: "POST", body: await datei.arrayBuffer() });
    zeigeFehler("fairgate", null);
    const neuerRun = wizRunId(d);
    if (W.runId !== neuerRun) { W.checks = {}; W.ack = false; }
    W.runId = neuerRun; W.abgleich = d; W.dateiName = datei.name; wizSpeichern();
    dz.innerHTML = ic("check") + `<br><b>${esc(datei.name)}</b> geladen<span class="hint">Andere Datei: klicken oder hierher ziehen</span>`;
    renderPlausi(d);
    ladeProtokoll(); ladeStand();
  } catch (e) {
    zeigeFehler("fairgate", e.message);
    dz.innerHTML = ic("alert") + `<br><b>Datei abgewiesen.</b><span class="hint">${esc(e.message)}</span><span class="hint">Andere Datei: klicken oder hierher ziehen</span>`;
  }
}
function renderPlausi(d) {
  const kat = d.kategorien || { pflichtig: {}, nicht_pflichtig: {}, unbekannt: {} };
  const pill = (t, cls = "") => `<span class="pill ${cls}">${t}</span>`;
  const teile = [pill(`${ic("users", "sm")}${d.geprueft} Kontakte`)];
  Object.entries(kat.pflichtig).forEach(([k, n]) => teile.push(pill(`${esc(k)}: ${n} pflichtig`)));
  Object.entries(kat.nicht_pflichtig).forEach(([k, n]) => teile.push(pill(`${esc(k)}: ${n} nicht pflichtig`)));
  const unbekannt = Object.entries(kat.unbekannt);
  unbekannt.forEach(([k, n]) => teile.push(pill(`${ic("alert", "sm")}${esc(k)}: ${n} — unbekannte Kategorie`, "bad")));
  let html = `<div class="plausi">${teile.join("")}</div>`;
  if (unbekannt.length) html += `<label class="ack"><input type="checkbox" id="wiz-ack" ${W.ack ? "checked" : ""}><span>Diese Kategorien stehen in keiner Regel und werden <b>nicht abgeglichen</b>. Wenn das Mitglieder sind, zuerst unter Einstellungen → Regeln ergänzen und den Export nochmals laden. Sonst hier bestätigen, dass das so gewollt ist.</span></label>`;
  $("wiz-2-plausi").innerHTML = html;
  const pruefe = () => { W.ack = !unbekannt.length || ($("wiz-ack") && $("wiz-ack").checked); $("wiz-btn-2").disabled = !W.ack; wizSpeichern(); };
  if ($("wiz-ack")) $("wiz-ack").addEventListener("change", pruefe);
  pruefe();
}
function clItem(key, titel, detail, aktionen = "") {
  const done = !!W.checks[key];
  return `<li class="${done ? "done" : ""}"><input type="checkbox" data-key="${esc(key)}" ${done ? "checked" : ""} aria-label="Erledigt: ${esc(titel)}"><div class="t"><b>${esc(titel)}</b>${detail ? `<span>${esc(detail)}</span>` : ""}</div><div class="a">${aktionen}</div></li>`;
}
function renderChecklist() {
  const d = W.abgleich; if (!d) return;
  $("wiz-3-lead").innerHTML = `<b>${esc(d.zusammenfassung)}</b> Reihenfolge ist Pflicht: erst die Punkte im Portal, dann die Import-Datei hochladen, dann Fairgate — sonst entstehen Duplikate.`;
  const reihenfolge = ["schluessel", "austritt", "leerung"];
  const hand = d.handarbeit.map((h, i) => ({ ...h, key: `h:${i}` })).sort((a, b) => reihenfolge.indexOf(a.art) - reihenfolge.indexOf(b.art));
  const warn = [...(d.duplikat_warnungen || []).map((t, i) => ({ key: `w:${i}`, t, k: "Duplikat-Warnung" })), ...(d.unbekannte_kategorien || []).map((t, i) => ({ key: `u:${i}`, t, k: "Unbekannte Kategorie" }))];
  const nImport = d.neueintritte + d.korrekturen, imp = basename(d.dateien.import), liste = basename(d.dateien.liste), kont = basename(d.dateien.kontakte || "");
  const sek = (titel, hint, items, cntOk) => `<div class="cl-section"><h3>${titel} <span class="cnt ${cntOk ? "ok" : ""}">${items.length ? `${items.filter((k) => W.checks[k]).length} / ${items.length}` : "nichts zu tun"}</span></h3>${hint ? `<p class="hint">${hint}</p>` : ""}</div>`;
  let html = "";
  // A · Portal
  const aKeys = [...hand.map((h) => h.key), ...warn.map((w) => w.key)];
  html += sek("A · Im Portal von Hand", `Jeder Punkt hat einen Link direkt zur Person. <a class="plink" href="${ausgabeLink(liste)}" target="_blank" rel="noopener">${ic("file", "sm")}Liste zum Drucken</a>`, aKeys, aKeys.every((k) => W.checks[k]));
  if (aKeys.length) html += `<ul class="checklist">${hand.map((h) => clItem(h.key, `${ART_LABEL[h.art] || h.art}: ${h.name} (${h.fg})`, h.detail, plink(h.portal_url, "Im Portal öffnen"))).join("")}${warn.map((w) => clItem(w.key, `${w.k} — von Hand prüfen`, w.t)).join("")}</ul>`;
  // B · Import
  const bKeys = nImport ? ["imp"] : [];
  html += sek("B · Import-Datei hochladen", nImport ? `Im Portal: <b>Helfende → Import</b>, Datei wählen, hochladen. Enthält ${d.neueintritte} Neueintritte und ${d.korrekturen} Korrekturen. Leere Zellen überschreiben nichts.` : "Keine Neueintritte oder Korrekturen — kein Import nötig.", bKeys, bKeys.every((k) => W.checks[k]));
  if (nImport) html += `<ul class="checklist">${clItem("imp", `Import-Datei im Portal hochgeladen (${nImport} Zeilen)`, "", `<a class="btn" href="${ausgabeLink(imp)}">${ic("download")}${esc(imp)}</a>`)}</ul>`;
  // C · Fairgate
  const cKeys = d.klaerliste.map((_, i) => `k:${i}`);
  html += sek("C · In Fairgate nachtragen", d.klaerliste.length ? "Diese Punkte kann nur Fairgate lösen — beim nächsten Abgleich rutschen sie automatisch nach." : "", cKeys, cKeys.every((k) => W.checks[k]));
  if (cKeys.length) html += `<ul class="checklist">${d.klaerliste.map((t, i) => clItem(`k:${i}`, t, "")).join("")}</ul>`;
  // Info
  const abw = d.kontakt_abweichungen || [];
  if (abw.length) html += `<details class="more"><summary>Info · ${abw.length} Kontaktdaten weichen ab (Portal ≠ Fairgate) — keine Handarbeit nötig</summary><p class="hint" style="margin:8px 0">Die Portal-Adresse ist die vom Mitglied selbst gewählte Login-Adresse. Falls Fairgate veraltet ist, dort nachführen: <a class="plink" href="${ausgabeLink(kont)}">${ic("download", "sm")}${esc(kont)}</a></p><ul class="checklist">${abw.slice(0, 50).map((a) => `<li><span></span><div class="t"><b>${esc(a.name)} (${esc(a.fg)})</b><span>Portal ${esc(a.portal_mail)} · Fairgate ${esc(a.fairgate_mail)}</span></div><div class="a">${plink(a.portal_url)}</div></li>`).join("")}</ul></details>`;
  $("wiz-3-liste").innerHTML = html;
  aktualisiereFortschritt();
}
function aktualisiereFortschritt() {
  const boxen = [...document.querySelectorAll("#wiz-3-liste input[data-key]")];
  const erledigt = boxen.filter((cb) => cb.checked).length;
  document.querySelectorAll("#wiz-3-liste .cl-section").forEach((sec) => {
    const ul = sec.nextElementSibling && sec.nextElementSibling.classList.contains("checklist") ? sec.nextElementSibling : null;
    const cnt = sec.querySelector(".cnt"); if (!cnt || !ul) return;
    const b = [...ul.querySelectorAll("input[data-key]")], d = b.filter((x) => x.checked).length;
    cnt.textContent = `${d} / ${b.length}`; cnt.classList.toggle("ok", d === b.length);
  });
  $("wiz-3-progress").style.width = boxen.length ? `${Math.round(erledigt / boxen.length * 100)}%` : "100%";
  $("wiz-3-progress-text").textContent = boxen.length ? `${erledigt} von ${boxen.length} Punkten erledigt` : "Nichts abzuarbeiten — direkt zur Kontrolle.";
  $("wiz-btn-3").disabled = erledigt < boxen.length;
}
async function wizKontrolle() {
  const el = $("wiz-4-ergebnis");
  el.innerHTML = `<div class="statusline busy">${ic("refresh")}<span>Portal-Bestand wird frisch geholt und verglichen …</span></div>`;
  try {
    const d = await holeJson("/api/abgleich/kontrolle", { method: "POST" });
    zeigeFehler("kontrolle", null);
    ladeStand(); ladeProtokoll();
    if (d.synchron) {
      $("wiz-fertig-text").textContent = `${d.zusammenfassung} Nächster Abgleich in rund drei Monaten — der Verlauf unter Einstellungen erinnert dich an das Datum.`;
      W.checks = {}; W.abgleich = null; W.runId = null; wizZeige(5);
      toast("Alles synchron — Abgleich abgeschlossen.");
    } else {
      const o = d.offen;
      el.innerHTML = `<div class="statusline err">${ic("alert")}<span><b>Noch nicht synchron:</b> ${o.handarbeit} Handarbeit · ${o.neueintritte} Neueintritte · ${o.korrekturen} Korrekturen · ${o.klaerliste} Klärfälle offen.</span></div>
        <p class="hint" style="margin:10px 0 0">Typische Gründe: Import-Datei noch nicht hochgeladen, ein Punkt im Portal noch nicht erledigt, oder das Portal braucht einen Moment. Die Checkliste wird mit dem aktuellen Stand neu aufgebaut — bereits Erledigtes bleibt abgehakt.</p>
        <div class="wiz-actions" style="margin-top:12px"><button class="btn primary" id="wiz-btn-nochmal">Checkliste aktualisieren</button><button class="btn" id="wiz-btn-kontrolle2">${ic("refresh")}Nochmals prüfen</button></div>`;
      $("wiz-btn-nochmal").addEventListener("click", () => { W.abgleich = { ...W.abgleich, ...d, dateien: W.abgleich.dateien }; renderChecklist(); wizZeige(3); });
      $("wiz-btn-kontrolle2").addEventListener("click", wizKontrolle);
    }
  } catch (e) {
    zeigeFehler("kontrolle", e.message);
    el.innerHTML = `<div class="statusline err">${ic("alert")}<span>${esc(e.message)}</span></div><div class="wiz-actions" style="margin-top:12px"><button class="btn primary" id="wiz-btn-kontrolle3">${ic("refresh")}Nochmals versuchen</button></div>`;
    $("wiz-btn-kontrolle3").addEventListener("click", wizKontrolle);
  }
}
function wizNeu() { W.checks = {}; W.abgleich = null; W.runId = null; W.ack = false; W.dateiName = ""; wizSpeichern(); $("wiz-2-plausi").innerHTML = ""; $("dropzone").innerHTML = `${ic("upload")}<br>Excel-Export aus Fairgate <b>hierher ziehen</b> oder klicken`; wizZeige(0); }

// ------------------------------------------------------------------ Regeln / Verlauf ----
function befuelleRegeln() {
  const r = S.regeln; if (!r) return;
  $("regeln-kategorien").innerHTML = r.kategorien.map(kategorieZeile).join("");
  $("regel-altersgrenze").value = r.altersgrenze; $("regel-halbjahr").value = r.halbjahresziel;
  $("regel-email").value = r.email_abweichung || "info";
  setSicht(S.sicht);
}
function kategorieZeile(k = { name: "", pflichtig: true, zielwert: 2, portal_gruppe: "Mitglied" }) {
  return `<tr><td><input type="text" class="k-name" value="${esc(k.name)}" placeholder="z. B. Aktivmitglied"></td><td><input type="checkbox" class="k-pflichtig" ${k.pflichtig ? "checked" : ""}></td><td><input type="number" class="k-ziel" value="${Number(k.zielwert) || 0}" min="0" max="50"></td><td><input type="text" class="k-gruppe" value="${esc(k.portal_gruppe)}" placeholder="Mitglied"></td><td><button class="btn ghost icon k-del" title="Zeile entfernen" aria-label="Zeile entfernen">${ic("x")}</button></td></tr>`;
}
async function speichereRegeln() {
  const kategorien = [...document.querySelectorAll("#regeln-kategorien tr")].map((tr) => ({
    name: tr.querySelector(".k-name").value.trim(), pflichtig: tr.querySelector(".k-pflichtig").checked,
    zielwert: Number(tr.querySelector(".k-ziel").value) || 0, portal_gruppe: tr.querySelector(".k-gruppe").value.trim(),
  })).filter((k) => k.name);
  const body = { kategorien, altersgrenze: Number($("regel-altersgrenze").value) || 16, halbjahresziel: Number($("regel-halbjahr").value) || 1, email_abweichung: $("regel-email").value };
  try {
    await holeJson("/api/regeln", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    zeigeFehler("regeln-speichern", null); toast("Regeln gespeichert."); await ladeRegeln(); await ladeStand();
  } catch (e) { zeigeFehler("regeln-speichern", e.message); }
}
function beschreibe(e) {
  const dateien = (e.dateien || []).map((f) => `<a href="${ausgabeLink(f)}" target="_blank" rel="noopener">${esc(f)}</a>`).join(", ");
  switch (e.aktion) {
    case "api-abruf": return { a: "Portal-Abruf", d: `${e.accounts} Accounts${e.hinweise != null ? ` · ${e.hinweise} Hinweise` : ""}` };
    case "abgleich": return { a: "Quartals-Abgleich", d: `${e.geprueft} geprüft · ${e.neueintritte} Neueintritte · ${e.korrekturen} Korrekturen · ${e.handarbeit} Handarbeit${e.abweichungen != null ? ` · ${e.abweichungen} Info` : ""}${dateien ? " · " + dateien : ""}` };
    case "kontrolle": return { a: e.synchron ? "Kontrolle: alles synchron ✓" : "Kontrolle: noch offen", d: `${e.handarbeit} Handarbeit · ${e.neueintritte} Neueintritte · ${e.korrekturen} Korrekturen · ${e.klaerliste} Klärfälle` };
    case "saeumigen-csv": return { a: "Säumigen-CSV", d: `${e.anzahl} Einträge (${e.sicht === "halbjahr" ? "Halbjahresziel" : "Saison-Soll"})${dateien ? " · " + dateien : ""}` };
    case "gesamtexport": return { a: "Excel-Gesamtexport", d: `${e.anzahl} Mitglieder${dateien ? " · " + dateien : ""}` };
    default: return { a: esc(e.aktion), d: dateien };
  }
}
function renderProtokoll(liste) {
  const el = $("protokoll-liste");
  el.innerHTML = liste.length ? liste.map((e) => { const b = beschreibe(e); return `<li><span class="z">${formatZeit(e.zeit)}</span><div><div class="a">${b.a}</div><div class="d">${b.d}</div></div></li>`; }).join("")
    : `<li><div class="empty" style="grid-column:1/-1"><b>Noch keine Einträge</b>Abrufe, Abgleiche und Exporte erscheinen hier chronologisch.</div></li>`;
  wizStartAusVerlauf(liste);
}

// ------------------------------------------------------------------ Exporte ----
async function saeumigenCsv() {
  try { const d = await holeJson(`/api/export/saeumige?sicht=${encodeURIComponent(S.sicht)}`, { method: "POST" }); zeigeFehler("saeumigen-csv", null);
    toast(`Säumigen-CSV erstellt: ${d.anzahl} Einträge.`, { href: ausgabeLink(d.datei), text: basename(d.datei) }); ladeProtokoll(); }
  catch (e) { zeigeFehler("saeumigen-csv", e.message); }
}
async function gesamtexport() {
  try { const d = await holeJson("/api/export/gesamt", { method: "POST" }); zeigeFehler("gesamtexport", null);
    toast(`Excel-Gesamtexport erstellt: ${d.anzahl} Mitglieder, drei Blätter.`, { href: ausgabeLink(d.datei), text: basename(d.datei) }); ladeProtokoll(); }
  catch (e) { zeigeFehler("gesamtexport", e.message); }
}

// ------------------------------------------------------------------ Start ----
document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".navitem, #btn-einstellungen").forEach((b) => b.addEventListener("click", () => zeigePanel(b.dataset.panel)));
  document.querySelectorAll(".subtabs [data-sub]").forEach((b) => b.addEventListener("click", () => zeigeSub(b.dataset.sub)));
  $("btn-abrufen").addEventListener("click", () => abrufen(false));
  document.querySelectorAll(".seg [data-sicht]").forEach((b) => b.addEventListener("click", () => setSicht(b.dataset.sicht)));

  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => c.addEventListener("click", () => { S.k.filter = c.dataset.filter; document.querySelectorAll("#chips-kontingent .chip").forEach((x) => x.setAttribute("aria-pressed", String(x === c))); renderTabelleK(); }));
  $("suche-kontingent").addEventListener("input", (e) => { S.k.suche = e.target.value; renderTabelleK(); });
  bindeSort("tab-mitglieder", S.k.sort, renderTabelleK);
  $("tab-mitglieder-body").addEventListener("click", (e) => { if (e.target.closest("a")) return; const tr = e.target.closest("tr.row"); if (tr) toggleZeile(tr.dataset.fg); });
  $("tab-mitglieder-body").addEventListener("keydown", (e) => { const tr = e.target.closest("tr.row"); if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggleZeile(tr.dataset.fg); } });
  $("btn-saeumige-csv").addEventListener("click", saeumigenCsv); $("btn-saeumige-csv-2").addEventListener("click", saeumigenCsv);
  $("btn-gesamtexport").addEventListener("click", gesamtexport); $("btn-gesamtexport-2").addEventListener("click", gesamtexport);
  ["btn-print-kontingent", "btn-print-helfende", "btn-print-bericht"].forEach((id) => $(id).addEventListener("click", () => window.print()));

  document.querySelectorAll("#chips-helfende .chip").forEach((c) => c.addEventListener("click", () => { S.h.filter = c.dataset.typ; document.querySelectorAll("#chips-helfende .chip").forEach((x) => x.setAttribute("aria-pressed", String(x === c))); renderTabelleH(); }));
  $("suche-helfende").addEventListener("input", (e) => { S.h.suche = e.target.value; renderTabelleH(); });
  bindeSort("tab-helfende", S.h.sort, renderTabelleH);
  bindeChips($("dq-gruppen")); bindeChips($("wiz-1-dq"));

  // Geführter Abgleich
  $("wiz-btn-start").addEventListener("click", wizStart);
  $("wiz-btn-1").addEventListener("click", () => wizZeige(2));
  $("wiz-btn-2").addEventListener("click", () => { renderChecklist(); wizZeige(3); });
  $("wiz-btn-3").addEventListener("click", () => { $("wiz-4-ergebnis").innerHTML = `<div class="wiz-actions" style="margin-top:0"><button class="btn primary" id="wiz-btn-kontrolle">${ic("refresh")}Kontrolle starten</button></div>`; $("wiz-btn-kontrolle").addEventListener("click", wizKontrolle); wizZeige(4); });
  $("wiz-btn-kontrolle").addEventListener("click", wizKontrolle);
  $("wiz-btn-neu").addEventListener("click", wizNeu);
  document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => wizZeige(Number(b.dataset.goto))));
  // Abhaken ohne Neuaufbau der Liste (kein Scroll-Sprung, Fokus bleibt): nur Zähler/Fortschritt nachführen.
  $("wiz-3-liste").addEventListener("change", (e) => {
    const cb = e.target.closest("input[data-key]"); if (!cb) return;
    W.checks[cb.dataset.key] = cb.checked; wizSpeichern();
    cb.closest("li").classList.toggle("done", cb.checked);
    aktualisiereFortschritt();
  });
  const dz = $("dropzone"), input = $("datei-input");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => fairgateHochladen(e.dataTransfer.files[0]));
  input.addEventListener("change", () => { fairgateHochladen(input.files[0]); input.value = ""; });

  $("btn-kategorie-plus").addEventListener("click", () => $("regeln-kategorien").insertAdjacentHTML("beforeend", kategorieZeile()));
  $("regeln-kategorien").addEventListener("click", (e) => { const b = e.target.closest(".k-del"); if (b) b.closest("tr").remove(); });
  $("btn-regeln-speichern").addEventListener("click", speichereRegeln);

  // Start: Regeln, Stand, Verlauf — jeder Schritt fängt seine Fehler selbst. Danach automatisch
  // den Portal-Bestand holen, wenn ein API-Key vorhanden ist (kein Knopf nötig).
  const gespeichert = wizLaden();
  wizZeige(0);
  await ladeRegeln();
  const ok = await ladeStand();
  await ladeProtokoll();
  if (ok && S.daten && S.daten.api_verfuegbar && !geladen()) await abrufen(true);
  if (gespeichert && gespeichert.step >= 3 && gespeichert.dateiName) {
    $("wiz-letzter").insertAdjacentHTML("beforeend", `<span class="l">Unterbrochen</span><span>Ein Abgleich mit «${esc(gespeichert.dateiName)}» war in Schritt ${gespeichert.step}. Denselben Export in Schritt 2 nochmals laden — die Häkchen bleiben erhalten.</span>`);
  }
});
