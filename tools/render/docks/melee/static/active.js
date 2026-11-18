// Active bracket (http://127.0.0.1:8765/active). Shared code: common.js. Data: /api/bracket.
// For each side of the bracket (Winners / Losers, per pool) it shows only the earliest round that
// still has unfinished sets, in the same set boxes as the Full Bracket. Tap a set for its window with the actions.
// Order: sets in progress first (live, playing, called), then the waiting sets in suggested call
// order: closest seeds first (the closest matches tend to run longest, so they start earliest),
// ties go to the better-seeded set. Sets from later rounds that are already ready to play are
// listed under "Ready early". Sets still waiting on a player come last, dimmed.
"use strict";

let data = null;
let entrants = [];
let selectedId = null;   // set shown in the set window

const liveId = () => (data?.overlaySetId != null ? String(data.overlaySetId) : null);
const isLive = (s) => liveId() === String(s.id) && s.state !== 3;
const seedOf = (x) => (x.entrantId && x.seed ? x.seed : null);

// Suggested call order for waiting sets (lower = call sooner).
function callKey(s) {
  const [a, b] = s.slots.map(seedOf);
  if (a == null || b == null) return [999, 999];
  return [Math.abs(a - b), Math.min(a, b)];
}
function byCallOrder(x, y) {
  const [a, b] = [callKey(x), callKey(y)];
  return a[0] - b[0] || a[1] - b[1] || (x.identifier || "").localeCompare(y.identifier || "");
}
// In progress first: live, playing, called; then waiting (call order); then sets missing a player.
function rank(s) {
  if (isLive(s)) return 0;
  if (s.state === 2) return 1;
  if (s.state === 6) return 2;
  return hasPlayers(s) ? 3 : 4;
}
const sortActive = (list) => [...list].sort((x, y) => rank(x) - rank(y) || byCallOrder(x, y));

function prereqLabel(slot, all) {
  if (slot.prereqType === "set" && all[String(slot.prereqId)]) {
    const src = all[String(slot.prereqId)];
    return `${slot.prereqPlacement === 2 ? "Loser" : "Winner"} of ${src.identifier || "?"}`;
  }
  return slot.prereqType === "bye" ? "Bye" : "TBD";
}

function badgeFor(s) {
  if (isLive(s)) return el("span", { className: "badge live", textContent: "Live" });
  if (!hasPlayers(s)) return null;
  return el("span", { className: `badge b${s.state}`, textContent: STATE_NAME[s.state] || s.state });
}

// Same small set box as the Full Bracket. Tapping it opens the set window with the actions.
function card(s, all, order) {
  const live = isLive(s);
  const empty = !hasPlayers(s);
  const c = el("div", { className: ["bset", `st-${s.state}`, live && "live", empty && "empty",
    String(s.id) === String(selectedId) && "sel"].filter(Boolean).join(" "), title: s.round });
  const right = el("span", { className: "right" });
  if (order) right.append(el("span", { className: "order", textContent: `Call #${order}`, title: "Suggested call order: closest seeds first" }));
  if (s.stream && String(s.streamId) !== String(data.streamId)) right.append(el("span", { className: "badge other", textContent: s.stream }));
  const badge = badgeFor(s);
  if (badge) right.append(badge);
  c.append(el("div", { className: "top" }, el("span", { className: "letter", textContent: s.identifier || "" }), right));
  for (const i of [0, 1]) {
    const slot = s.slots[i] || {};
    const known = !!slot.entrantId;
    c.append(el("div", { className: `p${known ? "" : " tbd"}` },
      el("span", { textContent: known ? `${slot.seed ? `(${slot.seed}) ` : ""}${display(slot.prefix, slot.tag)}` : prereqLabel(slot, all) }),
      el("b", { textContent: !known ? "" : slot.score === -1 ? "DQ" : slot.score ?? "" })));
  }
  const foot = [setupName(s), s.station ? `Station ${s.station}` : ""].filter(Boolean).join(" · ");
  if (foot) c.append(el("div", { className: "foot", textContent: foot }));
  markTopSeed(c, s);
  if (!empty) c.onclick = () => { selectedId = s.id; render(); $("#set-dialog").showModal(); };
  return c;
}

// The set window (same as the Full Bracket): closed by ✕, Esc, a tap outside, or any action.
function renderSetDialog(all) {
  const d = $("#set-dialog");
  const s = selectedId != null ? all[String(selectedId)] : null;
  if (!s || s.state === 3) { if (d.open) d.close(); return; }  // gone or finished: close
  $("#sd-letter").textContent = s.identifier || "";
  $("#sd-badge").replaceChildren(...[badgeFor(s)].filter(Boolean));
  $("#sd-round").textContent = s.round || "";
  $("#sd-players").replaceChildren(...[0, 1].map((i) => {
    const slot = s.slots[i] || {};
    const known = !!slot.entrantId;
    return el("div", { className: `p${known ? "" : " tbd"}` },
      el("i", { textContent: known && slot.seed ? `(${slot.seed})` : "" }),
      el("span", { textContent: known ? display(slot.prefix, slot.tag) : prereqLabel(slot, all) }),
      el("b", { textContent: !known ? "" : slot.score === -1 ? "DQ" : slot.score ?? "" }));
  }));
  $("#sd-meta").textContent = [s.stream ? `stream: ${s.stream}` : null, setupName(s) ? `setup: ${setupName(s)}` : null,
    s.station ? `station ${s.station}` : null].filter(Boolean).join(" · ");
  const btns = $("#sd-buttons");
  btns.replaceChildren();
  const add = (label, fn, cls = "") => {
    const b = el("button", { textContent: label, className: cls });
    b.onclick = () => { d.close(); fn(); };
    btns.append(b);
  };
  if (!hasPlayers(s)) return;
  const live = isLive(s);
  add(live ? "On stream ✓" : "Put on stream", () => streamSet(s), live ? "" : "accent");
  add(setupName(s) ? `${setupName(s)} ✓` : "Put on setup…", () => openSetupPicker(s));
  if (s.state !== 6 && s.state !== 2) add("Call", () => doAction("call", s, `Called ${vsText(s)}`));
  if (s.state !== 2) add("Start", () => doAction("start", s, `Started ${vsText(s)}`));
  add("Report…", () => openReport(s), btns.children.length % 2 === 0 ? "wide" : "");
}

// Cards for a list, numbering the waiting sets in call order.
function grid(list, all, counter) {
  return el("div", { className: "col" }, ...list.map((s) => card(s, all, isWaiting(s) && !isLive(s) ? ++counter.n : 0)));
}

function sideBlock(title, sets, all) {
  const open = sets.filter((s) => s.state !== 3);
  if (!open.length) return null;
  const r = (s) => Math.abs(s.roundNum ?? 0);
  const active = Math.min(...open.map(r));
  const now = open.filter((s) => r(s) === active);
  const early = open.filter((s) => r(s) > active && hasPlayers(s));
  const roundName = now[0]?.round || `Round ${active}`;
  const block = el("section", { className: "aside" });
  const done = sets.filter((s) => r(s) === active && s.state === 3).length;
  // "Winners" + "Winners Round 1" -> "Winners Round 1" (pool prefix kept); grand finals stand alone.
  const pre = title.includes(" · ") ? title.slice(0, title.lastIndexOf(" · ") + 3) : "";
  const heading = roundName.toLowerCase().includes(title.slice(pre.length).toLowerCase()) ? pre + roundName
    : roundName.startsWith("Grand Final") ? pre + roundName : `${title} · ${roundName}`;
  block.append(el("h2", {}, `${heading} `,el("span", { className: "muted small", textContent: `${done}/${done + now.length} done` })));
  if (!now.some((s) => hasPlayers(s) || s.state === 2)) {
    block.append(el("p", { className: "muted pad", textContent: "Waiting on results from the other side." }));
  } else {
    const counter = { n: 0 };
    const cols = el("div", { className: "cols" }, grid(sortActive(now), all, counter));
    if (early.length) {
      const col = grid(sortActive(early), all, counter);
      col.prepend(el("div", { className: "col-head", textContent: "Ready early (later rounds)" }));
      cols.append(col);
    }
    block.append(cols);
  }
  return block;
}

function groupsOf(sets) {
  const m = new Map();
  for (const s of sets) {
    const key = `${s.phaseOrder ?? 0}|${s.groupId ?? ""}`;
    if (!m.has(key)) {
      const label = [s.phase, s.group && s.group !== "1" ? `Pool ${s.group}` : null].filter(Boolean).join(" · ");
      m.set(key, { key, label, sets: [] });
    }
    m.get(key).sets.push(s);
  }
  return [...m.values()].sort((a, b) => a.key.localeCompare(b.key, undefined, { numeric: true }));
}

function render() {
  if (!data) return;
  $("#t-name").textContent = data.tournament?.name ? `${data.tournament.name} · Active` : "Active Bracket";
  const all = Object.fromEntries((data.sets || []).map((s) => [String(s.id), s]));
  const groups = groupsOf(data.sets || []).filter((g) => g.sets.some((s) => s.state !== 3));
  const multi = groups.length > 1;
  const blocks = [];
  for (const g of groups) {
    const pre = multi && g.label ? `${g.label} · ` : "";
    const w = g.sets.filter((s) => (s.roundNum ?? 0) >= 0), l = g.sets.filter((s) => (s.roundNum ?? 0) < 0);
    blocks.push(sideBlock(l.length ? `${pre}Winners` : pre + (g.label || "Bracket"), w, all));
    if (l.length) blocks.push(sideBlock(`${pre}Losers`, l, all));
  }
  const shown = blocks.filter(Boolean);
  $("#board").replaceChildren(shown.length ? el("div", { className: "asides" }, ...shown)
    : el("p", { className: "muted pad", textContent: (data.sets || []).length ? "Every set is finished." : "No sets in this event yet." }));
  const open = (data.sets || []).filter((s) => s.state !== 3 && hasPlayers(s));
  const c = (f) => open.filter(f).length;
  $("#counts").textContent = [`${c((s) => s.state === 2)} playing`, `${c((s) => s.state === 6)} called`, `${c(isWaiting)} waiting`].join(" · ");
  $("#updated").textContent = new Date(data.fetchedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  renderSetDialog(all);
}

async function streamSet(s) {
  if (!entrants.length) entrants = await api("/api/entrants").catch(() => []);
  await putOnStream(s, { entrants, streamId: data?.streamId, streams: data?.streams });
}

async function refresh(quiet = true) {
  try {
    data = await api("/api/bracket");
    if (checkUiVersion(data.uiVersion)) return;
    updateSetups(data);
    dockLiveSetId = data.overlaySetId ?? null;
    if (!data.rebuilding) clearOverlayIfDone(data.sets);
    render();
    if (!quiet && !data.rebuilding) status("");
    showRateLimited(data.rateLimited && !data.rebuilding);
    showRebuilding(data.rebuilding, () => refresh());
  } catch (e) {
    status(e.message, "error");
  }
}

async function onRemoteChange() {
  try { applyTheme((await api("/api/state")).config?.theme); } catch { /* keep theme */ }
  await refresh();
}

$("#btn-refresh").onclick = () => refresh(false);
$("#sd-close").onclick = () => $("#set-dialog").close();
$("#set-dialog").onclick = (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); };  // tap outside
$("#set-dialog").onclose = () => { selectedId = null; render(); };

(async function init() {
  try {
    ensureDialogs();
    const st = await api("/api/state");
    checkUiVersion(st.uiVersion);
    applyTheme(st.config?.theme);
    if (!st.tokenSet) {
      status("start.gg token not found (STARTGG_TOKEN). Set it, then restart the dock.", "error");
      return;
    }
    await refresh(false);
    entrants = await api("/api/entrants").catch(() => []);
    setInterval(() => { if (!document.querySelector("dialog[open]")) refresh(); }, Math.max(10, st.config?.pollSeconds || 20) * 1000);
    watchChanges(onRemoteChange);
  } catch (e) {
    status(`Dock server not reachable: ${e.message}. Is start_dock.bat running?`, "error");
  }
})();
