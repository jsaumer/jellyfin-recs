"""The dashboard single-page UI, served as one self-contained HTML string."""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jellyfin Recommendations</title>
<style>
  :root {
    --bg: #0e1116; --panel: #161b22; --panel2: #1c2129; --border: #2a313c;
    --text: #e6edf3; --muted: #8b949e; --accent: #6ea8fe; --green: #3fb950;
    --red: #f85149; --amber: #d29922; --purple: #bc8cff;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  header { position: sticky; top: 0; z-index: 10; background: var(--panel);
    border-bottom: 1px solid var(--border); padding: 14px 22px;
    display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  .meta { color: var(--muted); font-size: 13px; }
  .spacer { flex: 1; }
  button { font: inherit; cursor: pointer; border: 1px solid var(--border);
    background: var(--panel2); color: var(--text); border-radius: 7px;
    padding: 7px 13px; transition: .15s; }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); color: #04203f; border-color: var(--accent); font-weight: 600; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .wrap { max-width: 1440px; margin: 0 auto; padding: 16px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
  .tab { padding: 8px 16px; border-radius: 20px; background: var(--panel2);
    border: 1px solid var(--border); }
  .tab.active { background: var(--accent); color: #04203f; border-color: var(--accent); font-weight: 600; }
  .genre { margin-bottom: 18px; }
  .genre h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); border-bottom: 1px solid var(--border);
    padding-bottom: 5px; margin-bottom: 9px; }
  /* Dense auto-fill grid: ~4-5 columns at desktop width, 1-2 on mobile. */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; }
  .card { background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 9px; display: flex; flex-direction: row; gap: 9px; }
  .card.approved { border-color: var(--green); }
  .card.dismissed { opacity: .45; }
  .card.staged { border-color: var(--purple); }
  .poster { width: 50px; height: 75px; object-fit: cover; border-radius: 5px;
    flex-shrink: 0; background: var(--panel2); }
  .cardBody { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 0; }
  /* Row 1: rank + title + year + rating on a single ellipsized line. */
  .head { display: flex; align-items: baseline; gap: 4px; min-width: 0; }
  .head .title { font-weight: 600; font-size: 13px; flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rank { background: var(--accent); color: #04203f; font-weight: 700;
    font-size: 11px; border-radius: 5px; padding: 1px 5px; flex-shrink: 0; }
  .rating { color: var(--amber); font-size: 11px; font-weight: 600; flex-shrink: 0; }
  .year { color: var(--muted); font-weight: 400; font-size: 11px; flex-shrink: 0; }
  /* Row 2: why, clamped to 3 lines; click toggles .expanded to show it all. */
  .why { color: var(--muted); font-size: 12px; line-height: 1.45; cursor: pointer;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    overflow: hidden; }
  .why.expanded { -webkit-line-clamp: unset; overflow: visible; }
  /* Bare text links keep row 3 on a single line inside a ~250px card. */
  .linkBtn { font-size: 11px; text-decoration: none; color: var(--muted);
    padding: 0; border: 0; background: none; flex-shrink: 0; }
  .linkBtn:hover { color: var(--accent); text-decoration: underline; }
  /* Row 3: links + compact actions, all inline (wraps only if very narrow). */
  .actions { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: 1px; }
  .actions button { padding: 2px 5px; font-size: 10px; border-radius: 5px; flex-shrink: 0;
    white-space: nowrap; }
  .badge { font-size: 10px; padding: 1px 6px; border-radius: 10px; }
  .badge.approved { background: rgba(63,185,80,.15); color: var(--green); }
  .badge.dismissed { background: rgba(248,81,73,.15); color: var(--red); }
  .badge.staged { background: rgba(188,140,255,.15); color: var(--purple); }
  .empty { color: var(--muted); text-align: center; padding: 60px 20px; }
  .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    background: var(--panel2); border: 1px solid var(--border); padding: 10px 18px;
    border-radius: 8px; opacity: 0; transition: .3s; pointer-events: none; }
  .toast.show { opacity: 1; }
  .stagingPill { font-size: 12px; padding: 3px 10px; border-radius: 12px;
    border: 1px solid var(--border); color: var(--muted); }
  .stagingPill.on { color: var(--green); border-color: var(--green); }
  /* ---- Settings modal ---- */
  .modal { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: none;
    align-items: center; justify-content: center; z-index: 50; padding: 20px; }
  .modal.show { display: flex; }
  .modalCard { background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; width: 100%; max-width: 540px; max-height: 85vh;
    display: flex; flex-direction: column; }
  .modalHead { display: flex; align-items: center; gap: 10px; padding: 13px 16px;
    border-bottom: 1px solid var(--border); }
  .modalHead h2 { font-size: 16px; margin: 0; flex: 1; }
  .modalBody { padding: 16px; overflow-y: auto; display: flex;
    flex-direction: column; gap: 11px; }
  .modalBody h4 { margin: 5px 0 0; font-size: 12px; text-transform: uppercase;
    letter-spacing: .05em; color: var(--muted);
    border-bottom: 1px solid var(--border); padding-bottom: 5px; }
  .modalBody label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .modalBody label.chk { flex-direction: row; align-items: center; gap: 8px; }
  .modalBody input[type=number], .modalBody select { font: inherit; font-size: 13px;
    background: var(--panel2); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 6px 8px; }
  .modalFoot { display: flex; align-items: center; gap: 10px; padding: 13px 16px;
    border-top: 1px solid var(--border); flex-wrap: wrap; }
  .envNote { color: var(--muted); font-size: 11px; flex: 1; min-width: 210px; }
  .warnOpt { color: var(--amber); font-size: 11px; }
  .tmdbFooter { display: flex; align-items: center; justify-content: center;
    gap: 10px; flex-wrap: wrap; padding: 20px; margin-top: 24px;
    border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; }
  .tmdbFooter a { display: inline-flex; }
  .tmdbFooter svg { display: block; }
</style>
</head>
<body>
<header>
  <h1>🎬 Jellyfin Recommendations</h1>
  <span id="genAt" class="meta"></span>
  <span id="routeInfo" class="meta" style="color:var(--purple)"></span>
  <span class="spacer"></span>
  <span id="stagingPill" class="stagingPill">staging: —</span>
  <span id="versionBadge" class="meta" style="font-size:12px"></span>
  <button id="gearBtn" onclick="openSettings()" title="Settings">⚙</button>
  <button id="refreshBtn" class="primary" onclick="refresh()">↻ Refresh</button>
</header>

<div id="settingsModal" class="modal">
  <div class="modalCard">
    <div class="modalHead">
      <h2>⚙ Settings</h2>
      <button onclick="closeSettings()" title="Close">✕</button>
    </div>
    <div class="modalBody" id="settingsBody">Loading ...</div>
    <div class="modalFoot">
      <span class="envNote">API keys and URLs are managed in the deployment
        environment (Komodo), not here.</span>
      <button onclick="closeSettings()">Cancel</button>
      <button class="primary" onclick="saveSettings()">Save</button>
    </div>
  </div>
</div>
<div class="wrap">
  <div class="tabs" id="tabs"></div>
  <div id="content"></div>
</div>
<footer class="tmdbFooter">
  <a href="https://www.themoviedb.org" target="_blank" rel="noopener"
     aria-label="The Movie Database (TMDB)">
    <svg width="60" height="22" viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" role="img">
      <defs>
        <linearGradient id="tmdbg" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#90cea1"/>
          <stop offset="1" stop-color="#01b4e4"/>
        </linearGradient>
      </defs>
      <rect width="60" height="22" rx="4" fill="url(#tmdbg)"/>
      <text x="30" y="15" text-anchor="middle" font-family="Arial, Helvetica, sans-serif"
            font-size="12" font-weight="700" fill="#0d253f">TMDB</text>
    </svg>
  </a>
  <span>This product uses the TMDB API but is not endorsed or certified by TMDB.</span>
</footer>
<div id="toast" class="toast"></div>

<script>
let DATA = null;
let ACTIVE = "movies";
const TABS = [
  ["movies", "🎬 Movies"], ["shows", "📺 TV Shows"], ["cartoons", "🎨 Cartoons"],
];

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

function keyOf(title, year) { return title + "|" + year; }

async function load() {
  const res = await fetch("/api/recommendations");
  DATA = await res.json();
  renderTabs();
  render();
  const recs = DATA.recommendations || {};
  if (DATA.version) {
    document.getElementById("versionBadge").textContent = "v" + DATA.version;
  }
  if (recs._generated_at) {
    const d = new Date(recs._generated_at * 1000);
    document.getElementById("genAt").textContent = "updated " + d.toLocaleString();
  }
  const s = DATA.staging || {};
  const pill = document.getElementById("stagingPill");
  if (s.enabled) {
    pill.textContent = "staging: on"; pill.classList.add("on");
    const r = s.routing || {};
    let routeTxt = [];
    if (r.shows) routeTxt.push("TV→" + r.shows);
    if (r.cartoons) routeTxt.push("Cartoons→" + r.cartoons);
    document.getElementById("routeInfo").textContent = routeTxt.join("   ·   ");
  } else {
    pill.textContent = "staging: off (dashboard-only)";
    document.getElementById("routeInfo").textContent = "";
  }
}

function renderTabs() {
  const el = document.getElementById("tabs");
  el.innerHTML = "";
  for (const [key, label] of TABS) {
    const b = document.createElement("div");
    b.className = "tab" + (key === ACTIVE ? " active" : "");
    b.textContent = label;
    b.onclick = () => { ACTIVE = key; renderTabs(); render(); };
    el.appendChild(b);
  }
}

function statusOf(title, year) {
  const st = (DATA.state || {})[keyOf(title, year)];
  return st ? st.status : null;
}

function card(rec, displayRank) {
  const st = statusOf(rec.title, rec.year);
  const div = document.createElement("div");
  div.className = "card" + (st ? " " + st : "");

  // Poster thumbnail (best-effort — hide gracefully if absent or broken).
  if (rec.poster) {
    const img = document.createElement("img");
    img.className = "poster"; img.src = rec.poster; img.alt = "";
    img.loading = "lazy";
    img.onerror = () => img.remove();
    div.appendChild(img);
  }

  const body = document.createElement("div");
  body.className = "cardBody";

  // Row 1 — rank + title + (year) + ★rating on one ellipsized line.
  // Rank chip is the display position (1..N), so the visible list is always
  // contiguous even if server-side filtering left holes in rec.rank.
  const head = document.createElement("div");
  head.className = "head";
  const rankHtml = displayRank ? `<span class="rank">#${displayRank}</span>` : "";
  const ratingHtml = rec.rating ? `<span class="rating">★${rec.rating}</span>` : "";
  head.innerHTML = `${rankHtml}<span class="title">${rec.title}</span>` +
    `<span class="year">(${rec.year||"—"})</span>${ratingHtml}`;
  const t = head.querySelector(".title");
  if (t) t.title = rec.title;          // full title on hover when ellipsized
  body.appendChild(head);

  // Row 2 — why, clamped to 3 lines; click toggles full text.
  const why = document.createElement("div");
  why.className = "why";
  why.textContent = rec.why || "";
  why.title = "Click to expand / collapse";
  why.onclick = () => why.classList.toggle("expanded");
  body.appendChild(why);

  // Row 3 — status badge, IMDb/TMDB links, and compact actions, all inline.
  const actions = document.createElement("div");
  actions.className = "actions";
  if (st) {
    const b = document.createElement("span");
    b.className = "badge " + st; b.textContent = st;
    actions.appendChild(b);
  }
  if (rec.imdb_url) actions.appendChild(mkLink("IMDb", rec.imdb_url));
  if (rec.tmdb_url) actions.appendChild(mkLink("TMDB", rec.tmdb_url));
  if (st !== "approved" && st !== "staged")
    actions.appendChild(mkBtn("✓ Approve", () => setStatus(rec, "approved")));
  if (st !== "dismissed")
    actions.appendChild(mkBtn("✕ Dismiss", () => setStatus(rec, "dismissed")));
  if (st) actions.appendChild(mkBtn("↺", () => setStatus(rec, "reset"), "Reset"));
  if (st === "approved" && DATA.staging && DATA.staging.enabled &&
      (ACTIVE === "movies" || ACTIVE === "shows" || ACTIVE === "cartoons")) {
    actions.appendChild(mkBtn("→ Grab", () => stage(rec)));
  }
  body.appendChild(actions);

  div.appendChild(body);
  return div;
}

function mkBtn(label, fn, tip) {
  const b = document.createElement("button");
  b.textContent = label; b.onclick = fn;
  if (tip) b.title = tip;
  return b;
}

function mkLink(label, url) {
  const a = document.createElement("a");
  a.className = "linkBtn"; a.textContent = label;
  a.href = url; a.target = "_blank"; a.rel = "noopener";
  return a;
}

function gridOf(list, showRank) {
  const grid = document.createElement("div");
  grid.className = "cards";
  // Number by display position so ranked lists are always contiguous #1..#N.
  (list || []).forEach((r, i) => grid.appendChild(card(r, showRank ? i + 1 : null)));
  return grid;
}

function section(title, list, showRank) {
  const g = document.createElement("div");
  g.className = "genre";
  g.innerHTML = `<h3>${title}</h3>`;
  g.appendChild(gridOf(list, showRank));
  return g;
}

function render() {
  const c = document.getElementById("content");
  c.innerHTML = "";
  const recs = DATA.recommendations || {};
  if (!recs || Object.keys(recs).length === 0) {
    c.innerHTML = `<div class="empty">No recommendations yet.<br>
      Click <b>Refresh</b> to generate your first set.</div>`;
    return;
  }

  // movies / shows / cartoons: ranked Top 10 first, then capped genre sections.
  let rendered = false;
  const top = recs["top10_" + ACTIVE] || [];   // top10_movies/shows/cartoons
  if (top.length) {
    c.appendChild(section("🏆 Top 10", top, true));
    rendered = true;
  }

  // Documentaries live inside the Movies tab as a ranked Top 3, between the
  // movie Top 10 and the genre sections.
  if (ACTIVE === "movies") {
    const docs = recs.top3_documentaries || [];
    if (docs.length) {
      c.appendChild(section("🎬 Top 3 Documentaries", docs, true));
      rendered = true;
    }
  }

  // Genre deep-dives exist only for movies/shows (cartoons is Top 10 only).
  const genres = recs[ACTIVE];
  if (genres && !Array.isArray(genres)) {
    for (const genre of Object.keys(genres)) {
      const items = genres[genre] || [];
      if (!items.length) continue;
      c.appendChild(section(genre, items, false));
      rendered = true;
    }
  }

  if (!rendered) c.innerHTML = `<div class="empty">Nothing here yet.</div>`;
}

async function setStatus(rec, status) {
  await fetch("/api/item", { method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({title: rec.title, year: rec.year, status}) });
  const k = keyOf(rec.title, rec.year);
  if (status === "reset") delete DATA.state[k];
  else DATA.state[k] = {status};
  render();
}

async function stage(rec) {
  toast("Grabbing " + rec.title + " ...");
  const res = await fetch("/api/stage", { method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({title: rec.title, year: rec.year, category: ACTIVE,
                          tmdb_id: rec.tmdb_id, tvdb_id: rec.tvdb_id}) });
  const out = await res.json();
  if (out.ok) { DATA.state[keyOf(rec.title, rec.year)] = {status:"staged"};
    const where = out.result && out.result.root ? " → " + out.result.root : "";
    // A substituted quality profile is never applied silently.
    toast(out.profile_drift ? "⚠ " + out.profile_drift : "Grabbed ✓" + where);
    render(); }
  else toast("Grab failed: " + out.message);
}

/* ----------------------------- settings ---------------------------------- */
let SETTINGS = null, PROFILES = null;

async function openSettings() {
  document.getElementById("settingsModal").classList.add("show");
  document.getElementById("settingsBody").textContent = "Loading ...";
  const s = await (await fetch("/api/settings")).json();
  SETTINGS = s.settings;
  renderSettings();                       // paint immediately ...
  try {                                   // ... then fill in live profiles
    PROFILES = await (await fetch("/api/profiles")).json();
    renderSettings();
  } catch (e) { /* profiles are best-effort */ }
}

function closeSettings() {
  document.getElementById("settingsModal").classList.remove("show");
}

// Dropdown of live quality profiles: "<name> — used by <n> of <total>", with
// the majority profile marked as the library default. The stored value is the
// NAME, never the id (ids get renumbered by Profilarr re-syncs).
function profileSelect(app, key) {
  const cur = SETTINGS[key] || "";
  const data = PROFILES ? PROFILES[app] : null;
  if (!data) return `<select id="${key}" disabled><option>loading ...</option></select>`;
  if (data.error)
    return `<div class="warnOpt">${app} unavailable — ${data.error}</div>`;
  let opts = `<option value=""${cur === "" ? " selected" : ""}>Auto (library default)</option>`;
  let known = false;
  for (const p of data.profiles) {
    const isCur = cur.toLowerCase() === p.name.toLowerCase();
    if (isCur) known = true;
    const dflt = p.is_default ? " (library default)" : "";
    opts += `<option value="${p.name}"${isCur ? " selected" : ""}>` +
            `${p.name} — used by ${p.count} of ${data.total}${dflt}</option>`;
  }
  // A configured name that no longer exists stays visible, so the drift is
  // obvious in the UI rather than silently snapping to something else.
  if (cur && !known)
    opts += `<option value="${cur}" selected>${cur} — ⚠ not found in ${app}</option>`;
  return `<select id="${key}">${opts}</select>`;
}

function renderSettings() {
  const s = SETTINGS;
  const sel = (v, want) => (v === want ? " selected" : "");
  document.getElementById("settingsBody").innerHTML = `
    <h4>Recommendations</h4>
    <label>Refresh interval (hours)
      <input type="number" min="1" id="refresh_interval_hours" value="${s.refresh_interval_hours}"></label>
    <label>Recommendations per genre
      <input type="number" min="1" id="recs_per_genre" value="${s.recs_per_genre}"></label>

    <h4>Staging</h4>
    <label class="chk"><input type="checkbox" id="staging_enabled"
      ${s.staging_enabled ? "checked" : ""}> Staging enabled</label>
    <label class="chk"><input type="checkbox" id="search_on_grab_movies"
      ${s.search_on_grab_movies ? "checked" : ""}> Search on grab — Movies</label>
    <label>Search on grab — TV &amp; Cartoons
      <select id="search_on_grab_tv">
        <option value="off"${sel(s.search_on_grab_tv, "off")}>Off (queue only)</option>
        <option value="first_season"${sel(s.search_on_grab_tv, "first_season")}>First season only</option>
        <option value="all"${sel(s.search_on_grab_tv, "all")}>All missing episodes</option>
      </select></label>

    <h4>Quality profiles</h4>
    <label>Radarr — Movies ${profileSelect("radarr", "radarr_quality_profile")}</label>
    <label>Sonarr — TV &amp; Cartoons ${profileSelect("sonarr", "sonarr_quality_profile")}</label>`;
}

async function saveSettings() {
  const val = id => document.getElementById(id);
  const payload = {
    refresh_interval_hours: parseInt(val("refresh_interval_hours").value, 10),
    recs_per_genre: parseInt(val("recs_per_genre").value, 10),
    staging_enabled: val("staging_enabled").checked,
    search_on_grab_movies: val("search_on_grab_movies").checked,
    search_on_grab_tv: val("search_on_grab_tv").value,
  };
  // Only send profile names when the dropdowns actually rendered.
  for (const k of ["radarr_quality_profile", "sonarr_quality_profile"]) {
    const el = val(k);
    if (el && el.tagName === "SELECT" && !el.disabled) payload[k] = el.value;
  }
  const res = await fetch("/api/settings", { method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload) });
  const out = await res.json();
  if (!res.ok || !out.ok) { toast("Save failed: " + (out.message || res.status)); return; }
  SETTINGS = out.settings;
  toast("Settings saved ✓");
  closeSettings();
  load();                    // staging pill / routing may have changed
}

async function refresh() {
  const btn = document.getElementById("refreshBtn");
  btn.disabled = true; btn.textContent = "Refreshing ...";
  const res = await fetch("/api/refresh", {method:"POST"});
  if (res.status === 409) { toast("Already running."); btn.disabled=false; btn.textContent="↻ Refresh"; return; }
  const poll = setInterval(async () => {
    const s = await (await fetch("/api/refresh/status")).json();
    if (!s.running) {
      clearInterval(poll);
      btn.disabled = false; btn.textContent = "↻ Refresh";
      if (s.last_error) toast("Error: " + s.last_error);
      else { toast("Updated ✓"); load(); }
    }
  }, 1500);
}

load();
</script>
</body>
</html>
"""
