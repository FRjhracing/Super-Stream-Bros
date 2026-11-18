// Shared by Home (index.html), the Full Bracket (bracket.html) and the Active Bracket (active.html).
// Both pages talk to the same local server; a change on one page shows up on the
// other straight away (long-poll on /api/changes).
"use strict";

const STATE_NAME = { 1: "Waiting", 2: "Playing", 3: "Done", 4: "Ready", 6: "Called", 7: "Queued" };

const $ = (s) => document.querySelector(s);
const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  for (const k of kids) if (k != null) e.append(k);
  return e;
};
const display = (prefix, tag) => (prefix ? `${prefix} | ${tag}` : tag || "");
const vsText = (s) => `${s.slots[0]?.tag || "?"} vs ${s.slots[1]?.tag || "?"}`;
const isDQ = (s) => s.slots.some((x) => x.score === -1);
const hasPlayers = (s) => s.slots.length === 2 && s.slots.every((x) => x.entrantId);
const fmtClock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

// Which recording a set is on ("1", "2" or null). onStream = {"1": setId, "2": setId} from the server.
function streamOf(onStream, s) {
  for (const n of ["1", "2"]) if (onStream && onStream[n] != null && String(onStream[n]) === String(s.id)) return n;
  return null;
}
// What the two OBS outputs are called ("Recording 1"); from slotLabel in dock_config.json, so it
// can become "Stream" if the Ultimate side starts streaming. Code still calls them streams.
let SLOT = "Recording";
const slotName = (n) => `${SLOT} ${n}`;
function setSlotLabel(cfg) {
  SLOT = (cfg && cfg.slotLabel) || "Recording";
  document.querySelectorAll("[data-slot]").forEach((x) => (x.textContent = slotName(x.dataset.slot)));
}
const streamBadge = (n) => el("span", { className: `badge s${n}`, textContent: slotName(n) });

// Waiting sets (both players known) with a top-3 seed get a gold outline.
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
  if (kind === "ok") status.t = setTimeout(() => s.classList.add("hidden"), 5000);
}

// start.gg returns no sets for a minute or so while it starts or restarts a bracket (e.g. right
// after the first set is put on a recording / setup). The server then sends the last list with
// rebuilding: true; show a note and check again every few seconds until the sets are back.
let rebuildTimer = null, rebuildShown = false;
function showRebuilding(on, again) {
  clearTimeout(rebuildTimer);
  if (on) {
    status("start.gg is setting up the bracket (about a minute). Showing the last list until it's back; no need to reload. Timestamps are saved as usual.", "warn");
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
  if (on) { rateShown = true; status("start.gg rate limit reached: showing the last list, it catches up in a few seconds. Timestamps and actions still go through.", "warn"); }
  else if (rateShown) { rateShown = false; status(""); }
}

// The page reloads itself when the page files change on disk.
let uiVersion = null;
function checkUiVersion(v) {
  if (!v) return false;
  if (uiVersion === null) { uiVersion = v; return false; }
  if (v !== uiVersion && !document.querySelector("dialog[open]")) { location.reload(); return true; }
  return false;
}

// Long-poll the server; call onChange() whenever something changed (here or on the other page).
async function watchChanges(onChange) {
  if (new URLSearchParams(location.search).has("nowatch")) return;  // for headless screenshot tests
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

// ------------------------------------------------------------ dialogs (shared by both pages)
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
  <div id="rep-chars" class="char-block"></div>
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
</dialog>
<dialog id="chars-dialog">
  <div class="dlg-head"><strong>Characters</strong><button data-close>✕</button></div>
  <p class="muted small" id="chars-set"></p>
  <div id="chars-body" class="char-block"></div>
  <div class="row"><button id="chars-save" class="accent">Save</button></div>
</dialog>`);
  document.querySelectorAll("dialog [data-close]").forEach((b) => (b.onclick = () => b.closest("dialog").close()));
  document.querySelectorAll("#report-dialog .stepper button").forEach((b) => {
    b.onclick = () => {
      const i = Number(b.dataset.s) - 1;
      repScore[i] = Math.max(0, Math.min(9, repScore[i] + Number(b.dataset.d)));
      drawRep();
    };
  });
  // Names + set letter: lets the server write the result into the timestamp log.
  const names = (s) => ({ name1: display(s.slots[0].prefix, s.slots[0].tag), name2: display(s.slots[1].prefix, s.slots[1].tag),
    ...setPayload(s) });
  $("#rep-submit").onclick = async () => {
    const s = repSet, [a, b] = repScore;
    const winner = a > b ? s.slots[0] : s.slots[1];
    const chars = repPickers.map((p) => p.value());
    $("#report-dialog").close();
    // Never put on a setup? Ask which one it was played on, so the setup log still has it.
    const cur = setupOf(s);
    const pick = cur == null && dockSetups.setups.length ? setupSelect(s) : null;
    const where = cur != null ? `\nOn: ${dockSetups.setups[cur].name}` : "";
    const who = (i) => `${s.slots[i].tag}${chars[i].length ? ` (${chars[i].join(", ")})` : ""}`;
    if (!(await confirmBox(`Report ${s.round}:\n${who(0)} ${a} – ${b} ${who(1)}\nWinner: ${winner.tag}${where}`, pick))) return;
    const setup = pick && pick.querySelector("select").value !== "" ? Number(pick.querySelector("select").value) : null;
    await doAction("report", s, `Reported ${s.slots[0].tag} ${a}–${b} ${s.slots[1].tag}`,
      { entrant1: s.slots[0].entrantId, entrant2: s.slots[1].entrantId, score1: a, score2: b, ...names(s),
        setup, chars1: chars[0], chars2: chars[1], ...playerIds(s) });
    if (chars[0].length || chars[1].length) loadCharacters();  // pre-fill learns the new picks
  };
  for (const i of [0, 1]) {
    $(`#rep-dq${i + 1}`).onclick = async () => {
      const s = repSet, loser = s.slots[i];
      $("#report-dialog").close();
      if (!(await confirmBox(`DQ ${loser.tag} in ${s.round}?\n${s.slots[1 - i].tag} advances.`))) return;
      await doAction("report", s, `DQ'd ${loser.tag}`,
        { entrant1: s.slots[0].entrantId, entrant2: s.slots[1].entrantId, dqLoser: loser.entrantId, ...names(s) });
    };
  }
}

function confirmBox(text, extra = null) {
  ensureDialogs();
  return new Promise((resolve) => {
    const d = $("#confirm-dialog");
    $("#confirm-text").textContent = text;
    $("#confirm-extra").replaceChildren(...(extra ? [extra] : []));
    const done = (v) => { d.close(); resolve(v); };
    $("#confirm-yes").onclick = () => done(true);
    $("#confirm-no").onclick = () => done(false);
    d.oncancel = () => resolve(false);
    d.showModal();
  });
}

let repSet = null, repScore = [0, 0], repPickers = [];
function openReport(s) {
  ensureDialogs();
  repSet = s;
  repScore = [Math.max(0, s.slots[0].score || 0), Math.max(0, s.slots[1].score || 0)];
  $("#rep-round").textContent = `${s.round}${s.identifier ? ` · ${s.identifier}` : ""}`;
  $("#rep-n1").textContent = $("#rep-dq1n").textContent = display(s.slots[0].prefix, s.slots[0].tag);
  $("#rep-n2").textContent = $("#rep-dq2n").textContent = display(s.slots[1].prefix, s.slots[1].tag);
  repPickers = [0, 1].map((i) => charPicker(s.slots[i], startChars(s, i)));
  $("#rep-chars").replaceChildren(el("div", { className: "muted small", textContent: "Characters (for video titles; pre-filled with what they usually play)" }),
    ...repPickers.map((p) => p.node));
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

async function doReset(s) {
  if (!(await confirmBox(`Reset ${s.round}: ${vsText(s)}?\nThe result is cleared on start.gg. If later sets already started, start.gg will refuse.`))) return;
  await doAction("reset", s, `Reset ${vsText(s)}`);
}

// ------------------------------------------------------------ recordings
// Put a set on recording n ("1" or "2"): saves the timestamp first, then marks the set
// in progress on start.gg (and assigns the start.gg stream, if one is picked in ⚙).
async function putOnStream(s, n) {
  try {
    const r = await api("/api/onstream", { stream: n, ...setPayload(s), currentStreamId: s.streamId });
    if (r.already) status(`${vsText(s)} is already on ${slotName(n).toLowerCase()}.`, "ok");
    else if (r.warning) status(`${slotName(n)}: ${vsText(s)}, timestamp ${r.clock} saved. start.gg didn't update: ${r.warning}`, "error");
    else if (r.queued) status(`${slotName(n)}: ${vsText(s)} · timestamp ${r.clock} saved (start.gg update queued until it finishes setting up the bracket)`, "warn");
    else status(`${slotName(n)}: ${vsText(s)} · timestamp ${r.clock} saved`, "ok");
    return true;
  } catch (e) {
    status(`Not saved: ${e.message}`, "error");
    return false;
  }
}

// ------------------------------------------------------------ setups (named in ⚙)
// Every setup is time-stamped, recorded or not. Stream 1/2 each record one setup: putting a
// set on that setup = "Put on stream N". Pages keep these current from /api/sets or /api/bracket.
let dockSetups = { setups: [], streamSetups: {} };
let dockSetChars = {};  // setId -> {identifier, chars1, chars2} saved this tournament
function updateSetups(d) {
  if (d && Array.isArray(d.setups)) dockSetups = { setups: d.setups, streamSetups: d.streamSetups || {}, past: d.past || dockSetups.past || {} };
  if (d && d.setChars) dockSetChars = d.setChars;
}

const pname = (x) => display(x?.prefix, x?.tag) || "?";
function setPayload(s) {
  return { setId: s.id, identifier: s.identifier || "", round: s.round || "", p1: pname(s.slots[0]),
    p2: pname(s.slots[1]), e1: s.slots[0]?.entrantId, e2: s.slots[1]?.entrantId,
    startedAt: s.startedAt || null, state: s.state };
}
const playerIds = (s) => ({ pid1: s.slots[0]?.playerId, pid2: s.slots[1]?.playerId, tag1: s.slots[0]?.tag, tag2: s.slots[1]?.tag });

// Index of the setup this set is on, or null (by id, or set letter + both players: start.gg's
// "preview_" ids change when the bracket starts).
function setupOf(s) {
  const ents = new Set(s.slots.map((x) => String(x.entrantId)));
  const hit = dockSetups.setups.find((x) => x.on && (String(x.on.setId) === String(s.id) ||
    (s.identifier && x.on.identifier === s.identifier && ents.has(String(x.on.e1)) && ents.has(String(x.on.e2)))));
  return hit ? hit.index : null;
}
const setupName = (s) => { const i = setupOf(s); return i == null ? "" : dockSetups.setups[i]?.name || ""; };
const setupLabel = (x) => x.name + (x.stream ? ` · ${slotName(x.stream)}` : "");
// Button text for the two "put on" buttons ("Put on recording 1" / "On recording 1 ✓").
const putLabel = (n, on) => (on ? `On ${slotName(n).toLowerCase()} ✓` : `Put on ${slotName(n).toLowerCase()}`);

// "On setup:" choice in the report confirmation, for a set that was never put on a setup.
function setupSelect(s) {
  const sel = el("select", {},
    el("option", { value: "", textContent: "— don't know / skip —" }),
    ...dockSetups.setups.map((x) => el("option", { value: x.index, textContent: setupLabel(x) + (x.on ? ` (has ${x.on.p1} vs ${x.on.p2})` : "") })));
  // Reported before (result was reset): the setup it was logged on. The log keeps that set's
  // times; picking another setup here corrects the setup.
  const past = s && dockSetups.past?.[String(s.id)];
  if (past != null && dockSetups.setups[past]) {
    sel.value = String(past);
    return el("label", { className: "setup-pick" }, "Played on (from the first report; change it if it was wrong): ", sel);
  }
  return el("label", { className: "setup-pick" }, "Played on: ", sel);
}

async function putOnSetup(s, idx) {
  try {
    const r = await api("/api/setup", { ...setPayload(s), setup: idx, currentStreamId: s.streamId });
    const name = dockSetups.setups[idx]?.name;
    if (r.already) status(`${vsText(s)} is already on ${name}.`, "ok");
    else status(`${vsText(s)} on ${name} at ${r.clock}${r.warning ? ` (start.gg didn't update: ${r.warning})` : ""}` +
      `${r.queued ? " (start queued until start.gg finishes setting up the bracket)" : ""}`, r.warning ? "error" : r.queued ? "warn" : "ok");
    return true;
  } catch (e) {
    status(`Setup not saved: ${e.message}`, "error");
    return false;
  }
}

function openSetupPicker(s) {
  ensureDialogs();
  if (!dockSetups.setups.length) { status("No setups yet: add them in ⚙ settings.", "error"); return; }
  const d = $("#setup-dialog"), cur = setupOf(s);
  $("#setup-set").textContent = `${s.round}${s.identifier ? ` · ${s.identifier}` : ""}: ${vsText(s)}`;
  $("#setup-list").replaceChildren(...dockSetups.setups.map((x) => {
    const mine = x.index === cur;
    const busy = x.on && !mine ? `${x.on.p1} vs ${x.on.p2}${x.on.identifier ? ` (${x.on.identifier})` : ""}` : "";
    const b = el("button", { className: `${mine ? "sel" : busy ? "busy" : ""}${x.stream ? ` rec s${x.stream}` : ""}` },
      el("strong", { textContent: setupLabel(x) }),
      el("span", { className: "muted small", textContent: mine ? "this set ✓" : busy ? `now: ${busy} (ends it)` : "free" }));
    b.onclick = async () => { d.close(); if (!mine) await putOnSetup(s, x.index); };
    return b;
  }));
  const clr = $("#setup-clear");
  clr.classList.toggle("hidden", cur == null);
  if (cur != null) {
    clr.textContent = `Take off ${dockSetups.setups[cur].name}`;
    clr.onclick = async () => {
      d.close();
      try { await api("/api/setup", { action: "clear", setup: cur }); status(`Took ${vsText(s)} off ${dockSetups.setups[cur].name}`, "ok"); }
      catch (e) { status(e.message, "error"); }
    };
  }
  d.showModal();
}

// ------------------------------------------------------------ characters (for video titles)
// cast = start.gg's Ultimate list; players = start.gg player id -> {tag, top: usual characters}.
let dockCast = [], dockPlayers = {};
async function loadCharacters() {
  try { const r = await api("/api/characters"); dockCast = r.cast || []; dockPlayers = r.players || {}; } catch { /* keep */ }
}
const usual = (slot) => dockPlayers[String(slot?.playerId)]?.top || [];
const shortChar = (c) => (c === "Random Character" ? "Random" : c);

// Characters saved for this set (by id or set letter), else the player's most played one.
function savedChars(s) {
  return dockSetChars[String(s.id)] || Object.values(dockSetChars).find((x) => s.identifier && x.identifier === s.identifier) || null;
}
function startChars(s, i) {
  const saved = savedChars(s);
  if (saved) {
    const flip = saved.p1 && saved.p1 === pname(s.slots[1]) && saved.p2 !== pname(s.slots[1]);
    return [...((flip ? [saved.chars2, saved.chars1] : [saved.chars1, saved.chars2])[i] || [])];
  }
  return usual(s.slots[i]).slice(0, 1);
}

// One player's row: name, then their characters as chips (click to remove) and a small "+"
// right after them to add another (their usual ones first). Up to CHARS_MAX per player.
const CHARS_MAX = 3;
function charPicker(slot, initial) {
  let picked = initial.slice(0, CHARS_MAX);
  const chips = el("span", { className: "chips" });
  const sel = el("select", { className: "char-add" });
  const draw = () => {
    const full = picked.length >= CHARS_MAX;
    chips.replaceChildren(...picked.map((c) => {
      const b = el("button", { className: "chip", textContent: `${shortChar(c)} ✕`, title: "Remove" });
      b.onclick = (e) => { e.preventDefault(); picked = picked.filter((x) => x !== c); draw(); };
      return b;
    }));
    const mine = usual(slot).filter((c) => !picked.includes(c));
    sel.replaceChildren(el("option", { value: "", textContent: picked.length ? "+" : "+ character" }),
      ...(mine.length ? [el("optgroup", { label: "Usually plays" }, ...mine.map((c) => el("option", { value: c, textContent: shortChar(c) })))] : []),
      el("optgroup", { label: "All characters" }, ...dockCast.filter((c) => !picked.includes(c)).map((c) => el("option", { value: c, textContent: shortChar(c) }))));
    sel.title = picked.length ? "Add another character (switched mid-set)" : "Add a character";
    sel.classList.toggle("hidden", full);
    if (!full) chips.append(sel);
  };
  sel.onchange = () => { if (sel.value && picked.length < CHARS_MAX) picked.push(sel.value); draw(); };
  draw();
  const node = el("div", { className: "char-row" }, el("span", { className: "char-name", textContent: pname(slot) }), chips);
  return { node, value: () => [...picked] };
}

// "Characters…" on a set (e.g. one reported on start.gg instead of in the dock).
function openChars(s) {
  ensureDialogs();
  const pickers = [0, 1].map((i) => charPicker(s.slots[i], startChars(s, i)));
  $("#chars-set").textContent = `${s.round}${s.identifier ? ` · ${s.identifier}` : ""}: ${vsText(s)}`;
  $("#chars-body").replaceChildren(...pickers.map((p) => p.node));
  $("#chars-save").onclick = async () => {
    const [c1, c2] = pickers.map((p) => p.value());
    $("#chars-dialog").close();
    try {
      await api("/api/chars", { ...setPayload(s), ...playerIds(s), chars1: c1, chars2: c2 });
      status(`Characters saved: ${vsText(s)}`, "ok");
      loadCharacters();
    } catch (e) { status(`Characters not saved: ${e.message}`, "error"); }
  };
  $("#chars-dialog").showModal();
}

// ------------------------------------------------------------ set window (Full + Active Bracket)
// Tap a set: its actions open in a window with big buttons (touch screen). Closed by ✕, Esc, a tap
// outside, or any action (setup / report / characters then open their own window).
// ctx: { get: () => selected set or null, all: () => sets by id, on: (s) => recording "1"/"2"/null,
//        badge: (s) => node, prereq: (slot) => text, closed: () => {} }
const SET_DIALOG_HTML = `
<dialog id="set-dialog" class="set-dialog">
  <div class="dlg-head">
    <span class="sd-head"><strong id="sd-letter" class="letter"></strong><span id="sd-badge"></span><span id="sd-round" class="muted"></span></span>
    <button id="sd-close" class="sd-close" title="Close">✕</button>
  </div>
  <div id="sd-players" class="sd-players"></div>
  <p id="sd-meta" class="muted small"></p>
  <div id="sd-buttons" class="sd-buttons"></div>
</dialog>`;
function initSetDialog(onClosed) {
  if (!$("#set-dialog")) document.body.insertAdjacentHTML("beforeend", SET_DIALOG_HTML);
  const d = $("#set-dialog");
  $("#sd-close").onclick = () => d.close();
  d.onclick = (e) => { if (e.target === d) d.close(); };  // tap outside
  d.onclose = onClosed;
}
function renderSetDialog(s, ctx) {
  const d = $("#set-dialog");
  if (!d) return;
  if (!s) { if (d.open) d.close(); return; }  // the set is gone (bracket restarted): close
  const done = s.state === 3;
  $("#sd-letter").textContent = s.identifier || "";
  $("#sd-badge").replaceChildren(...[ctx.badge(s)].filter((x) => x && x !== ""));
  $("#sd-round").textContent = s.round || "";
  $("#sd-players").replaceChildren(...[0, 1].map((i) => {
    const slot = s.slots[i] || {};
    const known = !!slot.entrantId;
    const won = done && s.winnerId && String(slot.entrantId) === String(s.winnerId);
    return el("div", { className: `p${known ? "" : " tbd"}${won ? " win" : ""}` },
      el("i", { textContent: known && slot.seed ? `(${slot.seed})` : "" }),
      el("span", { textContent: known ? display(slot.prefix, slot.tag) : ctx.prereq(slot) }),
      el("b", { textContent: !known ? "" : slot.score === -1 ? "DQ" : slot.score ?? "" }));
  }));
  const saved = savedChars(s);
  const cs = saved ? [0, 1].map((i) => startChars(s, i).map(shortChar).join(", ")) : [];
  $("#sd-meta").textContent = [s.stream ? `stream: ${s.stream}` : null, !done && setupName(s) ? `setup: ${setupName(s)}` : null,
    s.station ? `station ${s.station}` : null, saved ? `characters: ${cs[0] || "?"} vs ${cs[1] || "?"}` : null].filter(Boolean).join(" · ");
  const btns = $("#sd-buttons");
  btns.replaceChildren();
  const add = (label, fn, cls = "") => {
    const b = el("button", { textContent: label, className: cls });
    b.onclick = () => { d.close(); fn(); };
    btns.append(b);
  };
  const on = ctx.on(s);
  if (done) {
    if (!isDQ(s)) add(saved ? "Characters ✓" : "Characters…", () => openChars(s));
    add("Reset result", () => doReset(s), "danger");
  } else if (hasPlayers(s)) {
    for (const n of ["1", "2"]) add(putLabel(n, on === n), () => putOnStream(s, n), on === n ? `s${n} cur` : `s${n}`);
    const setup = !on ? setupName(s) : "";
    add(setup ? `${setup} ✓` : "Put on setup…", () => openSetupPicker(s), setup ? "setup cur" : "");
    if (s.state !== 6 && s.state !== 2) add("Call", () => doAction("call", s, `Called ${vsText(s)}`));
    if (s.state !== 2) add("Start", () => doAction("start", s, `Started ${vsText(s)}`));
    add("Report…", () => openReport(s));
  }
  if (btns.children.length % 2) btns.lastElementChild.classList.add("wide");
}
