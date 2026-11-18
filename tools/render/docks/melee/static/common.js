// Shared by the main dock (index.html) and the bracket overview (bracket.html).
// Both pages talk to the same local server, so either one can put a set on stream,
// call/start/report/reset it; the server then tells the other page (long-poll on
// /api/changes) and it refreshes straight away.
"use strict";

const STATE_NAME = { 1: "Waiting", 2: "Playing", 3: "Done", 4: "Ready", 6: "Called", 7: "Queued" };

// Panel color themes. "accent" colors headings, buttons and highlights.
const THEMES = {
  "Protocol Lime": { accent: "#d1fa50", bg: "#0a0a0a", panel: "#151515" },
  "Ice": { accent: "#5cc8ff", bg: "#080b10", panel: "#111821" },
  "Magenta": { accent: "#ff4fd8", bg: "#0b080b", panel: "#191219" },
  "Ember": { accent: "#ff8a3d", bg: "#0b0907", panel: "#1a1410" },
  "Violet": { accent: "#a98bff", bg: "#09080d", panel: "#15121f" },
  "Gold": { accent: "#ffd23f", bg: "#0b0a06", panel: "#1a170c" },
  "Mono": { accent: "#e6e6e6", bg: "#0a0a0a", panel: "#161616" },
};
const DEFAULT_THEME = THEMES["Protocol Lime"];

function hexLum(hex) {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

function applyTheme(t) {
  t = { ...DEFAULT_THEME, ...(t || {}) };
  const r = document.documentElement.style;
  r.setProperty("--accent", t.accent);
  r.setProperty("--accent-ink", hexLum(t.accent) > 0.35 ? "#0a0a0a" : "#ffffff");
  r.setProperty("--bg", t.bg);
  r.setProperty("--panel", t.panel);
  r.setProperty("--line", `color-mix(in srgb, ${t.accent} 18%, ${t.panel})`);
  // Bracket overview set boxes: own color if picked in ⚙, else the panel color.
  const box = t.box || t.panel;
  r.setProperty("--box", box);
  r.setProperty("--box-line", `color-mix(in srgb, ${t.accent} 18%, ${box})`);
  return t;
}

const $ = (s) => document.querySelector(s);
const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  for (const k of kids) if (k != null) e.append(k);
  return e;
};
const stockUrl = (ch, color) => `/assets/stock_icons/${encodeURIComponent(`${color || "neutral"} ${ch}`)}.png`;
const display = (prefix, tag) => (prefix ? `${prefix} | ${tag}` : tag || "");
const vsText = (s) => `${s.slots[0]?.tag || "?"} vs ${s.slots[1]?.tag || "?"}`;
const isDQ = (s) => s.slots.some((x) => x.score === -1);
const hasPlayers = (s) => s.slots.length === 2 && s.slots.every((x) => x.entrantId);

// Waiting sets (both players known, not called or started) with a top-3 seed get a gold outline,
// so the high-seed sets are easy to spot for the stream.
const TOP_SEEDS = 3;
const topSeeds = (s) => s.slots.filter((x) => x.entrantId && x.seed && x.seed <= TOP_SEEDS);
const isWaiting = (s) => [1, 4, 7].includes(s.state) && hasPlayers(s);
function markTopSeed(card, s) {
  const top = isWaiting(s) ? topSeeds(s) : [];
  if (!top.length) return;
  card.classList.add("topseed");
  card.title = `Top-${TOP_SEEDS} seed: ${top.map((x) => `${x.tag} (seed ${x.seed})`).join(", ")}`;
}

// ------------------------------------------------------------ api
async function api(path, body) {
  const opts = { headers: { "X-Dock": "1" } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function status(msg, kind = "") {
  const s = $("#status");
  if (!s) return;
  if (!msg) { s.classList.add("hidden"); return; }
  s.textContent = msg;
  s.className = `status ${kind}`;
  clearTimeout(status.t);
  if (kind === "ok") status.t = setTimeout(() => s.classList.add("hidden"), 4000);
}

// start.gg returns no sets for a minute or so while it starts or restarts a bracket (e.g. right
// after the first set is put on a setup). The server then sends the last list with
// rebuilding: true; show a note and check again every few seconds until the sets are back.
let rebuildTimer = null, rebuildShown = false;
function showRebuilding(on, again) {
  clearTimeout(rebuildTimer);
  if (on) {
    status("start.gg is setting up the bracket (about a minute). Showing the last list until it's back; no need to reload.", "warn");
    rebuildShown = true;
    rebuildTimer = setTimeout(again, 8000);
  } else if (rebuildShown) {
    rebuildShown = false;
    status("Bracket is back from start.gg", "ok");
  }
}

// The server is serving its last list because start.gg's rate limit was hit (clears by itself).
let rateShown = false;
function showRateLimited(on) {
  if (on) { rateShown = true; status("start.gg rate limit reached: showing the last list, it catches up in a few seconds. Actions still go through.", "warn"); }
  else if (rateShown) { rateShown = false; status(""); }
}

// The page reloads itself when dock files change on disk (so OBS picks up new versions).
let uiVersion = null;
function checkUiVersion(v) {
  if (!v) return false;
  if (uiVersion === null) { uiVersion = v; return false; }
  if (v !== uiVersion && !document.querySelector("dialog[open]")) { location.reload(); return true; }
  return false;
}

// Long-poll the server; call onChange() whenever the other page (or this one) changed something.
async function watchChanges(onChange) {
  // ?nowatch turns this off (headless screenshot tests wait forever on an open long-poll).
  if (new URLSearchParams(location.search).has("nowatch")) return;
  let since = null;
  for (;;) {
    try {
      const r = await api(`/api/changes${since === null ? "" : `?since=${since}`}`);
      if (since !== null && r.version !== since) await onChange(r);
      since = r.version;
    } catch {
      await new Promise((res) => setTimeout(res, 3000));  // server restarting / offline
    }
  }
}

// ------------------------------------------------------------ dialogs (injected so both pages share them)
function ensureDialogs() {
  if ($("#confirm-dialog")) return;
  document.body.insertAdjacentHTML("beforeend", `
<dialog id="report-dialog">
  <div class="dlg-head"><strong>Report set</strong><button data-close>✕</button></div>
  <p class="muted small" id="rep-round"></p>
  <div class="rep-grid">
    <span id="rep-n1"></span>
    <div class="stepper"><button data-s="1" data-d="-1">−</button><b id="rep-s1">0</b><button data-s="1" data-d="1">+</button></div>
    <span id="rep-n2"></span>
    <div class="stepper"><button data-s="2" data-d="-1">−</button><b id="rep-s2">0</b><button data-s="2" data-d="1">+</button></div>
  </div>
  <div class="row"><button id="rep-submit" class="accent">Report to start.gg</button></div>
  <div class="row"><button id="rep-dq1" class="danger">DQ <span id="rep-dq1n"></span></button><button id="rep-dq2" class="danger">DQ <span id="rep-dq2n"></span></button></div>
</dialog>
<dialog id="confirm-dialog">
  <p id="confirm-text"></p>
  <div id="confirm-extra"></div>
  <div class="row"><button id="confirm-no">Cancel</button><button id="confirm-yes" class="accent">Yes</button></div>
</dialog>
<dialog id="setup-dialog">
  <div class="dlg-head"><strong>Put on setup</strong><button data-close>✕</button></div>
  <p class="muted small" id="setup-set"></p>
  <div id="setup-list" class="setup-list"></div>
  <div class="row"><button id="setup-clear" class="danger hidden"></button></div>
</dialog>`);
  $("#setup-dialog [data-close]").onclick = () => $("#setup-dialog").close();
  document.querySelectorAll("#report-dialog [data-close]").forEach((b) => (b.onclick = () => b.closest("dialog").close()));
  document.querySelectorAll("#report-dialog .stepper button").forEach((b) => {
    b.onclick = () => {
      const i = Number(b.dataset.s) - 1;
      repScore[i] = Math.max(0, Math.min(9, repScore[i] + Number(b.dataset.d)));
      drawRep();
    };
  });
  $("#rep-submit").onclick = async () => {
    const s = repSet, [a, b] = repScore;
    const winner = a > b ? s.slots[0] : s.slots[1];
    $("#report-dialog").close();
    // Never put on a setup? Ask which one it was played on, so the setup log still has it.
    const pick = setupOf(s) == null && dockSetups.setups.length ? setupSelect(s) : null;
    const where = setupOf(s) != null ? `\nOn setup: ${dockSetups.setups[setupOf(s)].name}` : "";
    if (!(await confirmBox(`Report ${s.round}:\n${s.slots[0].tag} ${a} – ${b} ${s.slots[1].tag}\nWinner: ${winner.tag}${where}`, pick))) return;
    await doAction("report", s, `Reported ${s.slots[0].tag} ${a}–${b} ${s.slots[1].tag}`,
      { entrant1: s.slots[0].entrantId, entrant2: s.slots[1].entrantId, score1: a, score2: b,
        ...setupPayload(s), setup: pick && pick.querySelector("select").value !== "" ? Number(pick.querySelector("select").value) : null });
  };
  for (const i of [0, 1]) {
    $(`#rep-dq${i + 1}`).onclick = async () => {
      const s = repSet, loser = s.slots[i];
      $("#report-dialog").close();
      if (!(await confirmBox(`DQ ${loser.tag} in ${s.round}?\n${s.slots[1 - i].tag} advances.`))) return;
      await doAction("report", s, `DQ'd ${loser.tag}`, { entrant1: s.slots[0].entrantId, entrant2: s.slots[1].entrantId, dqLoser: loser.entrantId, ...setupPayload(s) });
    };
  }
}

// "On setup:" picker shown in the report confirmation for a set that was never put on a setup.
function setupSelect(s) {
  const sel = el("select", {},
    el("option", { value: "", textContent: "— not recorded —" }),
    ...dockSetups.setups.map((x) => el("option", { value: x.index, textContent: x.on ? `${x.name} (has ${x.on.p1} vs ${x.on.p2})` : x.name })));
  // Best guess: the stream setup if this is the set on stream, else nothing.
  if (dockSetups.streamSetup != null && String(dockLiveSetId) === String(s.id)) sel.value = String(dockSetups.streamSetup);
  // Reported before (result was reset): the setup it was logged on. The log keeps that set's
  // times; picking another setup here corrects the setup.
  const past = dockSetups.past?.[String(s.id)];
  if (past != null && dockSetups.setups[past]) {
    sel.value = String(past);
    return el("label", { className: "setup-pick" }, "On setup (from the first report; change it if it was wrong): ", sel);
  }
  return el("label", { className: "setup-pick" }, "On setup: ", sel);
}

// Resolves true (yes), false (no) or null (Esc). labels: { yes, no } button text.
function confirmBox(text, extra = null, labels = {}) {
  ensureDialogs();
  return new Promise((resolve) => {
    const d = $("#confirm-dialog");
    $("#confirm-text").textContent = text;
    $("#confirm-extra").replaceChildren(...(extra ? [extra] : []));
    $("#confirm-yes").textContent = labels.yes || "Yes";
    $("#confirm-no").textContent = labels.no || "Cancel";
    const done = (v) => { d.close(); resolve(v); };
    $("#confirm-yes").onclick = () => done(true);
    $("#confirm-no").onclick = () => done(false);
    d.oncancel = () => resolve(null);
    d.showModal();
  });
}

let repSet = null, repScore = [0, 0];
function openReport(s, scores) {
  ensureDialogs();
  repSet = s;
  repScore = scores || [Math.max(0, s.slots[0].score || 0), Math.max(0, s.slots[1].score || 0)];
  $("#rep-round").textContent = `${s.round}${s.identifier ? ` · ${s.identifier}` : ""}`;
  $("#rep-n1").textContent = $("#rep-dq1n").textContent = display(s.slots[0].prefix, s.slots[0].tag);
  $("#rep-n2").textContent = $("#rep-dq2n").textContent = display(s.slots[1].prefix, s.slots[1].tag);
  drawRep();
  $("#report-dialog").showModal();
}
function drawRep() {
  $("#rep-s1").textContent = repScore[0];
  $("#rep-s2").textContent = repScore[1];
  $("#rep-submit").disabled = repScore[0] === repScore[1];
}

// ------------------------------------------------------------ start.gg actions
async function doAction(action, s, okMsg, extra = {}) {
  try {
    const r = await api("/api/action", { action, setId: s.id, ...extra });
    if (r.queued) status(`${okMsg}: queued, sent to start.gg once it finishes setting up the bracket`, "warn");
    else status(okMsg, "ok");
    return true;  // the server announces the change; both pages refresh from that
  } catch (e) {
    status(`${action} failed: ${e.message}`, "error");
    return false;
  }
}

// ------------------------------------------------------------ setups (named in ⚙; time-stamped for replay matching)
// Pages keep these current from /api/sets or /api/bracket.
let dockSetups = { setups: [], streamSetup: null };
let dockLiveSetId = null;
function updateSetups(d) {
  if (d && Array.isArray(d.setups)) dockSetups = { setups: d.setups, streamSetup: d.streamSetup ?? null, past: d.past || dockSetups.past || {} };
}

// Index of the setup this set is on, or null. Matches by id, or by set letter + both players
// (start.gg "preview_" ids change when the bracket starts).
function setupOf(s) {
  const ents = new Set(s.slots.map((x) => String(x.entrantId)));
  const hit = dockSetups.setups.find((x) => x.on && (String(x.on.setId) === String(s.id) ||
    (s.identifier && x.on.identifier === s.identifier && ents.has(String(x.on.e1)) && ents.has(String(x.on.e2)))));
  return hit ? hit.index : null;
}
const setupName = (s) => { const i = setupOf(s); return i == null ? "" : dockSetups.setups[i]?.name || ""; };

function setupPayload(s) {
  return { setId: s.id, identifier: s.identifier || "", round: s.round || "", p1: s.slots[0]?.tag || "?",
    p2: s.slots[1]?.tag || "?", e1: s.slots[0]?.entrantId, e2: s.slots[1]?.entrantId,
    startedAt: s.startedAt || null, state: s.state };
}

async function putOnSetup(s, idx, quiet = false) {
  try {
    const r = await api("/api/setup", { ...setupPayload(s), setup: idx });
    if (!quiet) status(r.already ? `Already on ${dockSetups.setups[idx]?.name}` :
      `${vsText(s)} on ${dockSetups.setups[idx]?.name} at ${r.clock}${r.warning ? ` (start.gg: ${r.warning})` : ""}` +
      `${r.queued ? " (start queued until start.gg finishes setting up the bracket)" : ""}`, r.warning ? "error" : r.queued ? "warn" : "ok");
    return true;
  } catch (e) {
    status(`Setup not saved: ${e.message}`, "error");
    return false;
  }
}

function openSetupPicker(s) {
  ensureDialogs();
  if (!dockSetups.setups.length) { status("No setups yet: add them in ⚙ settings (Setups).", "error"); return; }
  const d = $("#setup-dialog"), cur = setupOf(s);
  $("#setup-set").textContent = `${s.round}${s.identifier ? ` · ${s.identifier}` : ""}: ${vsText(s)}`;
  $("#setup-list").replaceChildren(...dockSetups.setups.map((x) => {
    const mine = x.index === cur;
    const busy = x.on && !mine ? `${x.on.p1} vs ${x.on.p2}${x.on.identifier ? ` (${x.on.identifier})` : ""}` : "";
    const b = el("button", { className: mine ? "sel" : busy ? "busy" : "" },
      el("strong", { textContent: x.name + (x.index === dockSetups.streamSetup ? " · stream" : "") }),
      el("span", { className: "muted small", textContent: (mine ? "this set ✓" : busy ? `now: ${busy} (ends it)` : "free") +
        (!mine && x.index === dockSetups.streamSetup ? " · goes live" : "") +
        (!mine && x.index !== dockSetups.streamSetup && String(dockLiveSetId) === String(s.id) ? " · clears the overlay" : "") }));
    b.onclick = async () => {
      d.close();
      if (mine) return;
      const ok = await putOnSetup(s, x.index);  // time-stamp first
      // The stream setup IS the stream: a set put on it goes live the same as "Put on stream"
      // (overlay loaded, start.gg stream assigned), whichever button was used.
      if (ok && x.index === dockSetups.streamSetup && String(dockLiveSetId) !== String(s.id) && typeof streamSet === "function") {
        await streamSet({ ...s, state: 2 });
      } else if (ok && x.index !== dockSetups.streamSetup && String(dockLiveSetId) === String(s.id)) {
        // The live set moved to an off-stream setup (players started elsewhere): it isn't on
        // stream any more, so the overlay is cleared.
        await clearOverlay(s, `moved to ${x.name}`);
      }
    };
    return b;
  }));
  const clr = $("#setup-clear");
  clr.classList.toggle("hidden", cur == null);
  if (cur != null) {
    clr.textContent = `Take off ${dockSetups.setups[cur].name}`;
    clr.onclick = async () => {
      d.close();
      try { await api("/api/setup", { action: "clear", setup: cur }); status(`Cleared ${dockSetups.setups[cur].name}`, "ok"); }
      catch (e) { status(e.message, "error"); }
    };
  }
  d.showModal();
}

async function doReset(s) {
  if (!(await confirmBox(`Reset ${s.round}: ${vsText(s)}?\nThe result is cleared on start.gg. If later sets already started, start.gg will refuse.`))) return;
  await doAction("reset", s, `Reset ${vsText(s)}`);
}

// ------------------------------------------------------------ profile pictures (circle crop, like Stream Updater)
const pfpCache = {};
function loadImg(src) {
  return new Promise((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = rej;
    i.src = src;
  });
}

async function makePfp(url) {
  const key = url || "default";
  if (pfpCache[key]) return pfpCache[key];
  let img;
  try {
    if (!url) throw new Error("no picture");
    // The image proxy is an /api/ route, which needs the X-Dock header; a plain <img src>
    // can't send it (that made every picture fall back to the default). Fetch it, then
    // load it from a same-origin blob URL so the canvas can still export it.
    const r = await fetch(`/api/img?url=${encodeURIComponent(url)}`, { headers: { "X-Dock": "1" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blobUrl = URL.createObjectURL(await r.blob());
    try { img = await loadImg(blobUrl); } finally { URL.revokeObjectURL(blobUrl); }
  } catch {
    img = await loadImg("/assets/default.png");
  }
  const N = 400, c = el("canvas", { width: N, height: N }), g = c.getContext("2d");
  const s = Math.max(N / img.width, N / img.height);
  const w = img.width * s, h = img.height * s;
  g.beginPath(); g.arc(N / 2, N / 2, N / 2, 0, Math.PI * 2); g.clip();
  g.drawImage(img, (N - w) / 2, (N - h) / 2, w, h);
  return (pfpCache[key] = c.toDataURL("image/png"));
}

// ------------------------------------------------------------ overlay
function blankPlayer() {
  return { entrantId: null, tag: "", prefix: "", display: "", name: "", score: 0, imageUrl: "", character: "", color: "neutral" };
}

function playerFromEntrant(e, prefs, score = 0) {
  const pref = (prefs || {})[e.tag] || {};
  return {
    entrantId: e.entrantId, tag: e.tag, prefix: e.prefix || "", display: display(e.prefix, e.tag),
    name: e.name || e.tag, score, imageUrl: e.imageUrl || "",
    character: pref.character || "", color: pref.color || "neutral",
  };
}

// Stream and overlay always agree: when the set on stream is finished (reported in the dock or
// on start.gg), the overlay is cleared like the Clear button (no names, default pictures, no
// characters, scores 0; the "Bo5" text stays). Every page calls this from its refresh; whichever
// page is open does it, and it only acts if the overlay still shows that set.
let clearingOverlay = false;
async function clearOverlayIfDone(sets) {
  if (dockLiveSetId == null || clearingOverlay) return false;
  const s = (sets || []).find((x) => String(x.id) === String(dockLiveSetId));
  if (!s || s.state !== 3) return false;
  return clearOverlay(s, "finished");
}

// Clear the overlay (like the Clear button) if it still shows set s. why: shown in the status.
async function clearOverlay(s, why) {
  if (clearingOverlay) return false;
  clearingOverlay = true;
  try {
    const st = await api("/api/state");
    if (String(st.overlay?.setId) !== String(s.id)) return false;  // already changed elsewhere
    await saveOverlay({ round: "", roundPlain: "", losersTop8: false, gameCount: st.overlay.gameCount || "",
      setId: null, p1: blankPlayer(), p2: blankPlayer() });
    dockLiveSetId = null;
    status(`${vsText(s)} ${why}: overlay cleared`, "ok");
    return true;
  } catch {
    return false;
  } finally {
    clearingOverlay = false;
  }
}

// ------------------------------------------------------------ name fitting
// OBS scales each name into a fixed box on the name plate (player1/2_name.txt: bounding box
// "name_box" from layout.json, default 273x59, "Scale to inner bounds"). Long names shrink until
// unreadable (e.g. "OAC | ApplSaucFactory"), so: keep "prefix | tag" down to 70% of normal size, else
// the tag alone down to 50%, else cut the tag with "…" at 50%. Measured with the stream font
// (the first .otf/.ttf in the dock's assets\fonts\, served as /assets/stream_font).
const NAME_FONT_PX = 48;
const KEEP_PREFIX = 0.7, MIN_SCALE = 0.5;
let nameFont = null;
async function nameMeasurer() {
  if (!nameFont) {
    nameFont = (async () => {
      let box = [273, 59];
      try {
        const st = await api("/api/state");
        if (Array.isArray(st.nameBox) && st.nameBox.length === 2) box = st.nameBox;
      } catch { /* keep the default box */ }
      try {
        const f = new FontFace("StreamName", "url(/assets/stream_font)");
        document.fonts.add(await f.load());
      } catch { /* no font file: falls back to a system font */ }
      const g = document.createElement("canvas").getContext("2d");
      g.font = `${NAME_FONT_PX}px StreamName, "Segoe UI", sans-serif`;
      const m = g.measureText("Hg");
      const lineH = (m.fontBoundingBoxAscent + m.fontBoundingBoxDescent) || NAME_FONT_PX * 1.17;
      // normal = OBS's scale for a short name (limited by box height / text height)
      return { width: (t) => g.measureText(t).width, boxW: box[0], normal: box[1] / lineH };
    })();
  }
  return nameFont;
}
async function fitName(p) {
  const full = p.display || "";
  if (!full) return "";
  const { width, boxW, normal } = await nameMeasurer();
  const scale = (t) => Math.min(normal, boxW / Math.max(1, width(t)));
  if (scale(full) >= KEEP_PREFIX * normal) return full;
  const tag = p.prefix && p.tag ? p.tag : full;  // typed-in names have no separate prefix
  if (scale(tag) >= MIN_SCALE * normal) return tag;
  let cut = tag;
  while (cut.length > 1 && scale(cut + "…") < MIN_SCALE * normal) cut = cut.slice(0, -1);
  return cut.trimEnd() + "…";
}

// Send an overlay state to the server (writes the OBS files, tells the other page).
async function saveOverlay(ov) {
  const body = { round: ov.round, roundPlain: ov.roundPlain || "", losersTop8: !!ov.losersTop8,
    gameCount: ov.gameCount, setId: ov.setId };
  for (const n of [1, 2]) {
    ov[`p${n}`].shown = await fitName(ov[`p${n}`]);  // what OBS shows (may drop the prefix)
    body[`p${n}`] = { ...ov[`p${n}`], pfp: await makePfp(ov[`p${n}`].imageUrl) };
  }
  const r = await api("/api/overlay", body);
  // The server may re-label the round for the seasonal theme ("Winners Final" -> "Survivors Final").
  if (r.overlay) Object.assign(ov, { round: r.overlay.round, roundPlain: r.overlay.roundPlain, losersTop8: r.overlay.losersTop8 });
  return r.overlay;
}

// Load a set onto the overlay and mark it on start.gg (assign our stream, start the set).
// ctx: { entrants: [...], streamId, streams } - whatever the calling page already has.
async function putOnStream(s, ctx = {}) {
  const st = await api("/api/state");
  const ov = st.overlay;
  for (const [i, slot] of s.slots.entries()) {
    let info = (ctx.entrants || []).find((e) => String(e.entrantId) === String(slot.entrantId));
    if (!info) info = await api(`/api/entrant?id=${encodeURIComponent(slot.entrantId)}`).catch(() => null);
    ov[`p${i + 1}`] = playerFromEntrant(info && info.tag ? info : { ...slot, name: slot.tag, imageUrl: "" },
      st.prefs, Math.max(0, slot.score || 0));
  }
  ov.setId = s.id;
  ov.round = s.round;              // themed name when a seasonal theme is on
  ov.roundPlain = s.roundPlain;    // start.gg's name (lets a theme switch re-label it)
  ov.losersTop8 = s.losersTop8;
  try {
    await saveOverlay(ov);
  } catch (e) {
    status(`Overlay not saved: ${e.message}`, "error");
    return null;
  }
  const streamId = ctx.streamId;
  if (streamId && String(s.streamId) !== String(streamId)) await doAction("stream", s, "Assigned to stream", { streamId });
  if (s.state !== 2) await doAction("start", s, `On stream: ${vsText(s)}`);
  else status(`On stream: ${vsText(s)}`, "ok");
  // The stream setup (picked in ⚙) gets the set too, so its replays are time-stamped like the others.
  const ss = dockSetups.streamSetup;
  if (ss != null && dockSetups.setups[ss] && setupOf(s) !== ss) await putOnSetup({ ...s, state: 2 }, ss, true);
  if (!streamId && (ctx.streams || []).length) status("Overlay loaded. Pick your stream in ⚙ settings (main dock) to also mark sets on stream in start.gg.", "");
  return ov;
}
