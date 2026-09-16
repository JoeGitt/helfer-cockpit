// Helfer-Cockpit 2 — Frontend. Läuft ausschliesslich gegen 127.0.0.1, ohne Framework,
// ohne CDN. Alle Daten kommen per fetch() von der lokalen JSON-API (cockpit/webapp.py).
"use strict";

// ------------------------------------------------------------------ Zustand ----
const S = {
  sicht: "saison", daten: null, regeln: null,
  k: { filter: "alle", suche: "", sort: { key: "status", dir: "asc" }, offen: new Set(), familieEntwurf: null },
  h: { filter: "alle", suche: "", sort: { key: "name", dir: "asc" } },
};
// Geführter Abgleich: step 0 = Start, 1 = Daten, 2 = Abarbeiten, 3 = Kontrolle, 4 = fertig. checks = abgehakte Punkte
// (nur Schlüssel wie "h:3", keine Personendaten) — bleiben im Browser-Speicher erhalten.
const W = { step: 0, abgleich: null, checks: {}, wahl: {}, offen: {}, phase: null, ack: false, runId: null, dateiName: "" };
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
const ART_LABEL = { schluessel: "E-Mail im Portal nachführen", austritt: "Im Portal löschen" };

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
function orgSlug() { const a = S.daten && S.daten.alle_accounts[0]; const m = a && String(a.portal_url).match(/helfereinsatz\.ch\/([^/]+)\//); return m ? m[1] : "pfadi-winterthur-handball"; }
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
const HELFENDE_ANSICHTEN = ["p-kontingent", "p-helfende"];   // eine Navigation «Helfende», zwei Ansichten
function zeigePanel(id) {
  const navId = HELFENDE_ANSICHTEN.includes(id) ? "p-kontingent" : id;
  document.querySelectorAll(".navitem, #btn-einstellungen").forEach((b) => {
    if (b.dataset.panel === navId) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".seg.ansicht [data-ansicht]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ansicht === id)));
  if (HELFENDE_ANSICHTEN.includes(id)) { try { localStorage.setItem("hc2-ansicht", id); } catch (e) { /* optional */ } }
  document.querySelectorAll("section.panel").forEach((p) => p.classList.toggle("active", p.id === id));
  window.scrollTo({ top: 0 });
}
function zeigeSub(id) {
  document.querySelectorAll(".subtabs [data-sub]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sub === id)));
  document.querySelectorAll(".subpanel").forEach((p) => p.classList.toggle("active", p.id === id));
  if (id === "s-antworten") ladeAntworten();
}
// ---- Einstellungen · Gemerkte Antworten («Andere Person» aus den Vorfragen) ----
async function ladeAntworten() {
  const el = $("antworten-liste"); if (!el) return;
  try {
    const d = await holeJson("/api/entscheide");
    renderAntworten(d.entscheide || {});
  } catch (e) { el.innerHTML = `<div class="empty"><b>Konnte nicht laden</b>${esc(e.message)}</div>`; }
}
function renderAntworten(ent) {
  const el = $("antworten-liste");
  const eintraege = Object.entries(ent);
  $("sub-n-antworten").textContent = eintraege.length ? `· ${eintraege.length}` : "";
  if (!eintraege.length) { el.innerHTML = `<div class="empty"><b>Nichts gemerkt</b>Antworten «Andere Person» aus den Vorfragen des Abgleichs erscheinen hier.</div>`; return; }
  el.innerHTML = `<ul class="checklist kompakt">${eintraege.map(([id, e]) => `<li><span></span><div class="t"><b>${esc(e.name || `Account ${id}`)}</b><span>${esc(FALL_LABEL[e.fall] || "")}${e.kandidaten ? ` wie ${esc(e.kandidaten)}` : ""} → ${esc(ANTWORT_LABEL[e.antwort] || e.antwort)}${e.zeit ? ` · gemerkt am ${esc(e.zeit)}` : ""}</span></div><div class="a"><button class="btn" data-antwort-loeschen="${esc(id)}">Vergessen</button></div></li>`).join("")}</ul>`;
  el.querySelectorAll("[data-antwort-loeschen]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const d = await holeJson("/api/entscheide/loeschen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ helper_ids: [b.dataset.antwortLoeschen] }) });
      renderAntworten(d.entscheide || {});
      toast(d.abgleich_aktualisiert ? "Vergessen — die Vorfrage erscheint wieder in Schritt 1." : "Vergessen — beim nächsten Abgleich wird wieder gefragt.");
      if (d.abgleich_aktualisiert && W.abgleich) { try { const a = await holeJson("/api/abgleich/letzter"); W.abgleich = a; W.runId = wizRunId(a); wizSpeichern(); renderPlausi(a); } catch (e) { /* Anzeige folgt beim nächsten Laden */ } }
    } catch (e) { toast(`Fehler: ${e.message}`); b.disabled = false; }
  }));
}

// ------------------------------------------------------------------ Laden ----
async function ladeStand() {
  try { anwenden(await holeJson("/api/stand")); zeigeFehler("stand-transport", null); return true; }
  catch (e) { zeigeFehler("stand-transport", e.message); return false; }
}
// Ein laufender Abruf wird von weiteren Aufrufern abgewartet, nie abgewiesen — sonst meldet
// z. B. Schritt 1 des Abgleichs «konnte nicht geholt werden», obwohl der Start-Abruf nur noch läuft.
let abrufPromise = null;
let letzterAbrufFehler = "";
function abrufen(still = false) {
  if (abrufPromise) return abrufPromise;
  abrufPromise = (async () => {
    const btn = $("btn-abrufen");
    btn.disabled = true; btn.querySelector(".ic").classList.add("spin"); btn.querySelector("span").textContent = "Holt …";
    let ok = false;
    try {
      const d = await holeJson("/api/abruf", { method: "POST" });
      anwenden(d); zeigeFehler("abruf-transport", null);
      ok = !d.fehler; letzterAbrufFehler = d.fehler || "";
      if (ok && !still) toast(`Abgerufen: ${d.alle_accounts.length} Accounts, ${d.mitglieder.length} Mitglieder.`);
      ladeProtokoll();
    } catch (e) { letzterAbrufFehler = e.message; zeigeFehler("abruf-transport", e.message); }
    finally { btn.disabled = false; btn.querySelector(".ic").classList.remove("spin"); btn.querySelector("span").textContent = "Neu abrufen"; abrufPromise = null; }
    return ok;
  })();
  return abrufPromise;
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
  document.querySelectorAll(".seg-n-mitglieder").forEach((el) => { el.textContent = g ? d.mitglieder.length : ""; });
  document.querySelectorAll(".seg-n-accounts").forEach((el) => { el.textContent = g ? d.alle_accounts.length : ""; });
  const kritisch = d.hinweise.filter((h) => h.schweregrad === "kritisch").length;
  const nAb = $("nav-n-abgleich");
  nAb.textContent = kritisch || ""; nAb.className = "n num " + (kritisch ? "crit" : "");
  $("sub-n-dq").textContent = d.hinweise.length ? `· ${d.hinweise.length}` : "";
  renderKennzahlen(); renderTabelleK(); renderTabelleH(); renderBericht(); renderDQ($("dq-gruppen"), $("dq-meta"));
  renderWizardStart();
}

// ------------------------------------------------------------------ Kontingent ----
function statusVon(m) { return S.sicht === "saison" ? m.status_saison : m.status_halbjahr; }
function zielVon(m) { const hz = S.regeln ? S.regeln.halbjahresziel : 1; return S.sicht === "saison" ? m.soll : (m.kinder ? hz * m.kinder.length : hz); }
// Kontingent-Zeilen: ein Mitglied pro Zeile — eine Familie (Topf) als eine Zeile mit ihren Kindern
function kontingentZeilen() {
  const rows = [], fam = new Map();
  (S.daten ? S.daten.mitglieder : []).forEach((m) => {
    if (!m.familie) { rows.push(m); return; }
    let f = fam.get(m.familie.schluessel);
    if (!f) {
      f = { fg: m.familie.schluessel, name: m.familie.name, gruppen: [], accounts: m.familie.accounts, soll: m.familie.soll, ist: m.familie.ist,
            soll_konflikt: false, status_saison: m.status_saison, status_halbjahr: m.status_halbjahr, kinder: [], fgs: m.familie.fgs };
      fam.set(m.familie.schluessel, f); rows.push(f);
    }
    f.kinder.push(m); m.gruppen.forEach((g) => { if (!f.gruppen.includes(g)) f.gruppen.push(g); });
    if (m.soll_konflikt) f.soll_konflikt = true;
  });
  return rows;
}
function zeilenSchluessel(fg) { const r = kontingentZeilen().find((x) => x.fg === fg || (x.kinder && x.kinder.some((k) => k.fg === fg))); return r ? r.fg : fg; }
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
  const z = { alle: n, erfuellt: 0, auf_kurs: 0, saeumig: 0, zweitaccount: 0, familie: 0 };
  d.mitglieder.forEach((m) => { z[statusVon(m)]++; if (m.accounts.length > 1 || m.familie) z.zweitaccount++; if (m.familie) z.familie++; });
  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => { c.querySelector(".c").textContent = z[c.dataset.filter] ?? 0; });
}
function gefilterteMitglieder() {
  const f = S.k.filter, q = S.k.suche.trim().toLowerCase();
  const liste = kontingentZeilen().filter((m) => {
    if (f === "zweitaccount" && m.accounts.length < 2) return false;
    if (f === "familie" && !m.kinder) return false;
    if (f !== "alle" && f !== "zweitaccount" && f !== "familie" && statusVon(m) !== f) return false;
    if (q && !(m.name.toLowerCase().includes(q) || m.fg.toLowerCase().includes(q) || (m.fgs || []).some((x) => x.toLowerCase().includes(q)) || m.accounts.some((a) => a.name.toLowerCase().includes(q)))) return false;
    return true;
  });
  const { key, dir } = S.k.sort;
  const wert = (m) => ({ name: m.name, gruppen: m.gruppen.join(", "), accounts: m.accounts.length, soll: m.soll, ist: m.ist, status: STATUS[statusVon(m)].rang })[key];
  liste.sort((a, b) => (vergleich(wert(a), wert(b)) || vergleich(a.name, b.name)) * (dir === "asc" ? 1 : -1));
  return liste;
}
function nameAus(betroffen) { return String(betroffen).split(/ \(|: |«/)[0].trim(); }
function hinweiseZu(m) {
  const namen = new Set(m.accounts.map((a) => a.name)), fgs = m.kinder ? m.kinder.map((k) => k.fg) : [m.fg];
  return (S.daten.hinweise || []).filter((h) => h.betroffene.some((b) => fgs.some((fg) => b === fg || b.includes(fg)) || namen.has(nameAus(b))));
}
function renderTabelleK() {
  const liste = gefilterteMitglieder(), body = $("tab-mitglieder-body"), n = S.daten.mitglieder.length;
  if (!n) { body.innerHTML = `<tr><td colspan="7"><div class="empty"><b>Noch keine Daten</b>Der Portal-Bestand wird beim Start automatisch geholt — sonst links «Neu abrufen».</div></td></tr>`; $("tfoot-kontingent").textContent = ""; return; }
  body.innerHTML = liste.length ? liste.map(zeileK).join("") : `<tr><td colspan="7"><div class="empty"><b>Kein Treffer</b>Filter oder Suchbegriff anpassen.</div></td></tr>`;
  const sortName = { name: "Name", gruppen: "Gruppen", accounts: "Accounts", soll: "Soll", ist: "Ist", status: "Status" }[S.k.sort.key];
  const nFam = kontingentZeilen().filter((r) => r.kinder).length;
  $("tfoot-kontingent").innerHTML = `<span>${liste.length} Zeilen · ${n} Mitglieder${nFam ? `, davon ${nFam} Familien` : ""}</span><span>· sortiert nach ${sortName}</span><span style="margin-left:auto">Zusammenführung ausschliesslich über FG-Nummer · Familie = Topf</span>`;
  markiereSort("tab-mitglieder", S.k.sort);
}
function zeileK(m) {
  const offen = S.k.offen.has(m.fg), mehrere = m.accounts.length > 1;
  const summanden = mehrere ? `<span class="sub">(${m.accounts.map((a) => fmt(a.ist)).join(" + ")})</span>` : "";
  const konflikt = m.soll_konflikt ? ` <span class="konflikt" title="Mehrere Mitglieds-Accounts mit dieser FG-Nummer — im Portal bereinigen">${ic("alert", "sm")}Konflikt</span>` : "";
  const tag = m.kinder ? `<span class="fgtag fam">${ic("users", "sm")}${m.kinder.length} Mitglieder</span> <span class="fgtag">${esc(m.fgs.join(" · "))}</span>` : `<span class="fgtag">${esc(m.fg)}</span>`;
  return `
    <tr class="row ${m.kinder ? "fam" : ""}" data-fg="${esc(m.fg)}" role="button" tabindex="0" aria-expanded="${offen}">
      <td><div class="cell-name">${ic("chev", "sm chev")}<div><span class="name">${esc(m.name)}</span> ${tag}</div></div></td>
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
  const sum = `${m.kinder ? "Familien-Topf: " : ""}Ist ${fmt(m.ist)} ${m.accounts.length > 1 ? "= " + m.accounts.map((a) => fmt(a.ist)).join(" + ") : ""} · Ziel ${fmt(zielVon(m))} (${S.sicht === "saison" ? "Saison-Soll" : "Halbjahresziel"}${m.kinder ? `, ${m.kinder.length} Kinder` : ""})`;
  const kinder = m.kinder ? `<div class="kinder"><b>Mitglieder der Familie</b> — die Einsätze zählen in den gemeinsamen Topf, egal auf welchem Account: ${m.kinder.map((k) => `<span class="kind">${esc(k.name)} <span class="fgtag">${esc(k.fg)}</span> Soll ${fmt(k.soll)}, eigene ${fmt(k.ist)}</span>`).join(" ")}</div>` : "";
  const famAktion = familieAktion(m);
  return `<div class="ledger">${kinder}<table><thead><tr><th>Account</th><th>Typ</th><th class="r">Ist</th><th class="r">Soll</th><th class="r" title="Geleistet / Zugesagt / Nicht erschienen">OK / Zug. / NOK</th><th>Bemerkung</th><th></th></tr></thead><tbody>${zeilen}</tbody></table><div class="sum num">${esc(sum)}</div>${dq}${famAktion}</div>`;
}
// ---- Familie zusammenführen (Spez 6.11): Anleitung mit fertigem Bemerkungstext, Wahrheit bleibt im Portal ----
function familieAktion(m) {
  const e = S.k.familieEntwurf;
  const aktiv = e && e.basis === m.fg;
  if (!aktiv) return `<div class="famact"><button class="btn" data-fam-start="${esc(m.fg)}">${ic("users")}${m.kinder ? "Familie erweitern …" : "Zu Familie zusammenführen …"}</button><span class="sub">Geschwister zu einem Topf verbinden: Soll = Summe, Einsätze zählen egal auf welchem Account.</span></div>`;
  const basisFgs = m.kinder ? m.kinder.map((k) => k.fg) : [m.fg];
  const alleZeilen = kontingentZeilen();
  const kandidaten = alleZeilen.filter((r) => r.fg !== m.fg && !e.weitere.includes(r.fg));
  const gewaehlt = e.weitere.map((fg) => alleZeilen.find((r) => r.fg === fg)).filter(Boolean);
  const fgsGesamt = [...basisFgs, ...gewaehlt.flatMap((r) => r.kinder ? r.kinder.map((k) => k.fg) : [r.fg])];
  // Wohin die Nummern gehören: alle Zweitaccounts der Beteiligten; gibt es keinen, an den Mitglieds-Account der Basis
  const beteiligte = [m, ...gewaehlt];
  const zweit = beteiligte.flatMap((r) => r.accounts.filter((a) => a.typ !== "mitglied"));
  const ziele = zweit.length ? zweit : [m.accounts.find((a) => a.typ === "mitglied")].filter(Boolean);
  const anleitung = gewaehlt.length ? `<ol class="howto compact">${ziele.map((a, i) => { const eigene = (a.fgs || []).filter((x) => !fgsGesamt.includes(x)); const text = [...(a.fgs && a.fgs.length ? [a.fgs[0]] : []), ...fgsGesamt.filter((x) => !(a.fgs || []).length || x !== a.fgs[0]), ...eigene].filter((x, k, arr) => arr.indexOf(x) === k).join(", "); return `<li><span class="n">${i + 1}</span><div><b>${esc(a.name)} (${TYP_LABEL[a.typ] || a.typ})</b><span>Bemerkung im Portal auf <b class="num">${esc(text)}</b> setzen${a.bemerkung ? ` (heute: «${esc(a.bemerkung)}»)` : ""} <button class="btn" data-copy="${esc(text)}">${ic("file", "sm")}Kopieren</button> ${plink(a.portal_url, "Im Portal öffnen")}</span></div></li>`; }).join("")}<li><span class="n">${ziele.length + 1}</span><div><b>Links «Neu abrufen»</b><span>Das Cockpit erkennt die Familie an den gemeinsamen Nummern — kein lokaler Zustand, jeder Admin sieht sie im Portal.</span></div></li></ol>` : `<p class="hint">Mitglied wählen, das zur Familie gehört.</p>`;
  return `<div class="famact offen"><div class="famhead"><b>${ic("users")}Familie: ${esc(m.kinder ? m.name : m.name)}${gewaehlt.length ? " + " + gewaehlt.map((r) => esc(r.name)).join(" + ") : ""}</b><button class="btn ghost" data-fam-abbruch="1">Abbrechen</button></div>
    <div class="famwahl"><label class="search">${ic("search", "sm")}<input type="search" list="fam-liste" data-fam-suche="${esc(m.fg)}" placeholder="Weiteres Mitglied: Name oder FG-Nummer" aria-label="Mitglied für die Familie suchen"></label><datalist id="fam-liste">${kandidaten.slice(0, 400).map((r) => `<option value="${esc(r.fg)}">${esc(r.name)}</option>`).join("")}</datalist>${gewaehlt.map((r) => `<span class="chip" aria-pressed="true">${esc(r.name)} <span class="c">${esc(r.fg)}</span> <button class="x" data-fam-weg="${esc(r.fg)}" aria-label="Entfernen">×</button></span>`).join("")}</div>
    ${anleitung}</div>`;
}
function toggleZeile(fg) { if (S.k.offen.has(fg)) S.k.offen.delete(fg); else S.k.offen.add(fg); renderTabelleK(); }
function springeZuMitglied(fg) {
  S.k.filter = "alle"; S.k.suche = ""; $("suche-kontingent").value = "";
  document.querySelectorAll("#chips-kontingent .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.filter === "alle")));
  fg = zeilenSchluessel(fg);
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
  try { localStorage.setItem(WIZ_KEY, JSON.stringify({ runId: W.runId, step: W.step, checks: W.checks, wahl: W.wahl, phase: W.phase, ack: W.ack, dateiName: W.dateiName })); } catch (e) { /* Speicher optional */ }
}
function wizLaden() {
  try { const s = JSON.parse(localStorage.getItem(WIZ_KEY) || "null"); if (s && s.runId) { W.runId = s.runId; W.checks = s.checks || {}; W.wahl = s.wahl || {}; W.phase = s.phase || null; W.ack = !!s.ack; W.dateiName = s.dateiName || ""; return s; } } catch (e) { /* ignorieren */ }
  return null;
}
function wizRunId(d) { return `${d.geprueft}|${d.zusammenfassung}|${basename((d.dateien || {}).import || "")}`; }

const FERTIG = 4;
function wizZeige(step) {
  W.step = step; wizSpeichern();
  $("wiz-start").hidden = step !== 0;
  [1, 2, 3].forEach((n) => { $(`wiz-${n}`).hidden = step !== n; });
  $("wiz-fertig").hidden = step !== FERTIG;
  W.maxStep = Math.max(W.maxStep || 0, step);
  document.querySelectorAll("#wiz-steps li").forEach((li) => {
    const n = Number(li.dataset.step);
    li.dataset.state = step === FERTIG || n < step ? "fertig" : n === step ? "aktiv" : "offen";
    const erreichbar = n <= (W.maxStep || 0) && step !== FERTIG && step !== 0;
    li.classList.toggle("klickbar", erreichbar);
    li.setAttribute("tabindex", erreichbar ? "0" : "-1");
    li.setAttribute("role", erreichbar ? "button" : "");
    li.title = erreichbar ? `Zu Schritt ${n} wechseln — nichts geht verloren` : "";
  });
}
function wizTabKlick(li) {
  const n = Number(li.dataset.step);
  if (!li.classList.contains("klickbar")) return;
  if (n === 2 && W.abgleich) renderChecklist();
  wizZeige(n);
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
  st.className = "statusline busy"; st.innerHTML = ic("refresh") + "<span>Portal-Bestand wird geholt … (bei mehreren hundert Accounts dauert das einige Sekunden)</span>";
  W.portalOk = false;
  if (S.daten && S.daten.api_verfuegbar) await abrufen(true);
  W.portalOk = geladen();
  if (W.portalOk) {
    const d = S.daten;
    st.className = "statusline ok"; st.innerHTML = ic("check") + `<span><b>${d.alle_accounts.length} Accounts</b> aus dem Portal (${d.mitglieder.length} Mitglieder) · Stand ${esc(d.stand)}</span>`;
  } else {
    const grund = letzterAbrufFehler || (S.daten && S.daten.fehler) || "keine Verbindung zur API oder kein API-Key hinterlegt";
    st.className = "statusline err"; st.innerHTML = ic("alert") + `<span><b>Portal-Bestand konnte nicht geholt werden:</b> ${esc(grund)} <button class="btn" id="wiz-btn-retry" style="margin-left:8px">${ic("refresh")}Nochmals versuchen</button></span>`;
    $("wiz-btn-retry").addEventListener("click", wizStart);
  }
  pruefeSchritt1();
}
function pruefeSchritt1() {
  const unbekannt = W.abgleich && Object.keys((W.abgleich.kategorien || {}).unbekannt || {}).length;
  const offen = W.abgleich && (W.abgleich.vorfragen || []).length;
  $("wiz-btn-2").disabled = !(W.portalOk && W.abgleich && (!unbekannt || W.ack) && !offen);
}
// ---- Vorfragen: mögliche Zweitaccounts, die VOR der Import-Datei beantwortet werden müssen ----
const ANTWORT_LABEL = { zweitaccount: "Zweitaccount", andere: "Andere Person", unklar: "Noch offen — Klärfall", elternteil: "Elternteil (Zweitaccount)", gleiche_person: "Dieselbe Person", ersatz: "Ersatz-Account" };
const FALL_LABEL = { nachname: "gleicher Nachname", name: "gleicher Name, andere E-Mail", email: "gleiche E-Mail" };
const MIT_FG = new Set(["zweitaccount", "elternteil", "gleiche_person", "ersatz"]);
function renderVorfragen(d) {
  const el = $("wiz-1-vorfragen"); if (!el) return;
  const vf = d.vorfragen || [], ent = d.entscheide || {};
  const beantwortet = Object.entries(ent).filter(([, e]) => e && e.antwort);
  if (!vf.length && !beantwortet.length) { el.innerHTML = ""; return; }
  let html = "";
  if (vf.length) {
    html += `<div class="vf-box"><h3>${ic("alert", "sm")}Vorfragen, bevor die Import-Datei entsteht <span class="cnt">${vf.length}</span></h3>
      <p class="hint">Diese Portal-Accounts haben keine FG-Nummer, passen aber zu einem Mitglied in Fairgate — über Nachname, Name oder E-Mail. Deine Antwort entscheidet, was der Import schreibt; die Import-Datei entsteht danach neu. Ohne Antwort kommt der Account nicht in die Datei.</p>
      <ul class="vf">${vf.map((v) => {
        const id = v.helper_id, k = v.kandidaten || [];
        const wahl = `<select data-vf-fg="${id}" aria-label="Welches Kind">${k.map((x) => `<option value="${esc(x.fg)}">${esc(x.name)} (${esc(x.fg)})</option>`).join("")}</select>`;
        return `<li data-vf="${id}">
          <div class="kopf"><b>${esc(v.name)}</b><span class="sub">${esc(v.email)}</span><span class="sub">${esc(v.einsatz_text)} · Zielwert ${esc(v.zielwert)} · Gruppen: ${esc((v.gruppen || []).join(", ") || "—")}</span>${plink(v.portal_url, "Account im Portal")}</div>
          <div class="kand"><div class="frage">${esc(v.frage)}</div>${k.map((x) => `<div>· <b>${esc(x.name)}</b> (${esc(x.fg)})${x.telefon ? ` · Telefon ${esc(x.telefon)}` : ""}${x.portal_account ? ` · Portal-Account ${esc(x.portal_account)}` : ""} ${plink(x.portal_url, "Im Portal")}</div>`).join("")}${(v.fakten || []).map((f) => `<div class="sub">${esc(f)}</div>`).join("")}${v.bemerkung ? `<div class="sub">Bemerkung im Portal: «${esc(v.bemerkung)}» — die FG-Nummer müsste dann von Hand dazu, Zielwert und Gruppe setzt der Import</div>` : ""}</div>
          <div class="antw">${(v.optionen || []).map((o) => `<label title="${esc(o.folge)}"><input type="radio" name="vf-${id}" value="${esc(o.antwort)}"><span>${esc(o.label)}${o.mit_fg ? ` ${k.length > 1 ? wahl : `<b>${esc(k[0] ? k[0].name : "")}</b>`}` : ""}<small>${esc(o.folge)}</small></span></label>`).join("")}</div></li>`; }).join("")}</ul>
      <div class="vf-foot"><span class="sub" id="vf-stand">0 von ${vf.length} beantwortet</span><button class="btn primary" id="vf-btn" disabled>${ic("check")}Antworten übernehmen</button></div>
      <p class="hint" style="margin:8px 0 0">«Andere Person» merkt sich das Cockpit dauerhaft — die Frage kommt nicht wieder. «Zweitaccount» erledigt sich mit dem Import von selbst.</p></div>`;
  }
  if (beantwortet.length) {
    html += `<details class="vf-done"><summary>${beantwortet.length} Vorfragen beantwortet — ändern</summary><ul>${beantwortet.map(([id, e]) => `<li><b>${esc(e.name || `Account ${id}`)}</b><span class="sub">${esc(FALL_LABEL[e.fall] || "")}${e.kandidaten ? ` wie ${esc(e.kandidaten)}` : ""} → ${esc(ANTWORT_LABEL[e.antwort] || e.antwort)}${e.fg && MIT_FG.has(e.antwort) ? ` (${esc(e.fg)})` : ""}${e.gespeichert ? " · dauerhaft gemerkt" : ""}</span><button class="btn" data-vf-reset="${esc(id)}">Nochmals fragen</button></li>`).join("")}</ul></details>`;
  }
  el.innerHTML = html;
  const stand = () => {
    const n = vf.filter((v) => el.querySelector(`input[name="vf-${v.helper_id}"]:checked`)).length;
    if ($("vf-stand")) $("vf-stand").textContent = `${n} von ${vf.length} beantwortet${n < vf.length ? " — unbeantwortete bleiben vorerst draussen" : ""}`;
    if ($("vf-btn")) $("vf-btn").disabled = n === 0;
  };
  el.querySelectorAll("input[type=radio]").forEach((r) => r.addEventListener("change", stand));
  if ($("vf-btn")) $("vf-btn").addEventListener("click", () => {
    const entscheide = {};
    vf.forEach((v) => {
      const r = el.querySelector(`input[name="vf-${v.helper_id}"]:checked`); if (!r) return;
      const sel = el.querySelector(`select[data-vf-fg="${v.helper_id}"]`);
      entscheide[v.helper_id] = { antwort: r.value, fg: MIT_FG.has(r.value) ? (sel ? sel.value : v.kandidaten[0].fg) : "", name: v.name, fall: v.fall, schluessel: v.schluessel, kandidaten: (v.kandidaten || []).map((x) => `${x.name} (${x.fg})`).join(", ") };
    });
    sendeEntscheide({ entscheide });
  });
  el.querySelectorAll("[data-vf-reset]").forEach((b) => b.addEventListener("click", () => sendeEntscheide({ entscheide: { [b.dataset.vfReset]: null } })));
}
async function sendeEntscheide(body) {
  const btn = $("vf-btn"); if (btn) { btn.disabled = true; btn.innerHTML = ic("refresh", "spin") + "Import-Datei wird neu erzeugt …"; }
  try {
    const d = await holeJson("/api/abgleich/entscheide", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    W.abgleich = d; W.runId = wizRunId(d); wizSpeichern();
    renderPlausi(d);
    const n = Object.values(body.entscheide || {}).filter(Boolean).length;
    toast(n ? `${n} Antworten übernommen — Import-Datei neu erzeugt.` : "Vorfrage wieder offen.");
    ladeProtokoll();
  } catch (e) { zeigeFehler("fairgate", e.message); renderPlausi(W.abgleich); }
}
async function fairgateHochladen(datei) {
  if (!datei) return;
  const dz = $("dropzone");
  dz.innerHTML = ic("refresh", "spin") + `<br>Wird geprüft: <b>${esc(datei.name)}</b> …`;
  $("wiz-btn-2").disabled = true; $("wiz-2-plausi").innerHTML = "";
  if (!W.portalOk && geladen()) W.portalOk = true;
  try {
    const d = await holeJson("/api/fairgate", { method: "POST", body: await datei.arrayBuffer() });
    zeigeFehler("fairgate", null);
    const neuerRun = wizRunId(d);
    if (W.runId !== neuerRun) { W.checks = {}; W.wahl = {}; W.offen = {}; W.phase = null; W.ack = false; }
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
  renderVorfragen(d);
  const pruefe = () => { W.ack = !unbekannt.length || ($("wiz-ack") && $("wiz-ack").checked); wizSpeichern(); pruefeSchritt1(); };
  if ($("wiz-ack")) $("wiz-ack").addEventListener("change", pruefe);
  pruefe();
}
function clItem(key, titel, detail, aktionen = "") {
  const done = !!W.checks[key];
  return `<li class="${done ? "done" : ""}"><input type="checkbox" data-key="${esc(key)}" ${done ? "checked" : ""} aria-label="Erledigt: ${esc(titel)}"><div class="t"><b>${esc(titel)}</b>${detail ? `<span>${esc(detail)}</span>` : ""}</div><div class="a">${aktionen}</div></li>`;
}
function klaerItem(key, kf, mitHaken = true) {
  const done = !!W.checks[key];
  const wahl = W.wahl[key];
  const fakten = (kf.fakten || []).map((f) => `<li>${esc(f)}</li>`).join("");
  const opts = (kf.optionen || []).map((o) => { const i = o.indexOf(" → "); return { wenn: i < 0 ? o : o.slice(0, i), dann: i < 0 ? "" : o.slice(i + 3) }; });
  const knoepfe = opts.length ? `<div class="wahl"><span class="wahl-frage">${wahl == null ? "Was trifft zu?" : "Deine Wahl:"}</span>${opts.map((o, i) => `<button type="button" class="opt ${wahl === i ? "on" : ""}" data-wahl="${esc(key)}" data-i="${i}">${esc(o.wenn)}</button>`).join("")}</div>${wahl != null && opts[wahl] ? `<div class="dann">${ic("chev", "sm")}<span>${esc(opts[wahl].dann || "Nichts weiter zu tun.")}</span></div>` : ""}` : "";
  const schritte = (kf.schritte || []).map((s) => `<li>${esc(s)}</li>`).join("");
  const links = kf.links ? kf.links.map((l) => plink(l.url, l.text)).join("") : plink(kf.portal_url, "Im Portal öffnen");
  const offen = wahl != null || !!W.offen[key];
  const lead = kf.lead || (kf.fakten && kf.fakten.length ? kf.fakten[0] : "");
  return `<li class="${done ? "done" : ""} klaer">${mitHaken ? `<input type="checkbox" data-key="${esc(key)}" ${done ? "checked" : ""} aria-label="Erledigt: ${esc(kf.titel)}">` : "<span></span>"}
    <details class="kf" data-kf="${esc(key)}" ${offen ? "open" : ""}><summary><b>${esc(kf.titel)}</b> ${kf.wo ? `<span class="typ ${kf.wo === "Fairgate" ? "" : "mitglied"}">${esc(kf.wo)}</span>` : ""}${lead ? `<span class="lead">${esc(lead)}</span>` : ""}</summary>
      <div class="kf-body">${fakten ? `<ul class="fakten">${fakten}</ul>` : ""}${schritte ? `<ol class="schritte">${schritte}</ol>` : ""}${knoepfe}</div></details>
    <div class="a">${links}</div></li>`;
}
// Portal-eigene Befunde (D3 Doppel-Mitglied, D10 Neuregistrierung) als konkrete Schritt-Anweisungen
function portalBefunde(d) {
  const acc = S.daten ? S.daten.alle_accounts : [];
  const inKlaerfall = new Set((d.klaerliste || []).map((k) => nameAus(k.titel)));
  const eins = (x) => `${x.num_ok} geleistet, ${x.num_confirmed} zugesagt`;
  const items = [];
  (S.daten ? S.daten.hinweise : []).forEach((h) => {
    if (h.code === "D10") h.betroffene.forEach((b, i) => {
      const name = nameAus(b), fgs = (b.match(/FG-\d+/g) || []);
      if (inKlaerfall.has(name)) return;                       // Fall E im Klärfall deckt das ab
      const ohne = acc.find((x) => x.name === name && !x.fg), mit = acc.find((x) => x.fg === fgs[0] && x.typ === "mitglied");
      // Wie der Server (Fall E): ein Namensvetter, der schon Freiwillige(r) mit Zielwert 0 ist, gilt als erledigt
      const erledigt = ohne && ohne.typ === "freiwillig" && !ohne.zielwert && !(ohne.gruppen || []).includes("Mitglied");
      const gefragt = ohne && ((d.vorfragen || []).some((v) => v.helper_id === ohne.id) || (d.entscheide || {})[String(ohne.id)]);
      if (erledigt || gefragt) return;                         // läuft über die Vorfragen in Schritt 1
      const fg = fgs[0] || "FG-…", mailOhne = ohne ? ohne.email : "?", mailMit = mit ? mit.email : "?";
      items.push({ key: `d:D10:${i}`, titel: `${name}: zwei Accounts — einer mit ${fg}, einer ohne. Zweitaccount oder Ersatz?`, wo: "Portal",
        fakten: [ohne ? `Account ohne FG-Nummer: E-Mail ${ohne.email} · ${eins(ohne)} — Link «Account ohne FG» rechts` : `Account ohne FG-Nummer: ${b}`,
                 mit ? `Account mit ${mit.fg}: E-Mail ${mit.email} · ${eins(mit)} — Link «${mit.fg}» rechts` : `Account mit ${fg}`,
                 "Entscheidungshilfe: Steht in der E-Mail des Accounts ohne FG-Nummer der eigene Vorname, ist es dieselbe Person mit neuer Adresse. Steht ein anderer Vorname zum gleichen Nachnamen (Familienadresse), ist es der Zweitaccount eines Elternteils.",
                 "Der Import hat den Account ohne FG-Nummer auf «Freiwillige», Zielwert 0 gesetzt (falls er das nicht schon war) — das passt in beiden Fällen"],
        optionen: [`Zweitaccount (Elternteil) → beide Accounts bleiben; beim Account ohne FG-Nummer (${mailOhne}) im Portal die Bemerkung «${fg}» eintragen — ab dann zählen seine Einsätze dem Mitglied`,
                   `Dieselbe Person mit neuer E-Mail → Einsätze des Accounts ohne FG-Nummer (${mailOhne}) auf den Account ${fg} (${mailMit}) umhängen (Portal: Event öffnen, Einsatz bearbeiten, Person wechseln); dort die E-Mail auf ${mailOhne} ändern; danach den Account ohne FG-Nummer löschen (Helfende, Person, «Helfer:in löschen» — unwiderruflich)`,
                   "Andere Person (nur Namensgleichheit) → nichts weiter tun; nach dem Import taucht der Fall nicht mehr auf"],
        links: [ohne && { url: ohne.portal_url, text: "Account ohne FG" }, mit && { url: mit.portal_url, text: mit.fg }].filter(Boolean) });
    });
    if (h.code === "D3") h.betroffene.forEach((fg, i) => {
      const konten = acc.filter((x) => x.fg === fg && x.typ === "mitglied");
      items.push({ key: `d:D3:${i}`, titel: `${fg}: ${konten.length} Mitglieds-Accounts mit derselben FG-Nummer`, wo: "Portal",
        fakten: konten.map((x) => `${x.name}: E-Mail ${x.email} · ${eins(x)}`).concat(["Das Kontingent rechnet bis zur Bereinigung mit dem höchsten Zielwert"]),
        optionen: ["Dieselbe Person → Einsätze auf einen Account umhängen (Portal: Event öffnen, Einsatz bearbeiten, Person wechseln), dann den anderen Account löschen (Helfende, Person, «Helfer:in löschen» — unwiderruflich)",
                   "Zwei Personen (z. B. Elternteil) → beim Nicht-Mitglied Gruppe «Mitglied» entfernen, Gruppe «Freiwillige» setzen, Zielwert 0; die FG-Nummer bleibt (Zweitaccount)"],
        links: konten.map((x) => ({ url: x.portal_url, text: x.name })) });
    });
  });
  return items;
}
function renderChecklist() {
  const d = W.abgleich; if (!d) return;
  $("wiz-3-lead").innerHTML = `<b>${esc(d.zusammenfassung)}</b> Drei Abschnitte, in dieser Reihenfolge: erst im Portal von Hand, dann die Import-Datei, dann die Klärfälle. Es ist immer nur ein Abschnitt offen.`;
  const hand = d.handarbeit.map((h, i) => ({ ...h, key: `h:${i}` }));
  const schluessel = hand.filter((h) => h.art === "schluessel"), austritte = hand.filter((h) => h.art === "austritt");
  const befunde = portalBefunde(d);
  const warn = [...(d.duplikat_warnungen || []).map((t, i) => ({ key: `w:${i}`, t, k: "Duplikat-Warnung" })),
    ...(d.unbekannte_kategorien || []).map((t, i) => ({ key: `u:${i}`, t, k: "Unbekannte Kategorie" }))];
  const nImport = d.neueintritte + d.korrekturen, imp = basename(d.dateien.import), liste = basename(d.dateien.liste), kont = basename(d.dateien.kontakte || "");
  const sub = (titel, n, why) => `<div class="cl-sub">${titel} <span class="cnt">${n}</span> ${why ? `<span class="why">${why}</span>` : ""}</div>`;
  // A · Portal von Hand
  const aKeys = [...hand.map((h) => h.key), ...warn.map((w) => w.key)];
  let aHtml = `<p class="hint">Was der Import nicht kann: E-Mails umschreiben und Austritte löschen. Jeder Punkt hat einen Link direkt zur Person. <a class="plink" href="${ausgabeLink(liste)}" target="_blank" rel="noopener">${ic("file", "sm")}Liste zum Drucken</a></p>`;
  if (schluessel.length) aHtml += sub("E-Mail im Portal nachführen", schluessel.length, "— sonst legt der Import ein Duplikat an") + `<ul class="checklist">${schluessel.map((h) => clItem(h.key, `${h.name} (${h.fg})`, h.detail, plink(h.portal_url, "Im Portal öffnen"))).join("")}</ul>`;
  if (austritte.length) aHtml += sub("Austritte im Portal löschen", austritte.length, "— nicht mehr in Fairgate. Das Portal kennt kein Deaktivieren: Person öffnen, «Helfer:in löschen» (unwiderruflich, vergangene Einsätze verschwinden aus der Statistik)") + `<ul class="checklist kompakt">${austritte.map((h) => clItem(h.key, `${h.name} (${h.fg})`, h.detail, plink(h.portal_url, "Im Portal öffnen"))).join("")}</ul>`;
  if (warn.length) aHtml += sub("Von Hand prüfen", warn.length, "") + `<ul class="checklist">${warn.map((w) => clItem(w.key, `${w.k}`, w.t)).join("")}</ul>`;
  if (!aKeys.length) aHtml = `<p class="hint">Nichts zu tun — keine E-Mail-Änderungen und keine Austritte.</p>`;
  // B · Import
  const bKeys = nImport ? ["imp"] : [];
  let bHtml = nImport ? "" : `<p class="hint">Keine Neueintritte oder Korrekturen — dieses Mal ist kein Import nötig.</p>`;
  if (nImport) {
    const pfad = d.dateien.import;
    const vorschau = d.import_vorschau || [];
    bHtml += `<div class="importcard">
      <div class="importhead">
        <div><div class="importtitle">${esc(imp)}</div><div class="sub">${d.neueintritte} Neueintritte · ${d.korrekturen} Korrekturen · liegt im Ordner «Ausgabe»</div></div>
        <a class="btn primary" href="${ausgabeLink(imp)}">${ic("download")}Import-Datei herunterladen</a>
      </div>
      <div class="importpfad num" title="Vollständiger Pfad">${esc(pfad)}</div>
      <ol class="howto compact">
        <li><span class="n">1</span><div><b>Herunterladen</b><span>Knopf oben — die Datei landet im Downloads-Ordner (oder direkt aus dem Ordner «Ausgabe» nehmen).</span></div></li>
        <li><span class="n">2</span><div><b>Im Helferportal anmelden</b><span>Menü <b>Helfende</b> → <b>Import</b>. ${plink(`https://app.helfereinsatz.ch/${esc(orgSlug())}/de/helpers`, "Helfende im Portal öffnen")}</span></div></li>
        <li><span class="n">3</span><div><b>Datei wählen und hochladen</b><span>Das Portal erkennt bestehende Personen an Vorname + Nachname + E-Mail und aktualisiert nur die gefüllten Felder; neue Personen werden angelegt. Es wird nichts gelöscht.</span></div></li>
        <li><span class="n">4</span><div><b>Hier abhaken</b><span>Erst danach zur Kontrolle — sie prüft, ob der Import angekommen ist.</span></div></li>
      </ol>
      ${vorschau.length ? `<div class="begr" id="begr">
        <div class="begr-head"><div><b>Was in der Datei steht — und warum</b><span class="sub">Zeile = Zeile in Excel (Kopfzeile ist 1). Zum Nachlesen auch als Datei: <a class="plink" href="${ausgabeLink(d.dateien.begruendung || "")}" target="_blank" rel="noopener">${ic("file", "sm")}${esc(basename(d.dateien.begruendung || ""))}</a></span></div>
          <input type="search" id="begr-suche" placeholder="Person oder Grund suchen" aria-label="In der Import-Vorschau suchen"></div>
        <div class="chips" id="begr-chips"></div>
        <div class="tablewrap begr-wrap"><table class="data" id="tab-begr"><thead><tr>
          <th class="r" data-sort="zeile">Zeile<span class="sorticon">↕</span></th><th data-sort="name">Person<span class="sorticon">↕</span></th><th data-sort="art">Art<span class="sorticon">↕</span></th><th data-sort="kategorie">Warum<span class="sorticon">↕</span></th><th>Begründung und was geschrieben wird</th></tr></thead><tbody id="tab-begr-body"></tbody></table></div>
        <div class="tfoot" id="tfoot-begr"></div></div>` : ""}
    </div>`;
    bHtml += `<ul class="checklist">${clItem("imp", `Import-Datei im Portal hochgeladen`, `${nImport} Zeilen — Neueintritte werden angelegt, Korrekturen aktualisiert.`)}</ul>`;
  }
  // C · Klärfälle
  const cKeys = [...d.klaerliste.map((_, i) => `k:${i}`), ...befunde.map((b) => b.key)];
  let cHtml = cKeys.length ? `<p class="hint">Erst nach dem Import, damit die Import-Datei gültig bleibt. Jeden Punkt aufklappen: Was trifft zu? — dann erscheint nur die Anleitung für diesen Fall.</p>` : `<p class="hint">Keine Klärfälle — nichts zu entscheiden.</p>`;
  if (d.klaerliste.length) cHtml += (befunde.length ? sub("Offene Fragen", d.klaerliste.length, "") : "") + `<ul class="checklist">${d.klaerliste.map((kf, i) => klaerItem(`k:${i}`, kf)).join("")}</ul>`;
  if (befunde.length) cHtml += sub("Doppelte Accounts", befunde.length, "— zwei Accounts, eine Person oder eine Familie?") + `<ul class="checklist">${befunde.map((b) => klaerItem(b.key, b)).join("")}</ul>`;
  const hinweise = d.hinweise || [];
  if (hinweise.length) cHtml += `<details class="more"><summary>Info · ${hinweise.length} Hinweise — keine Handarbeit nötig, aber gut zu wissen</summary><ul class="checklist">${hinweise.map((h, i) => klaerItem(`i:${i}`, h, false)).join("")}</ul></details>`;
  const abw = d.kontakt_abweichungen || [];
  if (abw.length) cHtml += `<details class="more"><summary>Info · ${abw.length} Kontaktdaten weichen ab (Portal ≠ Fairgate) — keine Handarbeit nötig</summary><p class="hint" style="margin:8px 0">Die Portal-Adresse ist die vom Mitglied selbst gewählte Login-Adresse. Falls Fairgate veraltet ist, dort nachführen: <a class="plink" href="${ausgabeLink(kont)}">${ic("download", "sm")}${esc(kont)}</a></p><ul class="checklist">${abw.slice(0, 50).map((a) => `<li><span></span><div class="t"><b>${esc(a.name)} (${esc(a.fg)})</b><span>Portal ${esc(a.portal_mail)} · Fairgate ${esc(a.fairgate_mail)}</span></div><div class="a">${plink(a.portal_url)}</div></li>`).join("")}</ul></details>`;
  // Phasen: nur eine offen — die erste mit offenen Punkten, oder die gemerkte
  const phasen = [{ id: "A", titel: "Im Portal von Hand", keys: aKeys, html: aHtml }, { id: "B", titel: "Import-Datei ins Portal hochladen", keys: bKeys, html: bHtml }, { id: "C", titel: "Klärfälle — hier entscheidest du", keys: cKeys, html: cHtml }];
  const ersteOffene = phasen.find((p) => p.keys.some((k) => !W.checks[k]));
  const offenId = W.phase && phasen.some((p) => p.id === W.phase) ? W.phase : (ersteOffene ? ersteOffene.id : "C");
  $("wiz-3-liste").innerHTML = phasen.map((p) => `<details class="phase" data-phase="${p.id}" ${p.id === offenId ? "open" : ""}><summary><span class="ph">${p.id}</span><span class="pt">${p.titel}</span><span class="cnt"></span><span class="ps"></span></summary><div class="phase-body">${p.html}</div></details>`).join("");
  if (vorschauAktiv(d)) initBegruendung(d.import_vorschau);
  aktualisiereFortschritt();
}
function vorschauAktiv(d) { return !!(d && d.import_vorschau && d.import_vorschau.length && $("tab-begr-body")); }
// ---- Begründungstabelle zur Import-Datei: Chips nach Grund, Suche, sortierbar ----
const B = { chip: "alle", suche: "", sort: { key: "zeile", dir: "asc" } };
function initBegruendung(zeilen) {
  B.chip = "alle"; B.suche = ""; B.sort = { key: "zeile", dir: "asc" };
  const zaehler = {};
  zeilen.forEach((z) => { zaehler[z.kategorie] = (zaehler[z.kategorie] || 0) + 1; });
  const kats = Object.keys(zaehler).sort((a, b) => zaehler[b] - zaehler[a]);
  $("begr-chips").innerHTML = [`<button class="chip" data-kat="alle" aria-pressed="true">Alle <span class="c">${zeilen.length}</span></button>`]
    .concat(kats.map((k) => `<button class="chip" data-kat="${esc(k)}" aria-pressed="false">${esc(k)} <span class="c">${zaehler[k]}</span></button>`)).join("");
  $("begr-chips").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    B.chip = c.dataset.kat;
    $("begr-chips").querySelectorAll(".chip").forEach((x) => x.setAttribute("aria-pressed", String(x === c)));
    renderBegruendung(zeilen);
  }));
  $("begr-suche").addEventListener("input", (e) => { B.suche = e.target.value.trim().toLowerCase(); renderBegruendung(zeilen); });
  bindeSort("tab-begr", B.sort, () => renderBegruendung(zeilen));
  renderBegruendung(zeilen);
}
function renderBegruendung(zeilen) {
  const q = B.suche;
  let liste = zeilen.filter((z) => (B.chip === "alle" || z.kategorie === B.chip)
    && (!q || `${z.name} ${z.email} ${z.grund} ${z.aenderungen} ${z.kategorie}`.toLowerCase().includes(q)));
  const k = B.sort.key, dir = B.sort.dir === "asc" ? 1 : -1;
  liste = liste.slice().sort((a, b) => (k === "zeile" ? a.zeile - b.zeile : String(a[k]).localeCompare(String(b[k]), "de") || a.zeile - b.zeile) * dir);
  markiereSort("tab-begr", B.sort);
  $("tab-begr-body").innerHTML = liste.map((z) => `<tr><td class="r num">${z.zeile}</td><td><b>${esc(z.name)}</b><div class="sub">${esc(z.email)}</div></td><td><span class="typ ${z.art === "Neueintritt" ? "mitglied" : ""}">${esc(z.art)}</span></td><td>${esc(z.kategorie)}</td><td class="sub"><span style="color:var(--ink)">${esc(z.grund || "")}</span>${z.aenderungen ? `<div>Schreibt: ${esc(z.aenderungen)}</div>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="5" class="sub" style="text-align:center;padding:18px">Nichts gefunden.</td></tr>`;
  $("tfoot-begr").innerHTML = `<span>${liste.length} von ${zeilen.length} Zeilen</span><span style="margin-left:auto">Die Datei wird in dieser Reihenfolge importiert; leere Zellen ändern nichts.</span>`;
}
function aktualisiereFortschritt() {
  const boxen = [...document.querySelectorAll("#wiz-3-liste input[data-key]")];
  const erledigt = boxen.filter((cb) => cb.checked).length;
  document.querySelectorAll("#wiz-3-liste details.phase").forEach((ph) => {
    const b = [...ph.querySelectorAll("input[data-key]")], d = b.filter((x) => x.checked).length;
    const cnt = ph.querySelector("summary .cnt"), ps = ph.querySelector("summary .ps");
    cnt.textContent = b.length ? `${d} / ${b.length}` : "nichts zu tun"; cnt.classList.toggle("ok", d === b.length);
    ps.textContent = d === b.length ? "erledigt" : `${b.length - d} offen`; ps.classList.toggle("ok", d === b.length);
  });
  $("wiz-3-progress").style.width = boxen.length ? `${Math.round(erledigt / boxen.length * 100)}%` : "100%";
  $("wiz-3-progress-text").textContent = boxen.length ? `${erledigt} von ${boxen.length} Punkten erledigt` : "Nichts abzuarbeiten — direkt zur Kontrolle.";
  $("wiz-btn-3").disabled = erledigt < boxen.length;
}
function oeffnePhase(id) {
  document.querySelectorAll("#wiz-3-liste details.phase").forEach((ph) => { ph.open = ph.dataset.phase === id; });
  W.phase = id; wizSpeichern();
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
      W.checks = {}; W.abgleich = null; W.runId = null; wizZeige(FERTIG);
      toast("Alles synchron — Abgleich abgeschlossen.");
    } else {
      const o = d.offen;
      el.innerHTML = `<div class="statusline err">${ic("alert")}<span><b>Noch nicht synchron:</b> ${o.handarbeit} Handarbeit · ${o.neueintritte} Neueintritte · ${o.korrekturen} Korrekturen · ${o.klaerliste} Klärfälle offen.</span></div>
        <p class="hint" style="margin:10px 0 0">Typische Gründe: Import-Datei noch nicht hochgeladen, ein Punkt im Portal noch nicht erledigt, oder das Portal braucht einen Moment. Die Checkliste wird mit dem aktuellen Stand neu aufgebaut — bereits Erledigtes bleibt abgehakt.</p>
        <div class="wiz-actions" style="margin-top:12px"><button class="btn primary" id="wiz-btn-nochmal">Checkliste aktualisieren</button><button class="btn" id="wiz-btn-kontrolle2">${ic("refresh")}Nochmals prüfen</button></div>`;
      $("wiz-btn-nochmal").addEventListener("click", () => { W.abgleich = { ...W.abgleich, ...d, dateien: W.abgleich.dateien }; renderChecklist(); wizZeige(2); });
      $("wiz-btn-kontrolle2").addEventListener("click", wizKontrolle);
    }
  } catch (e) {
    zeigeFehler("kontrolle", e.message);
    el.innerHTML = `<div class="statusline err">${ic("alert")}<span>${esc(e.message)}</span></div><div class="wiz-actions" style="margin-top:12px"><button class="btn primary" id="wiz-btn-kontrolle3">${ic("refresh")}Nochmals versuchen</button></div>`;
    $("wiz-btn-kontrolle3").addEventListener("click", wizKontrolle);
  }
}
function wizNeu() { W.maxStep = 0; W.portalOk = false; W.checks = {}; W.abgleich = null; W.runId = null; W.ack = false; W.dateiName = ""; wizSpeichern(); $("wiz-2-plausi").innerHTML = ""; $("dropzone").innerHTML = `${ic("upload")}<br>Excel-Export aus Fairgate <b>hierher ziehen</b> oder klicken`; wizZeige(0); }

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
    case "abgleich": return { a: "Mitglieder-Abgleich", d: `${e.geprueft} geprüft · ${e.neueintritte} Neueintritte · ${e.korrekturen} Korrekturen · ${e.handarbeit} Handarbeit${e.vorfragen ? ` · ${e.vorfragen} Vorfragen` : ""}${e.abweichungen != null ? ` · ${e.abweichungen} Info` : ""}${dateien ? " · " + dateien : ""}` };
    case "entscheide": return { a: "Vorfragen beantwortet", d: `${e.beantwortet} Antworten${e.geloescht ? ` · ${e.geloescht} wieder offen` : ""} · Import-Datei neu erzeugt` };
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
  document.querySelectorAll(".navitem, #btn-einstellungen").forEach((b) => b.addEventListener("click", () => {
    let ziel = b.dataset.panel;
    if (ziel === "p-kontingent") { try { const m = localStorage.getItem("hc2-ansicht"); if (HELFENDE_ANSICHTEN.includes(m)) ziel = m; } catch (e) { /* optional */ } }
    zeigePanel(ziel);
  }));
  document.querySelectorAll(".subtabs [data-sub]").forEach((b) => b.addEventListener("click", () => zeigeSub(b.dataset.sub)));
  $("btn-abrufen").addEventListener("click", () => abrufen(false));
  $("tab-mitglieder-body").addEventListener("click", (e) => {
    const start = e.target.closest("[data-fam-start]"); if (start) { e.stopPropagation(); S.k.familieEntwurf = { basis: start.dataset.famStart, weitere: [] }; renderTabelleK(); return; }
    if (e.target.closest("[data-fam-abbruch]")) { e.stopPropagation(); S.k.familieEntwurf = null; renderTabelleK(); return; }
    const weg = e.target.closest("[data-fam-weg]"); if (weg) { e.stopPropagation(); S.k.familieEntwurf.weitere = S.k.familieEntwurf.weitere.filter((x) => x !== weg.dataset.famWeg); renderTabelleK(); return; }
    const copy = e.target.closest("[data-copy]"); if (copy) { e.stopPropagation(); navigator.clipboard && navigator.clipboard.writeText(copy.dataset.copy).then(() => toast(`«${copy.dataset.copy}» kopiert.`)); return; }
    if (e.target.closest(".famact")) e.stopPropagation();
  }, true);
  $("tab-mitglieder-body").addEventListener("change", (e) => {
    const inp = e.target.closest("[data-fam-suche]"); if (!inp || !S.k.familieEntwurf) return;
    const mm = inp.value.match(/(\d{1,8})/); const fg = mm ? `FG-${mm[1]}` : inp.value.trim();
    const r = kontingentZeilen().find((x) => x.fg === fg || x.name.toLowerCase() === inp.value.trim().toLowerCase());
    if (!r || r.fg === S.k.familieEntwurf.basis) { toast("Kein Mitglied mit dieser Nummer gefunden."); return; }
    if (!S.k.familieEntwurf.weitere.includes(r.fg)) S.k.familieEntwurf.weitere.push(r.fg);
    renderTabelleK();
  });
  document.querySelectorAll(".seg [data-sicht]").forEach((b) => b.addEventListener("click", () => setSicht(b.dataset.sicht)));
  document.querySelectorAll(".seg.ansicht [data-ansicht]").forEach((b) => b.addEventListener("click", () => { zeigePanel(b.dataset.ansicht); if (b.dataset.ansicht === "p-helfende") renderTabelleH(); else renderTabelleK(); }));

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
  bindeChips($("dq-gruppen"));

  // Geführter Abgleich
  $("wiz-btn-start").addEventListener("click", wizStart);
  $("wiz-btn-2").addEventListener("click", () => { renderChecklist(); wizZeige(2); });
  $("wiz-btn-3").addEventListener("click", () => { $("wiz-4-ergebnis").innerHTML = `<div class="wiz-actions" style="margin-top:0"><button class="btn primary" id="wiz-btn-kontrolle">${ic("refresh")}Kontrolle starten</button></div>`; $("wiz-btn-kontrolle").addEventListener("click", wizKontrolle); wizZeige(3); });
  $("wiz-btn-kontrolle").addEventListener("click", wizKontrolle);
  $("wiz-btn-neu").addEventListener("click", wizNeu);
  document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => wizZeige(Number(b.dataset.goto))));
  $("wiz-steps").addEventListener("click", (e) => { const li = e.target.closest("li[data-step]"); if (li) wizTabKlick(li); });
  $("wiz-steps").addEventListener("keydown", (e) => { const li = e.target.closest("li[data-step]"); if (li && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); wizTabKlick(li); } });
  // Abhaken ohne Neuaufbau der Liste (kein Scroll-Sprung, Fokus bleibt): nur Zähler/Fortschritt nachführen.
  $("wiz-3-liste").addEventListener("change", (e) => {
    const cb = e.target.closest("input[data-key]"); if (!cb) return;
    W.checks[cb.dataset.key] = cb.checked; wizSpeichern();
    cb.closest("li").classList.toggle("done", cb.checked);
    aktualisiereFortschritt();
    const ph = cb.closest("details.phase");
    if (ph && cb.checked && ![...ph.querySelectorAll("input[data-key]")].some((x) => !x.checked)) {
      const naechste = ph.nextElementSibling; if (naechste && naechste.classList.contains("phase")) { oeffnePhase(naechste.dataset.phase); toast(`Abschnitt ${ph.dataset.phase} erledigt — weiter mit ${naechste.dataset.phase}.`); }
    }
  });
  $("wiz-3-liste").addEventListener("click", (e) => {
    const b = e.target.closest("button.opt"); if (!b) return;
    const key = b.dataset.wahl, i = Number(b.dataset.i);
    W.wahl[key] = W.wahl[key] === i ? null : i; wizSpeichern();
    const kf = b.closest("details.kf"), li = b.closest("li");
    const quelle = W.abgleich && (key.startsWith("k:") ? W.abgleich.klaerliste[Number(key.slice(2))] : key.startsWith("i:") ? W.abgleich.hinweise[Number(key.slice(2))] : portalBefunde(W.abgleich).find((x) => x.key === key));
    if (quelle) { W.offen[key] = true; li.outerHTML = klaerItem(key, quelle, !key.startsWith("i:")); }
  });
  $("wiz-3-liste").addEventListener("toggle", (e) => {
    const t = e.target;
    if (t.classList.contains("phase")) { if (t.open) document.querySelectorAll("#wiz-3-liste details.phase").forEach((ph) => { if (ph !== t) ph.open = false; }); if (t.open) { W.phase = t.dataset.phase; wizSpeichern(); } }
    else if (t.classList.contains("kf")) W.offen[t.dataset.kf] = t.open;
  }, true);
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
  if (gespeichert && gespeichert.step >= 1 && gespeichert.step <= 3 && gespeichert.runId) {
    // Läuft der Server noch, hat er den letzten Abgleich im Speicher: dann direkt dort weitermachen.
    let wieder = null;
    if (S.daten && S.daten.letzter_abgleich) {   // nur fragen, wenn der Server überhaupt einen hat (kein 404-Rauschen)
      try { const d = await holeJson("/api/abgleich/letzter"); if (wizRunId(d) === gespeichert.runId) wieder = d; } catch (e) { wieder = null; }
    }
    if (wieder) {
      W.abgleich = wieder;
      $("dropzone").innerHTML = ic("check") + `<br><b>${esc(W.dateiName || "Fairgate-Export")}</b> geladen<span class="hint">Andere Datei: klicken oder hierher ziehen</span>`;
      renderPlausi(wieder);
      W.portalOk = geladen();
      $("wiz-1-status").className = "statusline ok"; $("wiz-1-status").innerHTML = ic("check") + `<span><b>${S.daten.alle_accounts.length} Accounts</b> aus dem Portal · Stand ${esc(S.daten.stand)}</span>`;
      if (gespeichert.step >= 2) renderChecklist();
      W.maxStep = gespeichert.step;
      wizZeige(Math.max(gespeichert.step, 1));
      pruefeSchritt1();
      toast(`Abgleich fortgesetzt bei Schritt ${gespeichert.step}.`);
    } else if (gespeichert.step >= 2 && gespeichert.dateiName) {
      $("wiz-letzter").insertAdjacentHTML("beforeend", `<span class="l">Unterbrochen</span><span>Ein Abgleich mit «${esc(gespeichert.dateiName)}» war in Schritt ${gespeichert.step}. Das Cockpit wurde seither neu gestartet — denselben Export in Schritt 1 nochmals laden, die Häkchen bleiben erhalten.</span>`);
    }
  }
});
