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
  .wrap { max-width: 1200px; margin: 0 auto; padding: 22px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
  .tab { padding: 8px 16px; border-radius: 20px; background: var(--panel2);
    border: 1px solid var(--border); }
  .tab.active { background: var(--accent); color: #04203f; border-color: var(--accent); font-weight: 600; }
  .genre { margin-bottom: 28px; }
  .genre h3 { font-size: 14px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); border-bottom: 1px solid var(--border);
    padding-bottom: 6px; margin-bottom: 12px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
  .card { background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px; display: flex; flex-direction: row; gap: 12px; }
  .card.approved { border-color: var(--green); }
  .card.dismissed { opacity: .45; }
  .card.staged { border-color: var(--purple); }
  .poster { width: 68px; height: 102px; object-fit: cover; border-radius: 6px;
    flex-shrink: 0; background: var(--panel2); }
  .cardBody { display: flex; flex-direction: column; gap: 8px; flex: 1; min-width: 0; }
  .title { font-weight: 600; }
  .rank { display: inline-block; background: var(--accent); color: #04203f;
    font-weight: 700; font-size: 12px; border-radius: 6px; padding: 1px 7px; margin-right: 4px; }
  .rating { color: var(--amber); font-size: 12px; font-weight: 600; white-space: nowrap; }
  .year { color: var(--muted); font-weight: 400; font-size: 13px; }
  .why { color: var(--muted); font-size: 13px; flex: 1; }
  .links { display: flex; gap: 6px; }
  .linkBtn { font-size: 12px; text-decoration: none; padding: 3px 9px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--panel2); color: var(--muted); }
  .linkBtn:hover { border-color: var(--accent); color: var(--text); }
  .actions { display: flex; gap: 6px; margin-top: 4px; flex-wrap: wrap; }
  .actions button { padding: 5px 10px; font-size: 13px; }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; align-self: flex-start; }
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
  <button id="refreshBtn" class="primary" onclick="refresh()">↻ Refresh</button>
</header>
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
  const badge = st ? `<span class="badge ${st}">${st}</span>` : "";
  // Rank chip is the display position (1..N), so the visible list is always
  // contiguous even if server-side filtering left holes in rec.rank.
  const rankHtml = displayRank ? `<span class="rank">#${displayRank}</span>` : "";
  const ratingHtml = rec.rating ? `<span class="rating">★ ${rec.rating}</span>` : "";
  body.innerHTML = `${badge}
    <div class="title">${rankHtml}${rec.title}
      <span class="year">(${rec.year||"—"})</span> ${ratingHtml}</div>
    <div class="why">${rec.why||""}</div>`;

  // External link buttons (only when enrichment supplied them).
  if (rec.imdb_url || rec.tmdb_url) {
    const links = document.createElement("div");
    links.className = "links";
    if (rec.imdb_url) links.appendChild(mkLink("IMDb", rec.imdb_url));
    if (rec.tmdb_url) links.appendChild(mkLink("TMDB", rec.tmdb_url));
    body.appendChild(links);
  }

  const actions = document.createElement("div");
  actions.className = "actions";
  if (st !== "approved" && st !== "staged")
    actions.appendChild(mkBtn("✓ Approve", () => setStatus(rec, "approved")));
  if (st !== "dismissed")
    actions.appendChild(mkBtn("✕ Dismiss", () => setStatus(rec, "dismissed")));
  if (st) actions.appendChild(mkBtn("↺ Reset", () => setStatus(rec, "reset")));
  if (st === "approved" && DATA.staging && DATA.staging.enabled &&
      (ACTIVE === "movies" || ACTIVE === "shows" || ACTIVE === "cartoons")) {
    actions.appendChild(mkBtn("→ Grab", () => stage(rec)));
  }
  body.appendChild(actions);

  div.appendChild(body);
  return div;
}

function mkBtn(label, fn) {
  const b = document.createElement("button");
  b.textContent = label; b.onclick = fn; return b;
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
    toast("Grabbed ✓" + where); render(); }
  else toast("Grab failed: " + out.message);
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
