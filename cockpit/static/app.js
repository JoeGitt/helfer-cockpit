// Frontend für Helfer-Cockpit 2. Läuft nur gegen 127.0.0.1 — kein externer Zugriff,
// kein Framework, kein CDN. Alle Daten kommen per fetch() von der lokalen JSON-API.

let sichtAktuell = "saison";       // "saison" | "halbjahr"
let filterAktuell = "alle";        // "alle" | "erfuellt" | "auf_kurs" | "saeumig" | "zweitaccount"
let sucheAktuell = "";
let mitgliederAktuell = [];
let regelnAktuell = null;
let letzterStand = null;

const TYP_LABEL = {
  mitglied: "Mitglieds-Account",
  zweitaccount: "Zweitaccount",
  freiwillig: "Freiwillig",
  unbekannt: "Unbekannt",
  unklassifiziert: "Unklassifiziert",
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtNum(n) {
  n = Number(n) || 0;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

// Mehrere Fehlerquellen können gleichzeitig aktiv sein (z. B. Regeln-Laden
// schlägt fehl, Stand-Laden gelingt danach) — eine erfolgreiche Quelle darf
// den Banner einer anderen, weiterhin fehlgeschlagenen Quelle NICHT stumm
// überschreiben. Darum je Quelle ein Eintrag, Banner zeigt alle aktiven.
const fehlerQuellen = new Map();

function zeigeFehler(quelle, msg) {
  if (msg) {
    fehlerQuellen.set(quelle, msg);
  } else {
    fehlerQuellen.delete(quelle);
  }
  const el = document.getElementById("fehler-banner");
  if (fehlerQuellen.size) {
    el.textContent = "⚠ " + [...fehlerQuellen.values()].join("  ·  ");
    el.hidden = false;
  } else {
    el.hidden = true;
    el.textContent = "";
  }
}

let _hinweisTimer = null;
function zeigeHinweis(msg) {
  const el = document.getElementById("hinweis-banner");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(_hinweisTimer);
  _hinweisTimer = setTimeout(() => { el.hidden = true; }, 6000);
}

// ---------------------------------------------------------------- Laden ----

// Holt JSON von der lokalen API und wirft bei Transportfehlern (Server nicht
// erreichbar, Nicht-2xx-Status) einen Error mit verständlicher deutscher
// Meldung — nie ein stilles Scheitern. Nutzt d.fehler aus der Antwort, wenn
// vorhanden, sonst einen generischen Text mit Status/URL.
async function holeJson(url, optionen) {
  let antwort;
  try {
    antwort = await fetch(url, optionen);
  } catch (netzwerkFehler) {
    throw new Error(`Server nicht erreichbar (${url}) — läuft das Cockpit noch?`);
  }
  let daten = null;
  try {
    daten = await antwort.json();
  } catch (parseFehler) {
    daten = null;
  }
  if (!antwort.ok) {
    const meldung = (daten && daten.fehler) ? daten.fehler : `Serverfehler ${antwort.status} bei ${url}.`;
    throw new Error(meldung);
  }
  return daten;
}

async function ladeStand() {
  try {
    const d = await holeJson("/api/stand");
    zeigeFehler("stand-transport", "");
    anwenden(d);
  } catch (err) {
    zeigeFehler("stand-transport", "Stand konnte nicht geladen werden: " + err.message);
  }
}

function knopfDeaktivieren(state) {
  const b = document.getElementById("btn-abruf");
  b.disabled = state;
  b.textContent = state ? "… lädt" : "↻ Daten neu abrufen";
}

async function abrufen() {
  knopfDeaktivieren(true);
  try {
    const d = await holeJson("/api/abruf", { method: "POST" });
    zeigeFehler("abruf-transport", "");
    anwenden(d);
    ladeProtokoll();
  } catch (err) {
    zeigeFehler("abruf-transport", "Abruf fehlgeschlagen: " + err.message);
  } finally {
    knopfDeaktivieren(false);
  }
}

function anwenden(d) {
  letzterStand = d;
  mitgliederAktuell = d.mitglieder || [];
  renderKennzahlen(d.kennzahlen, d.stand, d.fehler);
  renderTabelle();
  renderHinweise(d.hinweise || []);
  renderBericht(d);
  aktualisiereAbgleichHelferStatus(d);
}

// ------------------------------------------------------------ Kennzahlen ----

function renderKennzahlen(k, stand, fehler) {
  zeigeFehler("stand", fehler);
  const leer = !k || k.mitglieder === undefined;
  document.getElementById("kpi-erfuellt").textContent =
    leer ? "– / –" : `${k.erfuellt} / ${k.mitglieder}`;
  document.getElementById("kpi-halbjahr").textContent =
    leer ? "– / –" : `${k.halbjahr_erreicht} / ${k.mitglieder}`;
  document.getElementById("kpi-ohne-einsatz").textContent =
    leer ? "–" : fmtNum(k.ohne_einsatz);
  document.getElementById("kpi-ist-soll").textContent =
    leer ? "– / –" : `${fmtNum(k.ist_summe)} / ${fmtNum(k.soll_summe)}`;
  document.getElementById("kpi-zweitaccounts").textContent =
    leer ? "–" : fmtNum(k.zweitaccounts);
  document.getElementById("nav-kontingent").textContent = leer ? "–" : fmtNum(k.mitglieder);
  document.getElementById("nav-dq").textContent = leer ? "–" : fmtNum(k.hinweise);
  const standEl = document.getElementById("stand-anzeige");
  if (leer) {
    standEl.innerHTML = "Helfertool-API<br><b>Noch keine Daten geladen</b>";
  } else {
    standEl.innerHTML = `Helfertool-API<br><b>${fmtNum(k.mitglieder)} Mitglieder erfasst` +
      (stand ? ` · Stand ${esc(stand)}` : "") + "</b>";
  }
}

// --------------------------------------------------------- Sicht/Filter ----

function statusFeld() {
  return sichtAktuell === "saison" ? "status_saison" : "status_halbjahr";
}

function zielFuerSicht(m) {
  return sichtAktuell === "saison" ? m.soll : Number(regelnAktuell?.halbjahresziel ?? 1);
}

function setSicht(s) {
  sichtAktuell = s;
  document.getElementById("sicht-saison").setAttribute("aria-pressed", String(s === "saison"));
  document.getElementById("sicht-halbjahr").setAttribute("aria-pressed", String(s === "halbjahr"));
  document.getElementById("kontingent-meta").textContent =
    "Sicht: " + (s === "saison" ? "Saison-Soll" : "Halbjahresziel");
  document.getElementById("th-soll").textContent = s === "saison" ? "Soll" : "Ziel";
  document.getElementById("chip-auf-kurs-btn").hidden = s !== "saison";
  if (s === "halbjahr" && filterAktuell === "auf_kurs") {
    filterAktuell = "alle";
    document.querySelectorAll("#p-kontingent .chips .chip[data-filter]").forEach((c) =>
      c.setAttribute("aria-pressed", c.dataset.filter === "alle" ? "true" : "false"));
  }
  renderTabelle();
  if (letzterStand) renderBericht(letzterStand);
}

// -------------------------------------------------------------- Tabelle ----

function renderTabelle() {
  const feld = statusFeld();
  const alle = mitgliederAktuell;

  const zaehlung = { alle: alle.length, erfuellt: 0, auf_kurs: 0, saeumig: 0, zweitaccount: 0 };
  for (const m of alle) {
    if (m[feld] === "erfuellt") zaehlung.erfuellt++;
    else if (m[feld] === "auf_kurs") zaehlung.auf_kurs++;
    else if (m[feld] === "saeumig") zaehlung.saeumig++;
    if (m.accounts.some((a) => a.typ === "zweitaccount")) zaehlung.zweitaccount++;
  }
  document.getElementById("chip-alle").textContent = zaehlung.alle;
  document.getElementById("chip-erfuellt").textContent = zaehlung.erfuellt;
  document.getElementById("chip-auf-kurs").textContent = zaehlung.auf_kurs;
  document.getElementById("chip-saeumig").textContent = zaehlung.saeumig;
  document.getElementById("chip-zweitaccount").textContent = zaehlung.zweitaccount;

  const q = sucheAktuell.trim().toLowerCase();
  let gefiltert = alle.filter((m) => {
    if (filterAktuell === "erfuellt" && m[feld] !== "erfuellt") return false;
    if (filterAktuell === "auf_kurs" && m[feld] !== "auf_kurs") return false;
    if (filterAktuell === "saeumig" && m[feld] !== "saeumig") return false;
    if (filterAktuell === "zweitaccount" && !m.accounts.some((a) => a.typ === "zweitaccount")) return false;
    if (q && !(`${m.name} ${m.fg}`.toLowerCase().includes(q))) return false;
    return true;
  });

  const rang = { saeumig: 0, auf_kurs: 1, erfuellt: 2 };
  gefiltert = gefiltert.slice().sort((a, b) => {
    const r = (rang[a[feld]] ?? 3) - (rang[b[feld]] ?? 3);
    return r !== 0 ? r : a.name.localeCompare(b.name, "de-CH");
  });

  const tbody = document.getElementById("tab-mitglieder");
  tbody.innerHTML = "";
  for (const m of gefiltert) {
    const ziel = zielFuerSicht(m);
    const status = m[feld];
    const pct = ziel > 0 ? Math.min(100, (m.ist / ziel) * 100) : 100;
    const barKlasse = status === "erfuellt" ? "g" : status === "auf_kurs" ? "o" : "r";
    const statusKlasse = status === "erfuellt" ? "ok" : status === "auf_kurs" ? "warn" : "crit";
    const statusText = status === "erfuellt" ? "Erfüllt" : status === "auf_kurs" ? "Auf Kurs" : "Säumig";
    const detailId = "d-" + m.fg.replace(/[^A-Za-z0-9]/g, "");

    let istZelle = `<b>${fmtNum(m.ist)}</b>`;
    let accountsZelle = `<span class="fg">1</span>`;
    if (m.accounts.length > 1) {
      const mitgliedIst = m.accounts.find((a) => a.typ === "mitglied")?.ist ?? 0;
      const andereIst = m.ist - mitgliedIst;
      istZelle += ` <span class="fg">(${fmtNum(mitgliedIst)}+${fmtNum(andereIst)})</span>`;
      accountsZelle = `<button class="acct-badge" data-toggle="${detailId}" data-count="${m.accounts.length}" aria-expanded="false">▸ ${m.accounts.length}</button>`;
    }

    const tr = document.createElement("tr");
    tr.className = "member";
    tr.innerHTML = `
      <td><span class="name">${esc(m.name)}</span> <span class="fg">${esc(m.fg)}</span></td>
      <td>${esc((m.gruppen || []).join(", "))}</td>
      <td>${accountsZelle}</td>
      <td class="num">${fmtNum(ziel)}</td>
      <td class="num">${istZelle}</td>
      <td><span class="bar"><i class="${barKlasse}" style="width:${pct}%"></i></span></td>
      <td><span class="status ${statusKlasse}">${statusText}</span></td>`;
    tbody.appendChild(tr);

    if (m.accounts.length > 1) {
      const detail = document.createElement("tr");
      detail.className = "detail";
      detail.id = detailId;
      detail.hidden = true;
      const subrows = m.accounts.map((a) => `
        <div class="subrow">
          <span class="who">${esc(a.name)} <span class="fg">· ${TYP_LABEL[a.typ] || a.typ}</span></span>
          <span class="num">Ist ${fmtNum(a.ist)} · Soll ${fmtNum(a.soll)}</span>
          <span class="meta">${esc(m.fg)}${a.bemerkung ? " · " + esc(a.bemerkung) : ""}</span>
        </div>`).join("");
      detail.innerHTML = `<td colspan="7"><div class="subaccounts">${subrows}</div></td>`;
      tbody.appendChild(detail);
    }
  }

  document.getElementById("tab-mitglieder-status").textContent =
    `Zeilen 1–${gefiltert.length} von ${alle.length} · sortiert nach Status · ` +
    "Zusammenführung ausschliesslich über FG-Nummer";
}

// -------------------------------------------------------------- Hinweise ----

function renderHinweise(hinweise) {
  const ul = document.getElementById("dq-liste");
  ul.innerHTML = "";
  document.getElementById("dq-meta").textContent = hinweise.length
    ? `Wird bei jedem API-Abruf geprüft · ${hinweise.length} offene Hinweise`
    : "Wird bei jedem API-Abruf geprüft · keine offenen Hinweise";
  if (!hinweise.length) {
    ul.innerHTML = '<li class="leer">Keine offenen Hinweise.</li>';
    return;
  }
  const SEV = { kritisch: "crit", warnung: "warn", hinweis: "info" };
  for (const h of hinweise) {
    const li = document.createElement("li");
    let betroffeneText = "";
    if (h.betroffene && h.betroffene.length) {
      const auszug = h.betroffene.slice(0, 8);
      betroffeneText = ` — ${auszug.map(esc).join(", ")}` +
        (h.betroffene.length > auszug.length ? ` (+${h.betroffene.length - auszug.length} weitere)` : "");
    }
    li.innerHTML = `<span class="sev ${SEV[h.schweregrad] || "info"}"></span>` +
      `<span><b>${esc(h.code)}</b> ${esc(h.text)}${betroffeneText}</span>`;
    ul.appendChild(li);
  }
}

// -------------------------------------------------------------- Bericht ----

function renderBericht(d) {
  const k = d.kennzahlen || {};
  const leer = k.mitglieder === undefined;

  document.getElementById("bericht-meta").textContent = "Stand " + (d.stand || "–");

  const pct = !leer && k.soll_summe > 0 ? (k.ist_summe / k.soll_summe) * 100 : 0;
  const umfang = 263.9;
  document.getElementById("ring-progress").setAttribute(
    "stroke-dasharray", `${((pct / 100) * umfang).toFixed(1)} ${umfang}`);
  document.getElementById("ring-pct").innerHTML = `${Math.round(pct)}&nbsp;%`;
  document.getElementById("ring-sub").innerHTML = leer
    ? "Noch keine Daten geladen."
    : `${fmtNum(k.ist_summe)} geleistete von ${fmtNum(k.soll_summe)} geforderten Einsätzen.<br>` +
      `Zwischenziel Halbjahr: mind. ${fmtNum(regelnAktuell?.halbjahresziel ?? 1)} Einsatz pro Mitglied.`;

  document.getElementById("fact-erfuellt").textContent = leer ? "– / –" : `${k.erfuellt} / ${k.mitglieder}`;
  document.getElementById("fact-halbjahr").textContent = leer ? "– / –" : `${k.halbjahr_erreicht} / ${k.mitglieder}`;
  document.getElementById("fact-ohne-einsatz").textContent = leer ? "–" : fmtNum(k.ohne_einsatz);
  document.getElementById("fact-zweitaccounts").textContent = leer ? "–" : fmtNum(k.zweitaccounts);
  document.getElementById("fact-soll-konflikte").textContent =
    leer ? "–" : fmtNum(mitgliederAktuell.filter((m) => m.soll_konflikt).length);
  document.getElementById("fact-dq").textContent = leer ? "–" : fmtNum(k.hinweise);

  renderGruppenBars(leer ? 0 : (k.mitglieder ? (k.halbjahr_erreicht / k.mitglieder) * 100 : 0));
  renderWerLeistet(d.wer_leistet || {});

  document.getElementById("saeumige-titel").textContent =
    leer ? "· Auszug" : `· ${fmtNum(k.ohne_einsatz)} ${k.ohne_einsatz === 1 ? "Mitglied" : "Mitglieder"} ohne Einsatz, Auszug`;
  const tbody = document.getElementById("saeumige-auszug");
  tbody.innerHTML = "";
  const saeumige = mitgliederAktuell.filter((m) => m.ist === 0).slice(0, 10);
  if (!saeumige.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="leer">Keine Mitglieder ohne Einsatz.</td></tr>';
  }
  for (const m of saeumige) {
    const typen = [...new Set(m.accounts.map((a) => TYP_LABEL[a.typ] || a.typ))].join(", ");
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(m.name)} <span class="fg">${esc(m.fg)}</span></td>` +
      `<td>${esc((m.gruppen || []).join(", "))}</td>` +
      `<td class="num">${fmtNum(m.soll)}</td><td class="num">${fmtNum(m.ist)}</td>` +
      `<td class="fg">${esc(typen)}</td>`;
    tbody.appendChild(tr);
  }
}

function renderGruppenBars(vereinsschnitt) {
  const gruppen = {};
  for (const m of mitgliederAktuell) {
    for (const g of m.gruppen || []) {
      gruppen[g] = gruppen[g] || { total: 0, erreicht: 0 };
      gruppen[g].total++;
      if (m.status_halbjahr === "erfuellt") gruppen[g].erreicht++;
    }
  }
  const el = document.getElementById("gruppen-bars");
  const namen = Object.keys(gruppen).sort((a, b) => a.localeCompare(b, "de-CH"));
  if (!namen.length) {
    el.innerHTML = '<p class="leer">Keine Gruppendaten vorhanden.</p>';
    return;
  }
  el.innerHTML = namen.map((g) => {
    const { total, erreicht } = gruppen[g];
    const pct = total > 0 ? (erreicht / total) * 100 : 0;
    const hi = pct >= vereinsschnitt ? " hi" : "";
    return `<div class="gbar"><span>${esc(g)}</span>` +
      `<span class="track"><span class="fill${hi}" style="width:${pct}%"></span></span>` +
      `<span class="val">${erreicht} / ${total} · ${Math.round(pct)} %</span></div>`;
  }).join("");
}

function renderWerLeistet(wer) {
  const unbekannt = (wer.unbekannt || 0) + (wer.unklassifiziert || 0);
  const kategorien = [
    { label: "Mitglieder", n: wer.mitglied || 0 },
    { label: "Zweitaccounts (Eltern)", n: wer.zweitaccount || 0 },
    { label: "Freiwillige", n: wer.freiwillig || 0 },
    { label: "Unbekannte", n: unbekannt },
  ];
  const gesamt = kategorien.reduce((s, k) => s + k.n, 0);
  const el = document.getElementById("wer-leistet-bars");
  el.innerHTML = kategorien.map((k) => {
    const pct = gesamt > 0 ? (k.n / gesamt) * 100 : 0;
    const hi = k.label === "Unbekannte" ? "" : " hi";
    return `<div class="gbar"><span>${esc(k.label)}</span>` +
      `<span class="track"><span class="fill${hi}" style="width:${pct}%"></span></span>` +
      `<span class="val">${fmtNum(k.n)} · ${Math.round(pct)} %</span></div>`;
  }).join("");
  const hinweisEl = document.getElementById("wer-leistet-hinweis");
  hinweisEl.textContent = unbekannt > 0
    ? `Unbekannte sollten 0 Einsätze haben — ${fmtNum(unbekannt)} Einsätze: → Datenqualität, dort zur Umteilung gelistet.`
    : "";
}

// -------------------------------------------------------------- Abgleich ----

function aktualisiereAbgleichHelferStatus(d) {
  const el = document.getElementById("abgleich-helfer-status");
  const k = d.kennzahlen || {};
  if (k.mitglieder === undefined) {
    el.textContent = "Noch keine Daten geladen.";
  } else {
    el.innerHTML = `<span class="tick">✓</span> Automatisch über die API — ` +
      `${fmtNum(k.mitglieder)} Mitglieder erfasst${d.stand ? ", Stand " + esc(d.stand) : ""}`;
  }
}

async function fairgateHochladen(datei) {
  let r;
  try {
    r = await fetch("/api/fairgate", { method: "POST", body: await datei.arrayBuffer() });
  } catch (netzwerkFehler) {
    const meldung = "Server nicht erreichbar (/api/fairgate) — läuft das Cockpit noch?";
    zeigeFehler("fairgate", meldung);
    document.getElementById("abgleich-ergebnis").innerHTML =
      `<p class="resultlead">Fehler: ${esc(meldung)}</p>`;
    throw new Error(meldung);
  }
  const d = await r.json();
  if (!r.ok) {
    zeigeFehler("fairgate", d.fehler);
    document.getElementById("abgleich-ergebnis").innerHTML =
      `<p class="resultlead">Fehler: ${esc(d.fehler)}</p>`;
    throw new Error(d.fehler);
  }
  zeigeFehler("fairgate", "");
  renderAbgleich(d);
  ladeProtokoll();
  return d;
}

function artifactCard(titel, anzahl, beschreibung, pfad) {
  return `<div class="artifact"><div class="count num">${anzahl}</div><h3>${esc(titel)}</h3>` +
    `<p>${esc(beschreibung)}</p>` +
    `<button type="button" class="cta" data-path="${esc(pfad)}">Pfad kopieren</button>` +
    `<div class="path">${esc(pfad)}</div></div>`;
}

function renderAbgleich(d) {
  const navBadge = document.getElementById("nav-abgleich");
  const gesamt = (d.neueintritte || 0) + (d.korrekturen || 0) + (d.handarbeit || []).length;
  navBadge.hidden = false;
  navBadge.textContent = gesamt;

  let html = `<p class="resultlead"><b>${esc(d.zusammenfassung)}</b></p>`;
  if ((d.duplikat_warnungen || []).length) {
    html += `<p class="hintline">${d.duplikat_warnungen.length} Duplikat-Warnung(en) — ` +
      "nicht importiert, siehe Handarbeits-Liste.</p>";
  }
  html += '<div class="artifacts">';
  html += artifactCard("Handarbeits-Liste", (d.handarbeit || []).length,
    "Zuerst im Portal von Hand abarbeiten (Schlüssel-Änderungen, dann Austritte). Abhakbar, druckbar.",
    d.dateien.liste);
  html += artifactCard("Import-Datei (Excel)", (d.neueintritte || 0) + (d.korrekturen || 0),
    "Danach im Portal hochladen: Neueintritte und Zielwert-Korrekturen.", d.dateien.import);
  html += artifactCard("Klärliste", (d.klaerliste || []).length,
    "Mitglieder ohne erreichbare E-Mail — in Fairgate nachtragen.", d.dateien.liste);
  html += "</div>";

  const el = document.getElementById("abgleich-ergebnis");
  el.innerHTML = html;
  el.querySelectorAll("button[data-path]").forEach((btn) => {
    btn.addEventListener("click", () => kopierePfad(btn.dataset.path));
  });
}

async function kopierePfad(pfad) {
  try {
    await navigator.clipboard.writeText(pfad);
    zeigeHinweis("Pfad kopiert: " + pfad);
  } catch (e) {
    zeigeHinweis("Pfad: " + pfad);
  }
}

// --------------------------------------------------------------- Regeln ----

async function ladeRegeln() {
  try {
    regelnAktuell = await holeJson("/api/regeln");
    zeigeFehler("regeln-transport", "");
    befuelleRegelnFormular();
  } catch (err) {
    zeigeFehler("regeln-transport", "Regeln konnten nicht geladen werden: " + err.message);
  }
}

function kategorieZeileHinzufuegen(k) {
  k = k || { name: "", pflichtig: true, zielwert: 0, portal_gruppe: "" };
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="text" class="rk-name" value="${esc(k.name)}"></td>
    <td style="text-align:center"><input type="checkbox" class="rk-pflichtig" ${k.pflichtig ? "checked" : ""}></td>
    <td class="num"><input type="number" min="0" class="rk-zielwert" value="${Number(k.zielwert) || 0}"></td>
    <td><input type="text" class="rk-gruppe" value="${esc(k.portal_gruppe)}"></td>
    <td><button type="button" class="rmrow" title="Zeile entfernen">✕</button></td>`;
  tr.querySelector(".rmrow").addEventListener("click", () => tr.remove());
  document.getElementById("regeln-kategorien").appendChild(tr);
}

function befuelleRegelnFormular() {
  const tbody = document.getElementById("regeln-kategorien");
  tbody.innerHTML = "";
  (regelnAktuell.kategorien || []).forEach((k) => kategorieZeileHinzufuegen(k));
  document.getElementById("regeln-altersgrenze").value = regelnAktuell.altersgrenze;
  document.getElementById("regeln-halbjahresziel").value = regelnAktuell.halbjahresziel;
}

async function speichereRegeln(ev) {
  ev.preventDefault();
  const zeilen = [...document.querySelectorAll("#regeln-kategorien tr")];
  const kategorien = zeilen.map((tr) => ({
    name: tr.querySelector(".rk-name").value.trim(),
    pflichtig: tr.querySelector(".rk-pflichtig").checked,
    zielwert: Number(tr.querySelector(".rk-zielwert").value) || 0,
    portal_gruppe: tr.querySelector(".rk-gruppe").value.trim(),
  })).filter((k) => k.name);
  const payload = {
    kategorien,
    altersgrenze: Number(document.getElementById("regeln-altersgrenze").value) || 0,
    halbjahresziel: Number(document.getElementById("regeln-halbjahresziel").value) || 0,
  };
  const statusEl = document.getElementById("regeln-status");
  statusEl.textContent = "Speichert …";
  try {
    const r = await fetch("/api/regeln", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.fehler || "Fehler beim Speichern.");
    regelnAktuell = payload;
    statusEl.textContent = "Gespeichert.";
    zeigeFehler("regeln-speichern", "");
    zeigeHinweis("Regeln gespeichert.");
    renderTabelle();
    if (letzterStand) renderBericht(letzterStand);
  } catch (err) {
    statusEl.textContent = "Fehler: " + err.message;
    zeigeFehler("regeln-speichern", err.message);
  }
}

// ------------------------------------------------------------- Protokoll ----

async function ladeProtokoll() {
  try {
    const liste = await holeJson("/api/protokoll");
    zeigeFehler("protokoll-transport", "");
    renderProtokoll(liste);
  } catch (err) {
    zeigeFehler("protokoll-transport", "Protokoll konnte nicht geladen werden: " + err.message);
  }
}

function formatZeit(iso) {
  const dt = new Date(iso);
  if (isNaN(dt)) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(dt.getDate())}.${p(dt.getMonth() + 1)}.${dt.getFullYear()} ${p(dt.getHours())}:${p(dt.getMinutes())}`;
}

function beschreibeEintrag(e) {
  if (e.aktion === "api-abruf") return `API-Abruf: ${e.accounts} Accounts`;
  if (e.aktion === "abgleich") {
    return `Quartals-Abgleich: ${e.neueintritte} Neueintritte, ${e.korrekturen} Korrekturen, ` +
      `${e.handarbeit} Handarbeit · Dateien: ${(e.dateien || []).join(", ")}`;
  }
  if (e.aktion === "saeumigen-csv") {
    return `Säumigen-CSV (${e.sicht}): ${e.anzahl} Mitglieder · Datei ${(e.dateien || []).join(", ")}`;
  }
  const rest = Object.entries(e).filter(([k]) => !["zeit", "aktion"].includes(k))
    .map(([k, v]) => `${k}: ${v}`).join(", ");
  return `${e.aktion}${rest ? " — " + rest : ""}`;
}

function renderProtokoll(liste) {
  const ul = document.getElementById("protokoll-liste");
  ul.innerHTML = "";
  if (!liste.length) {
    ul.innerHTML = '<li class="leer">Noch keine Einträge.</li>';
    return;
  }
  for (const e of liste) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="d">${esc(formatZeit(e.zeit))}</span><span>${esc(beschreibeEintrag(e))}</span>`;
    ul.appendChild(li);
  }
}

// ------------------------------------------------------------ Säumige-CSV ----

async function saeumigenCsv() {
  try {
    const r = await fetch(`/api/export/saeumige?sicht=${encodeURIComponent(sichtAktuell)}`, { method: "POST" });
    const d = await r.json();
    if (!r.ok) { zeigeFehler("saeumigen-csv", d.fehler || "Fehler beim CSV-Export."); return; }
    zeigeFehler("saeumigen-csv", "");
    zeigeHinweis(`Säumigen-CSV erzeugt: ${d.anzahl} Mitglieder → ${d.datei}`);
    ladeProtokoll();
  } catch (err) {
    zeigeFehler("saeumigen-csv", "Säumigen-CSV fehlgeschlagen: " + String(err.message || err));
  }
}

// -------------------------------------------------------------- Wiring ----

document.querySelectorAll(".navitem").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".navitem").forEach((x) => x.removeAttribute("aria-current"));
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  t.setAttribute("aria-current", "page");
  document.getElementById(t.dataset.panel).classList.add("active");
  if (t.dataset.panel === "p-log") ladeProtokoll();
}));

document.querySelectorAll("#p-kontingent .chips .chip[data-filter]").forEach((c) => c.addEventListener("click", () => {
  document.querySelectorAll("#p-kontingent .chips .chip[data-filter]").forEach((x) => x.setAttribute("aria-pressed", "false"));
  c.setAttribute("aria-pressed", "true");
  filterAktuell = c.dataset.filter;
  renderTabelle();
}));

document.getElementById("suche-mitglieder").addEventListener("input", (e) => {
  sucheAktuell = e.target.value;
  renderTabelle();
});

document.getElementById("sicht-saison").addEventListener("click", () => setSicht("saison"));
document.getElementById("sicht-halbjahr").addEventListener("click", () => setSicht("halbjahr"));

document.getElementById("tab-mitglieder").addEventListener("click", (e) => {
  const b = e.target.closest("[data-toggle]");
  if (!b) return;
  const row = document.getElementById(b.dataset.toggle);
  const open = row.hasAttribute("hidden");
  row.toggleAttribute("hidden", !open);
  b.setAttribute("aria-expanded", String(open));
  b.textContent = (open ? "▾ " : "▸ ") + b.dataset.count;
});

document.getElementById("btn-abruf").addEventListener("click", abrufen);
document.getElementById("btn-print").addEventListener("click", () => window.print());
document.getElementById("btn-saeumige-csv").addEventListener("click", saeumigenCsv);
document.getElementById("btn-saeumige-csv-bericht").addEventListener("click", saeumigenCsv);

document.getElementById("fg-datei-waehlen").addEventListener("click", () =>
  document.getElementById("fg-datei-input").click());

document.getElementById("fg-datei-input").addEventListener("change", async (e) => {
  const datei = e.target.files[0];
  if (!datei) return;
  const status = document.getElementById("fg-datei-status");
  status.innerHTML = `<span>⏳ ${esc(datei.name)} wird hochgeladen und abgeglichen …</span>`;
  try {
    const d = await fairgateHochladen(datei);
    status.innerHTML = `<span class="tick">✓</span> ${esc(datei.name)} · ${esc(d.zusammenfassung)} ` +
      `<button class="swap" id="fg-datei-waehlen">andere Datei wählen</button>`;
  } catch (err) {
    status.innerHTML = `<span>✕ ${esc(datei.name)} — Fehler beim Abgleich</span> ` +
      `<button class="swap" id="fg-datei-waehlen">andere Datei wählen</button>`;
  }
  document.getElementById("fg-datei-waehlen").addEventListener("click", () =>
    document.getElementById("fg-datei-input").click());
  e.target.value = "";
});

document.getElementById("regeln-kategorie-hinzu").addEventListener("click", () => kategorieZeileHinzufuegen());
document.getElementById("regeln-formular").addEventListener("submit", speichereRegeln);

document.addEventListener("DOMContentLoaded", async () => {
  // Jeder Schritt fängt seine eigenen Fehler bereits intern ab (siehe
  // ladeRegeln/ladeStand/ladeProtokoll) und zeigt sie sichtbar an. Zusätzlich
  // hier je Schritt try/catch: ein Fehlschlag darf die übrigen Startaufrufe
  // nie stumm verhindern, auch nicht bei einem unerwarteten Absturz.
  try {
    setSicht("saison");
  } catch (err) {
    zeigeFehler("start-sicht", "Start fehlgeschlagen (Ansicht): " + err.message);
  }
  try {
    await ladeRegeln();
  } catch (err) {
    zeigeFehler("regeln-transport", "Regeln konnten nicht geladen werden: " + err.message);
  }
  try {
    await ladeStand();
  } catch (err) {
    zeigeFehler("stand-transport", "Stand konnte nicht geladen werden: " + err.message);
  }
  try {
    await ladeProtokoll();
  } catch (err) {
    zeigeFehler("protokoll-transport", "Protokoll konnte nicht geladen werden: " + err.message);
  }
});
