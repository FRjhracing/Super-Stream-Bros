// Bracket overview (second OBS dock: http://127.0.0.1:8765/bracket). Shared code: common.js.
// Shows every set of the Melee event by round, with the same status as the main dock, and
// the same actions (put on stream, call, start, report, DQ, reset). Changes made here show up
// in the main dock immediately, and the other way round (server long-poll /api/changes).
"use strict";

let data = null;          // last /api/bracket result
let entrants = [];        // for putOnStream (names, pictures)
let selectedId = null;    // set shown in the actions window
let groupKey = null;      // which bracket / pool is shown
let hideDone = false;
let view = "full";        // tab: "full" | "winners" | "losers" | "done"
try {
  hideDone = localStorage.getItem("bracket.hideDone") === "1";
  view = ["full", "winners", "losers", "done"].includes(localStorage.getItem("bracket.view")) ? localStorage.getItem("bracket.view") : "full";
} catch { /* private mode */ }

const byId = () => Object.fromEntries((data?.sets || []).map((s) => [String(s.id), s]));
const liveId = () => (data?.overlaySetId != null ? String(data.overlaySetId) : null);
const identOrder = (a, b) => (a.identifier || "").length - (b.identifier || "").length
  || (a.identifier || "").localeCompare(b.identifier || "");

function badgeFor(s) {
  if (s.state !== 3 && !hasPlayers(s)) return "";  // future set: no status until both players are in
  if (liveId() === String(s.id) && s.state !== 3) return el("span", { className: "badge live", textContent: "Live" });
  if (s.state === 3 && isDQ(s)) return el("span", { className: "badge b1", textContent: "DQ" });
  return el("span", { className: `badge b${s.state}`, textContent: STATE_NAME[s.state] || s.state });
}

// Label for a slot with no player yet: "Winner of B", "Loser of C", or a seed.
function prereqLabel(slot, sets) {
  if (slot.prereqType === "set" && sets[String(slot.prereqId)]) {
    const src = sets[String(slot.prereqId)];
    return `${slot.prereqPlacement === 2 ? "Loser" : "Winner"} of ${src.identifier || "?"}`;
  }
  if (slot.prereqType === "bye") return "Bye";
  return "TBD";
}

function groupsOf(sets) {
  const m = new Map();
  for (const s of sets) {
    const key = `${s.phaseOrder ?? 0}|${s.groupId ?? ""}`;
    if (!m.has(key)) {
      const label = [s.phase, s.group && s.group !== "1" ? `Pool ${s.group}` : null].filter(Boolean).join(" · ") || "Bracket";
      m.set(key, { key, label, type: s.bracketType, sets: [] });
    }
    m.get(key).sets.push(s);
  }
  return [...m.values()].sort((a, b) => a.key.localeCompare(b.key, undefined, { numeric: true }));
}

function setCardB(s, sets) {
  const live = liveId() === String(s.id) && s.state !== 3;
  const done = s.state === 3;
  const empty = !hasPlayers(s) && !done;
  const cls = ["bset", `st-${s.state}`, live && "live", done && "done", empty && "empty",
    String(s.id) === String(selectedId) && "sel"].filter(Boolean).join(" ");
  const card = el("div", { className: cls, title: s.round });
  const right = el("span", { className: "right" });
  if (s.stream && String(s.streamId) !== String(data.streamId)) right.append(el("span", { className: "badge other", textContent: s.stream }));
  right.append(badgeFor(s));
  card.append(el("div", { className: "top" }, el("span", { className: "letter", textContent: s.identifier || "" }), right));
  for (const i of [0, 1]) {
    const slot = s.slots[i] || {};
    const known = !!slot.entrantId;
    const won = done && s.winnerId && String(slot.entrantId) === String(s.winnerId);
    const row = el("div", { className: `p${known ? "" : " tbd"}${won ? " win" : done ? " lose" : ""}` });
    row.append(el("span", { textContent: known ? display(slot.prefix, slot.tag) : prereqLabel(slot, sets) }),
      el("b", { textContent: !known ? "" : slot.score === -1 ? "DQ" : slot.score ?? "" }));
    card.append(row);
  }
  const foot = [!done && setupName(s), s.station ? `Station ${s.station}` : ""].filter(Boolean).join(" · ");
  if (foot) card.append(el("div", { className: "foot", textContent: foot }));
  markTopSeed(card, s);
  if (!empty) card.onclick = () => { selectedId = s.id; render(); $("#set-dialog").showModal(); };
  return card;
}

// Big card for the "Completed sets" tab.
function doneCard(s) {
  const card = el("div", { className: `dset${String(s.id) === String(selectedId) ? " sel" : ""}` });
  const when = s.completedAt ? new Date(s.completedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  card.append(el("div", { className: "top" },
    el("span", {}, el("span", { className: "letter", textContent: s.identifier || "" }), ` ${s.round || ""}`),
    el("span", {}, isDQ(s) ? el("span", { className: "badge b1", textContent: "DQ" }) : null, when ? ` ${when}` : "")));
  for (const slot of s.slots) {
    const won = s.winnerId && String(slot.entrantId) === String(s.winnerId);
    card.append(el("div", { className: `p ${won ? "win" : "lose"}` },
      el("span", { textContent: display(slot.prefix, slot.tag) || "?" }),
      el("b", { textContent: slot.score === -1 ? "DQ" : slot.score ?? "" })));
  }
  card.onclick = () => { selectedId = s.id; render(); $("#set-dialog").showModal(); };
  return card;
}

function column(title, sets, all) {
  const head = el("div", { className: "col-head", textContent: title, title });
  // Seasonal theme: the last rounds (top 4, or top 8 if the theme says so) get its label, e.g. "Final Haunt".
  const inFinals = (s) => (data?.finalsFrom === 8 ? s.top8 : s.top4);
  if (data?.finalsLabel && sets.some(inFinals)) {
    head.prepend(el("span", { className: "top8-tag", textContent: data.finalsLabel }));
    head.title = `${data.finalsLabel}: ${title}`;
  }
  const col = el("div", { className: "col" }, head);
  for (const s of sets.sort(identOrder)) col.append(setCardB(s, all));
  return col;
}

function columnsFor(sets, all) {
  const rounds = new Map();
  for (const s of sets) {
    const k = s.roundNum ?? 0;
    if (!rounds.has(k)) rounds.set(k, []);
    rounds.get(k).push(s);
  }
  const cols = el("div", { className: "cols" });
  for (const k of [...rounds.keys()].sort((a, b) => Math.abs(a) - Math.abs(b))) {
    const list = rounds.get(k).filter((s) => !(hideDone && s.state === 3));
    if (!list.length) continue;
    cols.append(column(rounds.get(k)[0].round || `Round ${k}`, list, all));
  }
  return cols;
}

function render() {
  if (!data) return;
  $("#t-name").textContent = `${data.tournament?.name || "Bracket"}`;
  const all = byId();
  const groups = groupsOf(data.sets);
  if (!groups.find((g) => g.key === groupKey)) groupKey = groups[0]?.key ?? null;
  $("#groups").replaceChildren(...(groups.length > 1 ? groups.map((g) => {
    const b = el("button", { textContent: g.label, className: g.key === groupKey ? "sel" : "" });
    b.onclick = () => { groupKey = g.key; render(); };
    return b;
  }) : []));
  const g = groups.find((x) => x.key === groupKey);
  const board = $("#board");
  if (!g) { $("#tabs").replaceChildren(); board.replaceChildren(el("p", { className: "muted pad", textContent: "No sets in this event yet." })); renderSetDialog(all); return; }

  const parts = [];
  const twoSided = g.type === "DOUBLE_ELIMINATION" || g.sets.some((s) => (s.roundNum ?? 0) < 0);
  const w = g.sets.filter((s) => (s.roundNum ?? 0) > 0), l = g.sets.filter((s) => (s.roundNum ?? 0) < 0);
  const finished = g.sets.filter((s) => s.state === 3).sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0));
  // Tabs: whole bracket, one side only (more room on the touch screen), or the finished sets.
  const left = (list) => `${list.filter((s) => s.state !== 3).length} left`;
  const tabs = [["full", "Full bracket", left(g.sets)],
    ...(twoSided ? [["winners", "Winners bracket", left(w)], ["losers", "Losers bracket", left(l)]] : []),
    ["done", "Completed sets", String(finished.length)]];
  if (!tabs.some(([key]) => key === view)) view = "full";
  $("#tabs").replaceChildren(...tabs.map(([key, label, count]) => {
    const b = el("button", { className: key === view ? "sel" : "" }, label, el("small", { textContent: count }));
    b.onclick = () => {
      view = key;
      try { localStorage.setItem("bracket.view", view); } catch { /* ignore */ }
      render();
      board.scrollTo(0, 0);
    };
    return b;
  }));
  if (view === "done") {
    // Finished sets, newest first, as big cards. Tap one for its window (Reset result).
    parts.push(finished.length ? el("div", { className: "done-grid" }, ...finished.map((s) => doneCard(s)))
      : el("p", { className: "muted pad", textContent: "No completed sets yet." }));
  } else if (twoSided) {
    if (view !== "losers") parts.push(el("div", { className: "side" }, el("h2", { textContent: "Winners" }), columnsFor(w, all)));
    if (view !== "winners") parts.push(el("div", { className: "side" }, el("h2", { textContent: "Losers" }), columnsFor(l, all)));
  } else {
    parts.push(el("div", { className: "side" }, el("h2", { textContent: g.label }), columnsFor(g.sets, all)));
  }
  board.replaceChildren(...parts);

  const c = (st) => g.sets.filter((s) => s.state === st).length;
  const liveHere = g.sets.some((s) => String(s.id) === liveId() && s.state !== 3);
  $("#counts").textContent = [liveHere ? "1 live" : null, `${c(2)} playing`, `${c(6)} called`,
    `${g.sets.filter((s) => [1, 4, 7].includes(s.state) && hasPlayers(s)).length} waiting`, `${c(3)} done`].filter(Boolean).join(" · ");
  $("#updated").textContent = new Date(data.fetchedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  renderSetDialog(all);
}

// The set actions window: opened by tapping a set, closed by ✕, Esc, a tap outside it, or any action.
function renderSetDialog(all) {
  const d = $("#set-dialog");
  const s = selectedId != null ? all[String(selectedId)] : null;
  if (!s) { if (d.open) d.close(); return; }  // the set is gone (bracket restarted): close
  $("#sd-letter").textContent = s.identifier || "";
  $("#sd-badge").replaceChildren(badgeFor(s));
  $("#sd-round").textContent = s.round || "";
  const done = s.state === 3;
  $("#sd-players").replaceChildren(...[0, 1].map((i) => {
    const slot = s.slots[i] || {};
    const known = !!slot.entrantId;
    const won = done && s.winnerId && String(slot.entrantId) === String(s.winnerId);
    return el("div", { className: `p${known ? "" : " tbd"}${won ? " win" : ""}` },
      el("i", { textContent: known && slot.seed ? `(${slot.seed})` : "" }),
      el("span", { textContent: known ? display(slot.prefix, slot.tag) : prereqLabel(slot, all) }),
      el("b", { textContent: !known ? "" : slot.score === -1 ? "DQ" : slot.score ?? "" }));
  }));
  $("#sd-meta").textContent = [s.stream ? `stream: ${s.stream}` : null, !done && setupName(s) ? `setup: ${setupName(s)}` : null,
    s.station ? `station ${s.station}` : null].filter(Boolean).join(" · ");
  const btns = $("#sd-buttons");
  btns.replaceChildren();
  const add = (label, fn, cls = "") => {
    const b = el("button", { textContent: label, className: cls });
    b.onclick = () => { d.close(); fn(); };  // close first: setup / report open their own window
    btns.append(b);
  };
  const live = liveId() === String(s.id);
  if (done) {
    add("Reset result", () => doReset(s), "danger wide");
  } else if (hasPlayers(s)) {
    add(live ? "On stream ✓" : "Put on stream", () => streamSet(s), live ? "" : "accent");
    add(setupName(s) ? `${setupName(s)} ✓` : "Put on setup…", () => openSetupPicker(s));
    if (s.state !== 6 && s.state !== 2) add("Call", () => doAction("call", s, `Called ${vsText(s)}`));
    if (s.state !== 2) add("Start", () => doAction("start", s, `Started ${vsText(s)}`));
    add("Report…", () => openReport(s), btns.children.length % 2 === 0 ? "wide" : "");
  }
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
$("#hide-done").checked = hideDone;
$("#hide-done").onchange = (e) => {
  hideDone = e.target.checked;
  try { localStorage.setItem("bracket.hideDone", hideDone ? "1" : "0"); } catch { /* ignore */ }
  render();
};

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
