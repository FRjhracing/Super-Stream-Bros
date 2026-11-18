// Super Stream Bros Ultimate Dock (runs inside an OBS custom browser dock). Shared code: common.js.
// Recording-only: no overlay. "Put on recording 1/2" saves a timestamp for that recording
// (the code calls the two OBS outputs "streams"; the page label comes from slotLabel).
"use strict";

let bracket = null;     // last /api/sets result
let streams = {};       // "1"/"2" -> set on that recording (from the server) or null
let recStart = {};      // "1"/"2" -> unix time "Rec started" was last pressed, or null
let pollTimer = null;
let pollSeconds = 20;

const ago = (t) => {
  const m = Math.max(0, Math.round((Date.now() / 1000 - t) / 60));
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
};

// ------------------------------------------------------------ recordings panel
function renderStreams() {
  for (const n of ["1", "2"]) {
    const box = document.querySelector(`.stream-card[data-n="${n}"]`);
    const cur = streams[n];
    const rec = recStart[n];
    const btn = (label, title, fn, cls = "") => { const b = el("button", { textContent: label, title, className: cls }); b.onclick = fn; return b; };
    const recSetup = dockSetups.setups.find((x) => x.stream === n);
    const head = el("div", { className: "sc-head" },
      el("h2", { textContent: slotName(n), title: "Which setup this recording captures: ⚙ settings" },
        el("span", { className: "muted small", textContent: recSetup ? ` · ${recSetup.name}` : " · no setup picked" })),
      el("span", { className: `rec ${rec ? "on" : ""}`, textContent: rec ? `● Rec since ${fmtClock(rec)}` : "Rec start not marked" }));
    const body = cur
      ? el("div", { className: "sc-body" },
          el("div", { className: "muted small", textContent: `${cur.round || "Set"}${cur.identifier ? ` · set ${cur.identifier}` : ""}` }),
          el("div", { className: "sc-vs", textContent: `${cur.p1} vs ${cur.p2}` }),
          el("div", { className: "muted small", textContent: `on since ${fmtClock(cur.since)} (${ago(cur.since)})` }))
      : el("div", { className: "sc-body" }, el("div", { className: "muted sc-empty", textContent: "Nothing on this recording" }));
    const acts = el("div", { className: "row" },
      btn("● Rec started", `Press when OBS ${n === "1" ? "(main)" : "(portable)"} starts recording: times in the chapter list count from here`, () => slot(n, "rec")),
      btn("★ Mark", "Save a marker at this moment (highlight, problem, anything to check later)", () => slot(n, "mark")),
      btn("■ Set over", "The set on this recording finished (reporting it does this too)", () => slot(n, "end"), cur ? "" : "dim"));
    box.replaceChildren(head, body, acts);
  }
}

async function slot(n, action) {
  if (action === "end" && !streams[n]) { status(`Nothing is on ${slotName(n).toLowerCase()}.`, ""); return; }
  if (action === "rec" && recStart[n] && !(await confirmBox(`${slotName(n)} was already marked as recording since ${fmtClock(recStart[n])}.\nMark a NEW recording start now? (Only if OBS ${n} started a new file.)`))) return;
  try {
    const r = await api("/api/slot", { stream: n, action });
    status(`${slotName(n)}: ${{ rec: "recording start", mark: "mark", end: "set over" }[action]} saved at ${r.clock}`, "ok");
  } catch (e) { status(e.message, "error"); }
}

// ------------------------------------------------------------ bracket list
// Name + characters (saved for this set, else muted "usually: ...") + score.
function slotLine(slot, winnerId, chars) {
  const won = winnerId && String(slot.entrantId) === String(winnerId);
  const hint = chars?.length ? el("span", { className: "chars", textContent: ` ${chars.map(shortChar).join(", ")}` })
    : usual(slot).length ? el("span", { className: "chars muted", textContent: ` usually ${usual(slot).slice(0, 2).map(shortChar).join(", ")}` }) : null;
  return [
    el("span", { className: won ? "win" : "" }, display(slot.prefix, slot.tag) || "TBD", hint),
    el("b", { className: won ? "win" : "", textContent: slot.score === -1 ? "DQ" : slot.score ?? "–" }),
  ];
}

function setCard(s, done) {
  const on = done ? null : streamOf(bracket.onStream, s);
  const setup = done ? "" : setupName(s);
  const card = el("div", { className: `set st-${s.state}${on ? ` on s${on}` : setup ? " onsetup" : ""}` });
  const badge = on ? streamBadge(on) : el("span", { className: `badge b${s.state}`, textContent: STATE_NAME[s.state] || s.state });
  const left = el("span", {}, badge, ` ${s.round}`);
  const right = el("span", {});
  if (setup && !on) right.append(el("span", { className: "badge setup", textContent: setup }), " ");
  const ours = Object.values(bracket.streamIds || {}).filter(Boolean).map(String);
  if (s.stream && !ours.includes(String(s.streamId))) right.append(el("span", { className: "badge other", textContent: s.stream }), " ");
  if (s.station) right.append(`station ${s.station} `);
  if (s.identifier) right.append(`#${s.identifier}`);
  card.append(el("div", { className: "meta" }, left, right));
  const saved = savedChars(s);
  const cs = [0, 1].map((i) => (saved ? startChars(s, i) : null));
  card.append(el("div", { className: "vs" }, ...slotLine(s.slots[0], s.winnerId, cs[0]), ...slotLine(s.slots[1] || {}, s.winnerId, cs[1])));
  const acts = el("div", { className: "acts" });
  const btn = (label, fn, cls = "") => { const b = el("button", { textContent: label, className: cls }); b.onclick = fn; acts.append(b); };
  if (done) {
    if (!isDQ(s)) btn(saved ? "Characters ✓" : "Characters…", () => openChars(s));
    btn("Reset", () => doReset(s), "danger");
  } else {
    for (const n of ["1", "2"]) btn(putLabel(n, on === n), () => putOnStream(s, n), on === n ? `s${n} cur` : `s${n}`);
    btn(setup && !on ? `${setup} ✓` : "Put on setup…", () => openSetupPicker(s), setup && !on ? "setup cur" : "");
    if (s.state !== 6 && s.state !== 2) btn("Call", () => doAction("call", s, `Called ${vsText(s)}`));
    if (s.state !== 2) btn("Start", () => doAction("start", s, `Started ${vsText(s)}`));
    btn("Report…", () => openReport(s));
  }
  card.append(acts);
  markTopSeed(card, s);
  return card;
}

function renderBracket() {
  if (!bracket) return;
  $("#t-name").textContent = bracket.tournament?.name ? `${bracket.tournament.name} · Ultimate` : "Super Stream Bros Ultimate - Home";
  const sel = $("#event-select");
  sel.replaceChildren(...bracket.events.map((e) => el("option", { value: e.id, textContent: `${e.name} (${e.numEntrants ?? "?"})`, selected: String(e.id) === String(bracket.eventId) })));
  sel.classList.toggle("hidden", bracket.events.length < 1);
  for (const n of ["1", "2"]) {
    const ss = $(`#sid-${n}`);
    if (ss.matches(":focus")) continue;
    ss.replaceChildren(
      el("option", { value: "", textContent: bracket.streams.length ? "None: don't assign on start.gg" : "No streams on start.gg" }),
      ...bracket.streams.map((x) => el("option", { value: x.id, textContent: x.streamName, selected: String(x.id) === String(bracket.streamIds?.[n]) })),
    );
  }
  // On-stream sets first, then playing, called, the rest in call order.
  const rank = { 2: 1, 6: 2, 7: 3, 4: 4, 1: 5 };
  const r = (s) => (streamOf(bracket.onStream, s) ? 0 : setupOf(s) != null ? 0.5 : rank[s.state] ?? 6);
  const list = [...bracket.open].sort((a, b) => r(a) - r(b));
  $("#open-sets").replaceChildren(...(list.length ? list.map((s) => setCard(s, false)) : [el("p", { className: "muted", textContent: "No open sets with both players known." })]));
  $("#open-count").textContent = `· ${list.length} open`;
  $("#done-sets").replaceChildren(...bracket.done.map((s) => setCard(s, true)));
  $("#updated").textContent = new Date(bracket.fetchedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ------------------------------------------------------------ timestamp log
async function loadLog() {
  try {
    const d = await api("/api/log");
    $("#log-count").textContent = `· ${d.count} saved`;
    $("#log-dir").textContent = `Timestamps folder: ${d.logDir}`;
    const rows = d.events.map((e) => {
      const del = el("button", { className: "x", textContent: "✕", title: "Delete this entry (mis-click)" });
      del.onclick = async () => {
        if (!(await confirmBox(`Delete this timestamp?\n${slotName(e.stream)} · ${e.clock} · ${e.text}`))) return;
        try { await api("/api/log/delete", { id: e.id }); } catch (err) { status(err.message, "error"); }
      };
      return el("div", { className: `log-row ev-${e.event}` },
        el("span", { className: "muted", textContent: e.clock }),
        el("span", {}, streamBadge(e.stream)),
        el("span", { className: "vid", textContent: e.video || "", title: "Time into the recording (from Rec started)" }),
        el("span", { className: "txt", textContent: e.text }),
        del);
    });
    $("#log").replaceChildren(...(rows.length ? rows : [el("p", { className: "muted", textContent: `Nothing yet. Press ● Rec started when each OBS starts recording, then Put on ${SLOT.toLowerCase()} 1/2 (or Put on setup) as sets start.` })]));
  } catch (e) { /* keep the old list */ }
}

// ------------------------------------------------------------ refresh / sync
async function loadState() {
  const st = await api("/api/state");
  setSlotLabel(st.config);  // before anything draws "Recording 1"
  streams = st.streams || {};
  recStart = st.recStart || {};
  updateSetups(st);
  $("#log-dir").textContent = `Timestamps folder: ${st.logDir}`;
  renderStreams();
  return st;
}

async function refresh(quiet = false) {
  try {
    bracket = await api("/api/sets");
    if (checkUiVersion(bracket.uiVersion)) return;
    updateSetups(bracket);
    renderBracket();
    renderStreams();
    if (!document.querySelector("#settings :focus")) renderSetupSettings();
    if (!quiet && !bracket.rebuilding) status("");
    showRateLimited(bracket.rateLimited && !bracket.rebuilding);
    showRebuilding(bracket.rebuilding, () => refresh(true));
  } catch (e) {
    status(e.message, "error");
  }
}

function schedulePoll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (document.querySelector("dialog[open]")) return;
    await refresh(true);
    await loadState().catch(() => {});  // a set reported on start.gg ends its recording segment
  }, pollSeconds * 1000);
}

async function onRemoteChange() {
  try { await loadState(); } catch { /* keep what we have */ }
  await loadLog();
  await refresh(true);
}

// ------------------------------------------------------------ wiring
$("#btn-refresh").onclick = () => refresh();
$("#btn-settings").onclick = () => $("#settings").classList.toggle("hidden");
$("#btn-bracket").onclick = () => window.open("/bracket", "ultimate-bracket", "width=1280,height=760");
$("#btn-active").onclick = () => window.open("/active", "ultimate-active", "width=1100,height=760");
$("#btn-open-folder").onclick = async () => {
  try { const r = await api("/api/openfolder", {}); status(`Opened ${r.folder}`, "ok"); }
  catch (e) { status(e.message, "error"); }
};
$("#event-select").onchange = async (e) => {
  try { await api("/api/tournament", { eventId: e.target.value }); await refresh(); }
  catch (err) { status(err.message, "error"); }
};
for (const n of ["1", "2"]) {
  $(`#sid-${n}`).onchange = async (e) => {
    try {
      await api("/api/streamids", { [n]: e.target.value || null });
      status(e.target.value ? `${slotName(n)} = ${e.target.selectedOptions[0].textContent} on start.gg` : `${slotName(n)}: no start.gg stream`, "ok");
    } catch (err) { status(err.message, "error"); }
  };
}
$("#btn-latest").onclick = async () => {
  try {
    const r = await api("/api/tournament", { tournamentSlug: "", refreshLink: true });
    $("#slug-input").value = r.slug; status(`Loaded ${r.tournament}`, "ok"); await refresh(true);
  } catch (e) { status(e.message, "error"); }
};
$("#btn-slug").onclick = async () => {
  try {
    const r = await api("/api/tournament", { tournamentSlug: $("#slug-input").value.trim() });
    $("#slug-input").value = r.slug; status(`Loaded ${r.tournament}`, "ok"); await refresh(true);
  } catch (e) { status(e.message, "error"); }
};
setInterval(renderStreams, 30000);  // keeps "on since ... (N min)" current

// ------------------------------------------------------------ setups (count, names, which ones are recorded)
function renderSetupSettings() {
  const list = dockSetups.setups;
  $("#setup-count").value = list.length;
  $("#setup-names").replaceChildren(...list.map((x) =>
    el("input", { value: x.name, placeholder: `Setup ${x.index + 1}`, title: `Setup ${x.index + 1} name` })));
  for (const n of ["1", "2"]) {
    $(`#rec-setup-${n}`).replaceChildren(el("option", { value: "", textContent: "— none —" }),
      ...list.map((x) => el("option", { value: x.index, textContent: x.name, selected: dockSetups.streamSetups[n] === x.index })));
  }
}
async function saveSetups(count) {
  const names = [...document.querySelectorAll("#setup-names input")].map((i) => i.value.trim());
  const n = Math.max(1, Math.min(16, count ?? names.length));
  while (names.length < n) names.push(`Setup ${names.length + 1}`);
  names.length = n;
  const rec = Object.fromEntries(["1", "2"].map((k) => [k, $(`#rec-setup-${k}`).value === "" ? null : Number($(`#rec-setup-${k}`).value)]));
  try {
    const r = await api("/api/setups", { names, streamSetups: rec });
    updateSetups(r);
    status(`${n} setup${n === 1 ? "" : "s"} saved`, "ok");
  } catch (e) { status(`Setups not saved: ${e.message}`, "error"); }
  renderSetupSettings();
  renderStreams();
}
$("#setup-count").onchange = (e) => saveSetups(Number(e.target.value) || 0);
$("#setup-names").onchange = () => saveSetups();
for (const n of ["1", "2"]) $(`#rec-setup-${n}`).onchange = () => saveSetups();

(async function init() {
  try {
    ensureDialogs();
    await loadCharacters();
    const st = await loadState();
    renderSetupSettings();
    checkUiVersion(st.uiVersion);
    pollSeconds = Math.max(10, st.config?.pollSeconds || 20);
    $("#slug-input").value = st.config?.tournamentSlug || "";
    await loadLog();
    if (!st.tokenSet) {
      status("start.gg token not found. Run set_token.bat, then close and reopen start_dock.bat. Timestamps for Rec started / Mark still work.", "error");
      $("#open-sets").replaceChildren(el("p", { className: "muted", textContent: "Bracket unavailable without a token." }));
      watchChanges(onRemoteChange);
      return;
    }
    await refresh();
    schedulePoll();
    watchChanges(onRemoteChange);
  } catch (e) {
    status(`Dock server not reachable: ${e.message}. Is start_dock.bat running?`, "error");
  }
})();
