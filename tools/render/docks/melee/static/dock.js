// Super Stream Bros Melee dock, Home page (a browser tab or an OBS custom browser dock). Shared code: common.js.
"use strict";

const CHARACTERS = {
  "Bowser": ["neutral", "red", "blue", "black"],
  "Captain Falcon": ["neutral", "black", "red", "white", "green", "blue"],
  "Doctor Mario": ["neutral", "red", "blue", "green", "black"],
  "Donkey Kong": ["neutral", "black", "red", "blue", "green"],
  "Falco": ["neutral", "red", "blue", "green"],
  "Fox": ["neutral", "red", "blue", "green"],
  "Ganondorf": ["neutral", "red", "blue", "green", "purple"],
  "Ice Climbers": ["neutral", "green", "orange", "red"],
  "Jigglypuff": ["neutral", "bow", "crown", "flower", "headband"],
  "Kirby": ["neutral", "yellow", "blue", "red", "green", "white"],
  "Link": ["neutral", "red", "blue", "black", "white"],
  "Luigi": ["neutral", "white", "pink", "blue"],
  "Mario": ["neutral", "yellow", "blue", "green", "brown"],
  "Marth": ["neutral", "red", "green", "black", "white"],
  "Mewtwo": ["neutral", "red", "blue", "green"],
  "Mr. Game & Watch": ["neutral", "red", "blue", "green"],
  "Ness": ["neutral", "yellow", "blue", "green"],
  "Peach": ["neutral", "daisy", "white", "blue", "green"],
  "Pichu": ["neutral", "red", "blue", "green"],
  "Pikachu": ["neutral", "red", "blue", "green"],
  "Roy": ["neutral", "red", "blue", "green", "yellow"],
  "Samus": ["neutral", "pink", "green", "brown", "blue"],
  "Sheik": ["neutral", "red", "blue", "green", "black"],
  "Yoshi": ["neutral", "red", "blue", "yellow", "pink", "cyan"],
  "Young Link": ["neutral", "red", "blue", "white", "black"],
  "Zelda": ["neutral", "red", "blue", "green", "lavender"],
};
const CHAR_ORDER = [
  "Doctor Mario", "Mario", "Luigi", "Bowser", "Peach", "Yoshi", "Donkey Kong", "Captain Falcon", "Ganondorf",
  "Falco", "Fox", "Ness", "Ice Climbers", "Kirby", "Samus", "Sheik", "Link", "Young Link",
  "Pichu", "Pikachu", "Jigglypuff", "Mewtwo", "Mr. Game & Watch", "Marth", "Roy",
];

let overlay = null;        // what is on stream (mirrors server dock_state.json)
let prefs = {};            // tag -> {character, color}
let bracket = null;        // last /api/sets result
let entrants = [];         // for manual player pick
let pollTimer = null;
let pollSeconds = 20;

// Stock icon <img>. If it fails to load (dock server restarting at that moment), try again once
// past the browser cache instead of leaving a broken picture.
function stockImg(ch, color, alt) {
  const img = el("img", { src: stockUrl(ch, color), alt });
  img.onerror = () => {
    // Retry once (seen failing once live), then show the name instead: stock icons aren't shipped
    // (assets\stock_icons\PROVIDE YOUR OWN.md), and the picker still has to work without them.
    img.onerror = () => {
      img.onerror = null;
      img.replaceWith(el("span", { className: "stock-missing", textContent: alt || "", title: `${color || "neutral"} ${ch}` }));
    };
    setTimeout(() => { img.src = `${stockUrl(ch, color)}?retry=${Date.now()}`; }, 800);
  };
  return img;
}

// ------------------------------------------------------------ on-stream panel
function renderPlayers() {
  for (const n of [1, 2]) {
    const p = overlay[`p${n}`];
    const box = document.querySelector(`.player[data-p="${n}"]`);
    box.replaceChildren();
    const pfp = el("img", { className: "pfp", alt: "" });
    makePfp(p.imageUrl).then((d) => (pfp.src = d));
    const name = el("input", { value: p.display || "", placeholder: `Player ${n}`, autocomplete: "off" });
    name.onchange = () => {
      if (name.dataset.picked) return;  // chosen from the list (handled by choosePlayer)
      const typed = name.value.trim();
      const hit = entrants.find((e) => display(e.prefix, e.tag) === typed || e.tag === typed);
      if (hit) { choosePlayer(n, hit); return; }
      Object.assign(p, { display: typed, tag: typed, prefix: "", name: typed, entrantId: null, imageUrl: "" });
      renderPlayers();
      pushOverlay();
    };
    const nameWrap = attachNamePicker(name, n);
    const charBtn = el("button", { className: "char-btn", title: "Character / color" });
    if (p.character) charBtn.append(stockImg(p.character, p.color, ""), p.character);
    else charBtn.append("Character");
    charBtn.onclick = () => openCharPicker(n);
    const minus = el("button", { textContent: "−" }), plus = el("button", { textContent: "+" });
    minus.onclick = () => { p.score = Math.max(0, p.score - 1); renderPlayers(); pushOverlay(); };
    plus.onclick = () => { p.score = Math.min(9, p.score + 1); renderPlayers(); pushOverlay(); };
    // Long names are fitted to the name plate (prefix dropped / cut with "…"); show what OBS gets.
    const fitted = p.shown && p.display && p.shown !== p.display
      ? el("div", { className: "muted small fitted", textContent: `Shows: ${p.shown}`, title: "Shortened to fit the name plate. Type a shorter name to override." })
      : null;
    box.append(...[  // native append() would print a null as the text "null"
      el("div", { className: "top" }, pfp, nameWrap),
      fitted,
      charBtn,
      el("div", { className: "score" }, minus, el("b", { textContent: p.score }), plus),
    ].filter(Boolean));
  }
  $("#round-input").value = overlay.round || "";
  $("#bo-input").value = overlay.gameCount || "";
  const set = findSet(overlay.setId);
  $("#stream-set").textContent = overlay.setId ? (set ? `· set ${set.identifier || ""}` : "· set linked") : "· manual";
  $("#btn-report-stream").disabled = !(overlay.setId && overlay.p1.entrantId && overlay.p2.entrantId);
}

async function pushOverlay() {
  overlay.round = $("#round-input").value.trim();
  overlay.gameCount = $("#bo-input").value.trim();
  for (const n of [1, 2]) {
    const p = overlay[`p${n}`];
    if (p.tag && p.character) prefs[p.tag] = { character: p.character, color: p.color };
  }
  try {
    await saveOverlay(overlay);
    renderPlayers();  // "Shows: …" hint for fitted names
    status("Overlay updated", "ok");
  } catch (e) {
    status(`Overlay not saved: ${e.message}`, "error");
  }
}

// ------------------------------------------------------------ player picker (manual overlay)
// Every entrant in the event. Players in a match (in progress, or on a setup) are listed after
// the free ones, in the busy-setup color, with where they are playing.
function playingMap() {
  const m = new Map();
  for (const s of bracket?.open || []) {
    const live = !!overlay && String(overlay.setId) === String(s.id);
    const setup = setupName(s);
    if (!(live || s.state === 2 || setup)) continue;
    s.slots.forEach((x, i) => m.set(String(x.entrantId), { set: s, live, setup, vs: s.slots[1 - i]?.tag || "?" }));
  }
  return m;
}

function attachNamePicker(input, n) {
  const pop = el("div", { className: `name-pop hidden p${n}` });
  let items = [], active = 0;
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    const busy = playingMap();
    const match = entrants.filter((e) => !q || display(e.prefix, e.tag).toLowerCase().includes(q) || (e.name || "").toLowerCase().includes(q));
    const free = match.filter((e) => !busy.has(String(e.entrantId)));
    const playing = match.filter((e) => busy.has(String(e.entrantId)));
    items = [...free, ...playing];
    active = Math.min(active, Math.max(0, items.length - 1));
    pop.replaceChildren(...items.slice(0, 60).map((e, i) => {
      const b = busy.get(String(e.entrantId));
      const where = !b ? "" : b.live ? "on stream" : b.setup ? `${b.setup} · vs ${b.vs}` : `playing · vs ${b.vs}`;
      const row = el("div", { className: `np-item${b && !b.live ? " busy" : ""}${b?.live ? " live" : ""}${i === active ? " act" : ""}` },
        el("span", { textContent: display(e.prefix, e.tag) }), where ? el("small", { textContent: where }) : null);
      row.onmousedown = (ev) => { ev.preventDefault(); pick(e); };  // before the input blurs
      return row;
    }));
    if (!items.length) pop.append(el("div", { className: "np-empty muted small", textContent: entrants.length ? "No player matches (typed name is used as is)" : "Player list not loaded" }));
    pop.classList.remove("hidden");
  };
  const pick = (e) => {
    input.dataset.picked = "1";
    pop.classList.add("hidden");
    input.blur();
    choosePlayer(n, e);
  };
  input.onfocus = () => { active = 0; draw(); input.select(); };
  input.oninput = () => { active = 0; draw(); };
  input.onblur = () => setTimeout(() => pop.classList.add("hidden"), 120);
  input.onkeydown = (ev) => {
    if (pop.classList.contains("hidden")) return;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      active = (active + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % Math.max(1, items.length);
      draw();
      pop.querySelector(".act")?.scrollIntoView({ block: "nearest" });
    } else if (ev.key === "Enter" && input.value.trim() && items[active]) {
      ev.preventDefault();
      pick(items[active]);
    } else if (ev.key === "Escape") {
      pop.classList.add("hidden");
    }
  };
  return el("div", { className: "name-wrap" }, input, pop);
}

// A player was picked for side n. If they are in a match somewhere else (another setup, or in
// progress), offer to move that whole set to stream: overlay loads both players, round and score,
// start.gg gets our stream, and the set moves to the stream setup (the setup log records the move;
// for a setup failing mid-set). Otherwise just that player goes on the overlay.
async function choosePlayer(n, e) {
  const b = playingMap().get(String(e.entrantId));
  if (b && !b.live) {
    const s = b.set;
    const where = b.setup ? `on ${b.setup}` : "in a match";
    const ss = dockSetups.streamSetup != null ? dockSetups.setups[dockSetups.streamSetup]?.name : "";
    const choice = await confirmBox(
      `${e.tag} is playing ${b.vs} ${where} (${s.round}${s.identifier ? ` · ${s.identifier}` : ""}).\n\n` +
      `Move that set to stream? Both players, the round and the score load${ss && b.setup !== ss ? `, and the set moves to ${ss}` : ""}.`,
      null, { yes: "Move set to stream", no: "Just this player" });
    if (choice === null) { renderPlayers(); return; }  // Esc: no change
    if (choice) { await streamSet(s); return; }
  }
  overlay[`p${n}`] = playerFromEntrant(e, prefs);
  renderPlayers();
  pushOverlay();
}

// ------------------------------------------------------------ character picker
function openCharPicker(n) {
  const p = overlay[`p${n}`];
  const d = $("#char-dialog");
  $("#char-title").textContent = `${p.display || `Player ${n}`}: character`;
  const grid = $("#char-grid");
  const drawColors = () => {
    const row = $("#color-row");
    row.replaceChildren();
    if (!p.character) return;
    for (const c of CHARACTERS[p.character]) {
      const b = el("button", { title: c, className: c === p.color ? "sel" : "" }, stockImg(p.character, c, c));
      b.onclick = () => { p.color = c; drawColors(); };
      row.append(b);
    }
  };
  grid.replaceChildren();
  for (const ch of CHAR_ORDER) {
    const b = el("button", { title: ch, className: ch === p.character ? "sel" : "" }, stockImg(ch, "neutral", ch));
    b.onclick = () => {
      p.character = ch; p.color = "neutral";
      grid.querySelectorAll("button").forEach((x) => x.classList.toggle("sel", x === b));
      drawColors();
    };
    grid.append(b);
  }
  $("#char-none").onclick = () => { p.character = ""; p.color = "neutral"; d.close(); };
  d.onclose = () => { renderPlayers(); pushOverlay(); };
  drawColors();
  d.showModal();
}

// ------------------------------------------------------------ bracket list
function findSet(id) {
  if (!bracket || !id) return null;
  return [...bracket.open, ...bracket.done].find((s) => String(s.id) === String(id)) || null;
}

function slotLine(slot, winnerId) {
  const won = winnerId && String(slot.entrantId) === String(winnerId);
  return [
    el("span", { className: won ? "win" : "", textContent: display(slot.prefix, slot.tag) || "TBD" }),
    el("b", { className: won ? "win" : "", textContent: slot.score === -1 ? "DQ" : slot.score ?? "–" }),
  ];
}

function setCard(s, done) {
  // Only the set currently on our stream is "LIVE"; other started sets are "Playing".
  const onStream = !done && overlay && String(overlay.setId) === String(s.id);
  const card = el("div", { className: `set st-${s.state}${onStream ? " onstream" : ""}` });
  const badge = onStream
    ? el("span", { className: "badge live", textContent: "Live" })
    : el("span", { className: `badge b${s.state}`, textContent: STATE_NAME[s.state] || s.state });
  const left = el("span", {}, badge, ` ${s.round}`);
  const right = el("span", {});
  // Show other people's streams by name; ours is implied by LIVE.
  if (s.stream && String(s.streamId) !== String(bracket.streamId)) right.append(el("span", { className: "badge other", textContent: s.stream }), " ");
  if (!done && setupName(s)) right.append(el("span", { className: "badge setup", textContent: setupName(s) }), " ");
  if (s.station) right.append(`station ${s.station} `);
  if (s.identifier) right.append(`#${s.identifier}`);
  card.append(el("div", { className: "meta" }, left, right));
  card.append(el("div", { className: "vs" }, ...slotLine(s.slots[0], s.winnerId), ...slotLine(s.slots[1] || {}, s.winnerId)));
  const acts = el("div", { className: "acts" });
  const btn = (label, fn, cls = "") => { const b = el("button", { textContent: label, className: cls }); b.onclick = fn; acts.append(b); };
  if (done) {
    btn("Reset", () => doReset(s), "danger");
  } else {
    btn(onStream ? "On stream ✓" : "Put on stream", () => streamSet(s), onStream ? "" : "accent");
    btn(setupName(s) ? `${setupName(s)} ✓` : "Put on setup…", () => openSetupPicker(s));
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
  $("#t-name").textContent = bracket.tournament?.name || "Super Stream Bros - Home";
  const sel = $("#event-select");
  sel.replaceChildren(...bracket.events.map((e) => el("option", { value: e.id, textContent: `${e.name} (${e.numEntrants ?? "?"})`, selected: String(e.id) === String(bracket.eventId) })));
  sel.classList.toggle("hidden", bracket.events.length < 2);
  const ss = $("#stream-select");
  if (!ss.matches(":focus")) {
    ss.replaceChildren(
      el("option", { value: "", textContent: bracket.streams.length ? "Not set: don't assign streams" : "No streams on start.gg" }),
      ...bracket.streams.map((x) => el("option", { value: x.id, textContent: x.streamName, selected: String(x.id) === String(bracket.streamId) })),
    );
  }
  const open = $("#open-sets");
  // On-stream set first, then playing, called, the rest in call order.
  const rank = { 2: 1, 6: 2, 7: 3, 4: 4, 1: 5 };
  const r = (s) => (overlay && String(overlay.setId) === String(s.id) ? 0 : rank[s.state] ?? 6);
  const list = [...bracket.open].sort((a, b) => r(a) - r(b));
  open.replaceChildren(...(list.length ? list.map((s) => setCard(s, false)) : [el("p", { className: "muted", textContent: "No open sets with both players known." })]));
  $("#open-count").textContent = `· ${list.length} open`;
  $("#done-sets").replaceChildren(...bracket.done.map((s) => setCard(s, true)));
  $("#updated").textContent = new Date(bracket.fetchedAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

async function refresh(quiet = false) {
  try {
    bracket = await api("/api/sets");
    if (checkUiVersion(bracket.uiVersion)) return;
    updateSetups(bracket);
    dockLiveSetId = overlay?.setId ?? null;
    if (!bracket.rebuilding) clearOverlayIfDone([...bracket.open, ...bracket.done]);
    if (!document.querySelector("#settings :focus")) renderSetupSettings();
    renderBracket();
    // Don't rebuild the on-stream panel while someone is typing in it (the poll used to reset it).
    if (!document.activeElement?.closest?.("#stream-panel")) renderPlayers();
    if (!quiet && !bracket.rebuilding) status("");
    showRateLimited(bracket.rateLimited && !bracket.rebuilding);
    showRebuilding(bracket.rebuilding, () => refresh(true));
    if (!entrants.length) loadEntrants();
  } catch (e) {
    status(e.message, "error");
  }
}

async function loadEntrants() {
  try {
    entrants = await api("/api/entrants");
    let dl = $("#entrant-list");
    if (!dl) document.body.append((dl = el("datalist", { id: "entrant-list" })));
    dl.replaceChildren(...entrants.map((e) => el("option", { value: display(e.prefix, e.tag) })));
  } catch { /* manual typing still works */ }
}

function schedulePoll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (!document.querySelector("dialog[open]")) refresh(true); }, pollSeconds * 1000);
}

// Something changed (here or in the bracket page): reload the overlay + theme, then the sets.
async function onRemoteChange() {
  const editing = document.querySelector("dialog[open]") ||
    (document.activeElement && document.activeElement.closest && document.activeElement.closest("#stream-panel"));
  try {
    const st = await api("/api/state");
    renderThemes(applyTheme(st.config?.theme));
    renderSeason(st);
    if (!editing) {
      overlay = st.overlay;
      prefs = st.prefs || {};
    }
  } catch { /* keep what we have */ }
  await refresh(true);
}

async function streamSet(s) {
  const ov = await putOnStream(s, { entrants, streamId: bracket?.streamId, streams: bracket?.streams });
  if (ov) { overlay = ov; renderPlayers(); renderBracket(); }
  dockLiveSetId = overlay?.setId ?? null;
}

// ------------------------------------------------------------ wiring
$("#btn-update").onclick = () => pushOverlay();
$("#btn-swap").onclick = () => { [overlay.p1, overlay.p2] = [overlay.p2, overlay.p1]; renderPlayers(); pushOverlay(); };
$("#btn-clear").onclick = async () => {
  if (!(await confirmBox("Clear the overlay (names, characters, scores, round)?"))) return;
  overlay = { round: "", roundPlain: "", losersTop8: false, gameCount: overlay.gameCount, setId: null, p1: blankPlayer(), p2: blankPlayer() };
  renderPlayers(); pushOverlay(); renderBracket();
};
$("#btn-report-stream").onclick = () => {
  const s = findSet(overlay.setId);
  if (!s) { status("The on-stream set isn't in the open list any more (already reported?).", "error"); return; }
  // Map overlay scores onto the set's slot order (overlay may be swapped).
  const scoreFor = (slot) => [overlay.p1, overlay.p2].find((p) => String(p.entrantId) === String(slot.entrantId))?.score || 0;
  openReport(s, [scoreFor(s.slots[0]), scoreFor(s.slots[1])]);
};
$("#round-input").onchange = () => pushOverlay();
$("#bo-input").onchange = () => pushOverlay();
$("#btn-refresh").onclick = () => refresh();
$("#btn-settings").onclick = () => $("#settings").classList.toggle("hidden");
$("#btn-bracket").onclick = () => window.open("/bracket", "protocol-bracket", "width=1280,height=760");
$("#btn-active").onclick = () => window.open("/active", "ssb-active", "width=1100,height=760");
$("#event-select").onchange = async (e) => {
  try { await api("/api/tournament", { eventId: e.target.value }); entrants = []; await refresh(); }
  catch (err) { status(err.message, "error"); }
};
$("#stream-select").onchange = async (e) => {
  try {
    await api("/api/stream", { streamId: e.target.value || null });
    bracket.streamId = e.target.value || null;
    status(e.target.value ? `Stream set: ${e.target.selectedOptions[0].textContent}` : "Stream assignment off", "ok");
  } catch (err) { status(err.message, "error"); }
};
let currentTheme = { ...DEFAULT_THEME };
function renderThemes(current) {
  currentTheme = { ...current };
  const row = $("#theme-row");
  row.replaceChildren(...Object.entries(THEMES).map(([name, t]) => {
    const b = el("button", { className: "swatch", title: name });
    b.style.background = `linear-gradient(135deg, ${t.accent} 50%, ${t.panel} 50%)`;
    if (t.accent === current.accent && t.bg === current.bg) b.classList.add("sel");
    b.onclick = () => saveTheme({ ...t, box: currentTheme.box || "" });  // presets keep the box color
    return b;
  }));
  $("#theme-accent").value = current.accent;
  $("#theme-bg").value = current.panel;
  $("#theme-box").value = current.box || current.panel;
  $("#theme-box-reset").disabled = !current.box;
}
let themeTimer = null;
async function saveTheme(t) {
  const applied = applyTheme(t);
  renderThemes(applied);
  clearTimeout(themeTimer);  // color pickers fire continuously; save once they settle
  themeTimer = setTimeout(() => api("/api/theme", applied).catch((e) => status(e.message, "error")), 400);
}
$("#theme-accent").oninput = (e) => saveTheme({ ...currentTheme, accent: e.target.value });
$("#theme-bg").oninput = (e) => {
  // Panel color picked by hand; page background is a darker shade of it.
  const p = e.target.value, n = parseInt(p.slice(1), 16);
  const dark = "#" + [16, 8, 0].map((sh) => Math.round(((n >> sh) & 255) * 0.55).toString(16).padStart(2, "0")).join("");
  saveTheme({ ...currentTheme, panel: p, bg: dark });
};
$("#theme-box").oninput = (e) => saveTheme({ ...currentTheme, box: e.target.value });
$("#theme-box-reset").onclick = () => saveTheme({ ...currentTheme, box: "" });
// ------------------------------------------------------------ seasonal theme (<themes folder>\<name>\theme.json + overlay.png)
function renderSeason(st) {
  const cfg = st.config || {}, seasons = st.seasons || [];
  const cur = cfg.season || "Default";
  const sel = $("#season-select");
  if (!sel.matches(":focus")) {
    sel.replaceChildren(...seasons.map((s) => el("option", { value: s.id, textContent: s.name, selected: s.id === cur })));
  }
  const info = seasons.find((s) => s.id === cur) || {};
  const isDefault = cur === "Default";
  $("#season-rounds").checked = cfg.seasonRounds !== false;
  $("#season-overlay").checked = cfg.seasonOverlay !== false;
  $("#season-rounds").disabled = isDefault || !info.hasRounds;
  $("#season-overlay").disabled = isDefault || !info.hasOverlay;
  const badge = $("#season-badge");
  badge.textContent = info.name || cur;
  badge.classList.toggle("hidden", isDefault);
}
async function saveSeason() {
  try {
    const r = await api("/api/season", {
      season: $("#season-select").value,
      seasonRounds: $("#season-rounds").checked,
      seasonOverlay: $("#season-overlay").checked,
    });
    overlay = r.overlay;
    const st = await api("/api/state");
    renderSeason(st);
    renderPlayers();
    status(`Theme: ${$("#season-select").selectedOptions[0]?.textContent || "Default"}`, "ok");
    await refresh(true);
  } catch (e) { status(`Theme not changed: ${e.message}`, "error"); }
}
// ------------------------------------------------------------ setups (count + names, set at the start of the night)
function renderSetupSettings() {
  const list = dockSetups.setups;
  $("#setup-count").value = list.length;
  $("#setup-names").replaceChildren(...list.map((x) =>
    el("input", { value: x.name, placeholder: `Setup ${x.index + 1}`, disabled: x.index === 0,
      title: x.index === 0 ? "Main Setup is always there" : `Setup ${x.index + 1} name` })));
  const ss = $("#stream-setup");
  ss.replaceChildren(el("option", { value: "", textContent: "None" }),
    ...list.map((x) => el("option", { value: x.index, textContent: x.name, selected: x.index === dockSetups.streamSetup })));
}
async function saveSetups(count) {
  const names = [...document.querySelectorAll("#setup-names input")].map((i) => i.value.trim());
  const n = Math.max(1, Math.min(16, count ?? names.length));  // Main Setup can't be removed
  while (names.length < n) names.push(`Setup ${names.length + 1}`);
  names.length = n;
  const ss = $("#stream-setup").value;
  try {
    const r = await api("/api/setups", { names, streamSetup: ss === "" ? null : Number(ss) });
    updateSetups(r);
    renderSetupSettings();
    renderBracket();
    status(`${n} setup${n === 1 ? "" : "s"} saved`, "ok");
  } catch (e) { status(`Setups not saved: ${e.message}`, "error"); }
}
$("#setup-count").onchange = (e) => saveSetups(Number(e.target.value) || 0);
$("#setup-names").onchange = () => saveSetups();
$("#stream-setup").onchange = () => saveSetups();

$("#season-select").onchange = saveSeason;
$("#season-rounds").onchange = saveSeason;
$("#season-overlay").onchange = saveSeason;

$("#btn-latest").onclick = async () => {
  try {
    const r = await api("/api/tournament", { tournamentSlug: "", refreshLink: true });
    $("#slug-input").value = r.slug; entrants = []; status(`Loaded ${r.tournament}`, "ok"); await refresh(true);
  } catch (e) { status(e.message, "error"); }
};
$("#btn-slug").onclick = async () => {
  try {
    const r = await api("/api/tournament", { tournamentSlug: $("#slug-input").value.trim() });
    entrants = []; status(`Loaded ${r.tournament}`, "ok"); await refresh(true);
  } catch (e) { status(e.message, "error"); }
};
document.querySelectorAll("dialog [data-close]").forEach((b) => (b.onclick = () => b.closest("dialog").close()));

(async function init() {
  try {
    ensureDialogs();
    const st = await api("/api/state");
    checkUiVersion(st.uiVersion);
    renderThemes(applyTheme(st.config?.theme));
    renderSeason(st);
    overlay = st.overlay;
    prefs = st.prefs || {};
    pollSeconds = Math.max(10, st.config?.pollSeconds || 20);
    $("#slug-input").value = st.config?.tournamentSlug || "";
    // Setup list from the saved config (the bracket poll fills in what's on each one).
    updateSetups({ setups: (st.config?.setups || []).map((name, index) => ({ index, name, on: null })), streamSetup: st.config?.streamSetup });
    renderSetupSettings();
    $("#out-dir").textContent = `Overlay files: ${st.outputDir} · Themes: ${st.themesDir || "?"}`;
    renderPlayers();
    if (!st.tokenSet) {
      status("start.gg token not found. Run set_token.bat (or set the STARTGG_TOKEN user environment variable), then restart the dock. The overlay controls still work by hand.", "error");
      $("#open-sets").replaceChildren(el("p", { className: "muted", textContent: "Bracket unavailable without a token." }));
      return;
    }
    await refresh();
    schedulePoll();
    watchChanges(onRemoteChange);
  } catch (e) {
    status(`Dock server not reachable: ${e.message}. Is start_dock.bat running?`, "error");
  }
})();
