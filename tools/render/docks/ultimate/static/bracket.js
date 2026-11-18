// SSBU:Full Bracket (http://127.0.0.1:8766/bracket). Shared code: common.js.
// Tabs pick the whole bracket, one side, or the completed sets. Tap a set for its window.
// Every set of the Ultimate event by round, with the same actions as the main dock
// (put on recording 1/2, put on setup, call, start, report, DQ, reset).
"use strict";

let data = null;          // last /api/bracket result
let selectedId = null;    // set shown in the set window
let view = "full";        // tab: "full" | "winners" | "losers" | "done"
let groupKey = null;      // which bracket / pool is shown
let hideDone = false;
try {
  hideDone = localStorage.getItem("ubracket.hideDone") === "1";
  view = ["full", "winners", "losers", "done"].includes(localStorage.getItem("ubracket.view")) ? localStorage.getItem("ubracket.view") : "full";
} catch { /* private mode */ }

const byId = () => Object.fromEntries((data?.sets || []).map((s) => [String(s.id), s]));
const onOf = (s) => (s.state === 3 ? null : streamOf(data?.onStream, s));
const identOrder = (a, b) => (a.identifier || "").length - (b.identifier || "").length
  || (a.identifier || "").localeCompare(b.identifier || "");

function badgeFor(s) {
  if (s.state !== 3 && !hasPlayers(s)) return "";  // future set: no status until both players are in
  const on = onOf(s);
  if (on) return streamBadge(on);
  if (s.state === 3 && isDQ(s)) return el("span", { className: "badge b1", textContent: "DQ" });
  return el("span", { className: `badge b${s.state}`, textContent: STATE_NAME[s.state] || s.state });
}

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
  const on = onOf(s);
  const done = s.state === 3;
  const empty = !hasPlayers(s) && !done;
  const cls = ["bset", `st-${s.state}`, on && `on${on}`, done && "done", empty && "empty",
    String(s.id) === String(selectedId) && "sel"].filter(Boolean).join(" ");
  const card = el("div", { className: cls, title: s.round });
  const right = el("span", { className: "right" });
  const ours = Object.values(data.streamIds || {}).filter(Boolean).map(String);
  if (s.stream && !ours.includes(String(s.streamId))) right.append(el("span", { className: "badge other", textContent: s.stream }));
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
  const setup = !done && !on ? setupName(s) : "";
  const foot = [setup, s.station ? `Station ${s.station}` : ""].filter(Boolean).join(" · ");
  if (foot) card.append(el("div", { className: "foot", textContent: foot }));
  if (setup) card.classList.add("onsetup");
  markTopSeed(card, s);
  if (!empty) card.onclick = () => { selectedId = s.id; render(); $("#set-dialog").showModal(); };
  return card;
}

// Big card for the "Completed sets" tab.
function doneCard(s) {
  const card = el("div", { className: `dset${String(s.id) === String(selectedId) ? " sel" : ""}` });
  const when = s.completedAt ? new Date(s.completedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  const saved = savedChars(s);
  card.append(el("div", { className: "top" },
    el("span", {}, el("span", { className: "letter", textContent: s.identifier || "" }), ` ${s.round || ""}`),
    el("span", {}, isDQ(s) ? el("span", { className: "badge b1", textContent: "DQ" }) : null, when ? ` ${when}` : "")));
  s.slots.forEach((slot, i) => {
    const won = s.winnerId && String(slot.entrantId) === String(s.winnerId);
    const chars = saved ? startChars(s, i).map(shortChar).join(", ") : "";
    card.append(el("div", { className: `p ${won ? "win" : "lose"}` },
      el("span", { textContent: (display(slot.prefix, slot.tag) || "?") + (chars ? ` (${chars})` : "") }),
      el("b", { textContent: slot.score === -1 ? "DQ" : slot.score ?? "" })));
  });
  if (!saved && !isDQ(s)) card.append(el("div", { className: "foot", textContent: "no characters saved" }));
  card.onclick = () => { selectedId = s.id; render(); $("#set-dialog").showModal(); };
  return card;
}

function column(title, sets, all) {
  const col = el("div", { className: "col" }, el("div", { className: "col-head", textContent: title, title }));
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
  $("#t-name").textContent = `${data.tournament?.name || "Bracket"} · Ultimate`;
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
  if (!g) { $("#tabs").replaceChildren(); board.replaceChildren(el("p", { className: "muted pad", textContent: "No sets in this event yet." })); showSet(all); return; }

  const parts = [];
  const twoSided = g.type === "DOUBLE_ELIMINATION" || g.sets.some((s) => (s.roundNum ?? 0) < 0);
  const w = g.sets.filter((s) => (s.roundNum ?? 0) > 0), l = g.sets.filter((s) => (s.roundNum ?? 0) < 0);
  const finished = g.sets.filter((s) => s.state === 3).sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0));
  const left = (list) => `${list.filter((s) => s.state !== 3).length} left`;
  const tabs = [["full", "Full bracket", left(g.sets)],
    ...(twoSided ? [["winners", "Winners bracket", left(w)], ["losers", "Losers bracket", left(l)]] : []),
    ["done", "Completed sets", String(finished.length)]];
  if (!tabs.some(([key]) => key === view)) view = "full";
  $("#tabs").replaceChildren(...tabs.map(([key, label, count]) => {
    const b = el("button", { className: key === view ? "sel" : "" }, label, el("small", { textContent: count }));
    b.onclick = () => {
      view = key;
      try { localStorage.setItem("ubracket.view", view); } catch { /* ignore */ }
      render();
      board.scrollTo(0, 0);
    };
    return b;
  }));
  if (view === "done") {
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
  const rec = g.sets.filter((s) => onOf(s)).length;
  $("#counts").textContent = [rec ? `${rec} recording` : null, `${c(2)} playing`, `${c(6)} called`,
    `${g.sets.filter((s) => [1, 4, 7].includes(s.state) && hasPlayers(s)).length} waiting`, `${c(3)} done`].filter(Boolean).join(" · ");
  $("#updated").textContent = new Date(data.fetchedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  showSet(all);
}

function showSet(all) {
  renderSetDialog(selectedId != null ? all[String(selectedId)] : null,
    { on: onOf, badge: badgeFor, prereq: (slot) => prereqLabel(slot, all) });
}

async function refresh(quiet = true) {
  try {
    data = await api("/api/bracket");
    if (checkUiVersion(data.uiVersion)) return;
    updateSetups(data);
    render();
    if (!quiet && !data.rebuilding) status("");
    showRateLimited(data.rateLimited && !data.rebuilding);
    showRebuilding(data.rebuilding, () => refresh());
  } catch (e) {
    status(e.message, "error");
  }
}

$("#btn-refresh").onclick = () => refresh(false);
initSetDialog(() => { selectedId = null; render(); });
$("#hide-done").checked = hideDone;
$("#hide-done").onchange = (e) => {
  hideDone = e.target.checked;
  try { localStorage.setItem("ubracket.hideDone", hideDone ? "1" : "0"); } catch { /* ignore */ }
  render();
};

(async function init() {
  try {
    ensureDialogs();
    await loadCharacters();
    const st = await api("/api/state");
    checkUiVersion(st.uiVersion);
    setSlotLabel(st.config);
    if (!st.tokenSet) {
      status("start.gg token not found. Run set_token.bat, then restart start_dock.bat.", "error");
      return;
    }
    await refresh(false);
    setInterval(() => { if (!document.querySelector("dialog[open]")) refresh(); }, Math.max(10, st.config?.pollSeconds || 20) * 1000);
    watchChanges(() => refresh());
  } catch (e) {
    status(`Dock server not reachable: ${e.message}. Is start_dock.bat running?`, "error");
  }
})();
