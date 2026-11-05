// Knockout Luck dashboard. Reads data.json (written by src/export_site.py) and draws
// everything with plain SVG, so the page needs no libraries and no build step.

const SVG = "http://www.w3.org/2000/svg";
const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;
// For chances shown to readers: never round a near-certainty up to 100% or down to 0%.
const chance = (x) => (x > 0.995 && x < 1 ? ">99%" : x < 0.005 && x > 0 ? "<1%" : pct(x));
// Club names as fans say them. The sources use their own spellings ("Ath Madrid", "FC Porto (POR)").
const CLUB_NAMES = {
  "AFC Ajax": "Ajax", "Ath Madrid": "Atlético Madrid", "Celtic FC": "Celtic", "Club Brugge KV": "Club Brugge",
  "Dinamo Kiev": "Dynamo Kyiv", "Ein Frankfurt": "Eintracht Frankfurt", "FC Basel 1893": "Basel",
  "FC København": "Copenhagen", "FC Porto": "Porto", "FK Bodø/Glimt": "Bodø/Glimt", "KAA Gent": "Gent",
  "M'gladbach": "Gladbach", "Malaga": "Málaga", "Man City": "Manchester City", "Man United": "Manchester United",
  "Olympiakos": "Olympiacos", "ŠK Slovan Bratislava": "Slovan Bratislava", "Slavia Praha": "Slavia Prague", "AEK Athen": "AEK Athens", "PSV": "PSV Eindhoven", "Paris SG": "Paris Saint-Germain", "Sociedad": "Real Sociedad",
  "Zenit St. Petersburg": "Zenit",
  "Inter": "Inter Milan", "Milan": "AC Milan",
  "Leicester": "Leicester City", "Newcastle": "Newcastle United",
};
const clean = (name) => { const plain = name.replace(/ \([A-Z]{3}\)$/, ""); return CLUB_NAMES[plain] || plain; };
// Does a club match what a fan typed? Either way of saying it works: "Man City" or "Manchester City".
const called = (name, query) => clean(name).toLowerCase().includes(query) || name.replace(/ \([A-Z]{3}\)$/, "").toLowerCase().includes(query);
const ROUND_SHORT = { "Playoffs": "Play-offs", "Round of 16": "Last 16", "Quarterfinals": "Quarter-finals", "Semifinals": "Semi-finals", "Final": "Final" };

function svg(tag, attrs = {}, parent) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

function canvas(container, height) {
  if (tipOwner && container.contains(tipOwner)) hideTip(); // its element is about to be redrawn away
  container.innerHTML = "";
  const width = Math.max(container.clientWidth, 280);
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height }, container);
  return { root, width, height };
}

// ---------- tooltip ----------
// A tooltip belongs to the element that opened it, and hides as soon as the pointer is
// anywhere else. "pointerleave" alone isn't enough: it never comes if the pointer leaves the
// window quickly or the chart is redrawn under it, and the tooltip would stay up.
const tip = document.getElementById("tip");
let tipOwner = null;
function showTip(html, event, owner = event.currentTarget) {
  tipOwner = owner;
  tip.innerHTML = html;
  tip.classList.add("on");
  const pad = 14;
  const box = tip.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
function hideTip() {
  tipOwner = null;
  tip.classList.remove("on");
}
document.addEventListener("pointermove", (e) => {
  if (tipOwner && e.pointerType !== "touch" && (!tipOwner.isConnected || !tipOwner.contains(e.target))) hideTip();
}, { passive: true });
// (A finger "leaves" the page whenever it lifts, so touch is left to the tap-elsewhere rule.)
document.documentElement.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") hideTip(); });
window.addEventListener("blur", hideTip);
// Mouse: the tooltip follows the pointer. Touch sends no pointermove for a tap and leaves as
// soon as the finger lifts, so a tap shows the tooltip and it stays until the next tap or scroll.
// `html` can be a function, for tooltips whose text depends on the moment they are shown.
function hover(node, html, onPick) {
  const text = () => (typeof html === "function" ? html() : html);
  node.addEventListener("pointermove", (e) => { if (e.pointerType !== "touch") showTip(text(), e); });
  node.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") hideTip(); });
  node.addEventListener("pointerdown", (e) => { if (e.pointerType === "touch") showTip(text(), e); });
  if (onPick) node.addEventListener("click", onPick);
}
document.addEventListener("pointerdown", (e) => { if (e.pointerType === "touch" && !e.target.closest(".chart, .term")) hideTip(); });

// ---------- glossary ----------
// The few terms that are left in the text. Dotted words open a one-line definition on hover,
// tap or keyboard focus, so a reader never has to leave the page to look something up.
const GLOSSARY = {
  "pre-match": ["Pre-match chance", "A team's chance of going through, worked out by the model before the first leg using only matches played earlier. If a tie were replayed ten times from the same start, a team with 70% would win about seven of them."],
  "closing-odds": ["Final (closing) odds", "The bookmakers' odds just before kick-off. By then they include team news and all the money that has been bet, so they're the hardest benchmark to beat."],
  "dixon-coles": ["Dixon–Coles", "A model that works out how many goals each side would score and concede against an average opponent, then turns that into the chances of a win, draw or loss."],
  "league-phase": ["League phase", "The opening stage since 2024-25. 36 clubs each play eight different opponents, and one table ranks them all. The top eight go straight to the last 16, 9th to 24th play off for the other eight places, and the rest are out."],
  "simulation": ["Simulation", "Playing the rest of the season out on a computer, match by match, using the model's chances for each. Do it many thousands of times and the share of seasons in which a club gets to a stage is its chance of getting there."],
  "elo": ["Elo", "A rating borrowed from chess. Each club has one number that goes up after a win and down after a loss, by more when the result was a surprise."],
};
function setupGlossary() {
  document.querySelectorAll(".term").forEach((node) => {
    const entry = GLOSSARY[node.dataset.term];
    if (!entry) return;
    const [title, text] = entry;
    node.setAttribute("aria-description", `${title}: ${text}`);
    hover(node, `<b>${title}</b><br>${text}`);
    // Keyboard: show it under the word once the page has stopped scrolling to it. (The page
    // scrolls smoothly, and scrolling hides tooltips, so showing it straight away would be undone.)
    node.addEventListener("focus", () => {
      let lastTop = null, frames = 0;
      const settle = () => {
        if (document.activeElement !== node || ++frames > 300) return; // a long smooth scroll takes ~2s
        const box = node.getBoundingClientRect();
        if (box.top !== lastTop) { lastTop = box.top; requestAnimationFrame(settle); return; }
        showTip(`<b>${title}</b><br>${text}`, { clientX: box.left, clientY: box.bottom - 10 }, node);
      };
      requestAnimationFrame(settle);
    });
    node.addEventListener("blur", () => { if (tipOwner === node) hideTip(); });
    node.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
  });
}

function legend(id, items) {
  document.getElementById(id).innerHTML = items
    .map(([label, color, kind]) => `<span><i class="${kind || ""}" style="background:${color}"></i>${label}</span>`)
    .join("");
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// One more tie. dist[k] is the chance of exactly k wins so far; p is the chance of winning this one.
function addTie(dist, p) {
  const next = new Array(dist.length + 1).fill(0);
  dist.forEach((q, k) => { next[k] += q * (1 - p); next[k + 1] += q * p; });
  return next;
}

// "1 in N": how rarely a club would win at least as many ties as it did if the model's tie
// chances were right. Exact (the tail of a Poisson-binomial distribution), not a normal
// approximation, which says 1 in 11,600 for Real Madrid instead of 1 in 10,200.
function oddsOfDoingAsWell(ties, club) {
  const mine = ties.filter((t) => t.team_a === club || t.team_b === club);
  let dist = [1]; // dist[k]: chance of exactly k ties won so far
  for (const t of mine) dist = addTie(dist, t.team_a === club ? t.p_a : 1 - t.p_a);
  const won = mine.filter((t) => t.winner === club).length;
  const tail = dist.slice(won).reduce((a, b) => a + b, 0);
  return tail > 0 ? Number((1 / tail).toPrecision(3)).toLocaleString("en-GB") : "";
}

// Plain names for the models, wherever a reader sees them.
const MODEL_NAMES = {
  "Dixon–Coles": "Our model",
  "Elo": "Simple ratings (Elo)",
  "Base rates": "Knowing nothing",
  "Average of Elo and Dixon–Coles": "Our model and Elo, averaged",
  "Bookmakers (closing)": "Bookmakers",
};

// ---------- headline ----------
function fillHeadline(data) {
  const h = data.headline;
  const fills = {
    seasons: `${h.first_season} to ${h.last_season} · ${h.ties} ties`,
    ties: h.ties,
    underdog: pct(h.underdog),
    "median-run": pct(h.median_champion_run),
    real: `${h.real_won} of ${h.real_ties}`,
    "real-label": `ties won by Real Madrid, when the model expected about ${Math.round(h.real_expected)}`,
    "real-won": `${h.real_won} of ${h.real_ties}`,
    "real-expected": h.real_expected.toFixed(1),
    "test-matches": data.scores[0].matches.toLocaleString("en-GB"),
    finals: data.rounds.find((r) => r.round === "Final")?.ties ?? "",
    "real-odds": oddsOfDoingAsWell(data.ties, "Real Madrid"),
    built: data.built,
  };
  document.querySelectorAll("[data-fill]").forEach((node) => { node.textContent = fills[node.dataset.fill] ?? ""; });
}

// ---------- season strip ----------
const ROUND_TINY = { "Playoffs": "PO", "Round of 16": "L16", "Quarterfinals": "QF", "Semifinals": "SF", "Final": "F" };
// Every tie side by side, season by season, grouped by round (play-offs to final) within a
// season. Choosing a season, here or in the Season filter, zooms the strip into it: the same
// bars spread out to fill the width and are labelled with who went through. Changing season
// pans across; "All seasons" zooms back out. The club, round and upsets filters fade the
// ties that don't match, so the strip always shows what the list below shows.
function setupTicker(data) {
  const box = document.getElementById("ticker-chart");
  const nav = document.getElementById("strip-nav");
  const f = { season: document.getElementById("f-season"), round: document.getElementById("f-round"),
    club: document.getElementById("f-club"), against: document.getElementById("f-against"), upsets: document.getElementById("f-upsets") };
  const seasons = [...new Set(data.ties.map((t) => t.season))].sort();
  const ties = data.ties.map((t) => ({ ...t, p: winnerChance(t) }))
    .sort((a, b) => a.season.localeCompare(b.season) || ROUND_ORDER[a.round] - ROUND_ORDER[b.round] || b.p - a.p);
  // Positions in "tie units": each bar is 0.8 wide, with wider gaps between rounds and seasons.
  let u = 0;
  ties.forEach((t, i) => {
    const prev = ties[i - 1];
    if (prev) u += prev.season !== t.season ? 4 : prev.round !== t.round ? 1.7 : 1;
    t.u = u;
  });
  const bounds = (season) => {
    const mine = ties.filter((t) => !season || t.season === season);
    return [mine[0].u, mine[mine.length - 1].u + 0.8];
  };
  let view = f.season.value || null, nodes = null, geo = null, frame = 0;

  // The vertical scale never changes, so the axis and the 50% line stay put while bars move.
  function layout(season) {
    // Below 420px the zoomed bars are too thin to name, so there's no room kept for names.
    const W = Math.max(box.clientWidth, 280), narrow = W < 560, names = W >= 420;
    const m = { l: 38, r: 6, t: 22, b: names ? 100 : 46 };
    const H = names ? 270 : 210;
    const [a, b] = bounds(season);
    const k = (W - m.l - m.r) / (b - a); // pixels per tie unit
    return { W, H, m, k, narrow, names, zoom: Boolean(season), x: (v) => m.l + (v - a) * k, y: (v) => m.t + (1 - v) * (H - m.t - m.b) };
  }
  const geometry = (L) => ties.map((t) => ({ x: L.x(t.u), w: Math.max(0.8 * L.k, 0.7), y: L.y(t.p), h: L.y(0) - L.y(t.p) }));
  function place(g) {
    nodes.rects.forEach((r, i) => {
      r.setAttribute("x", g[i].x);
      r.setAttribute("width", g[i].w);
      r.setAttribute("y", g[i].y);
      r.setAttribute("height", g[i].h);
    });
  }

  function build() {
    cancelAnimationFrame(frame);
    const L = layout(view);
    const { root } = canvas(box, L.H);
    const clip = svg("clipPath", { id: "strip-clip" }, svg("defs", {}, root));
    svg("rect", { x: L.m.l - 1, y: 0, width: L.W - L.m.l - L.m.r + 2, height: L.H }, clip);
    // Axis: 0, 50% (dotted, the line between favourite and underdog) and 100%.
    [0, 0.5, 1].forEach((v) => {
      svg("line", { x1: L.m.l, x2: L.W - L.m.r, y1: L.y(v), y2: L.y(v), stroke: v === 0.5 ? css("--ink") : css("--grid"),
        "stroke-dasharray": v === 0.5 ? "2 3" : "none", opacity: v === 0.5 ? 0.5 : 1 }, root);
      svg("text", { x: L.m.l - 6, y: L.y(v) + 4, "text-anchor": "end" }, root).textContent = pct(v);
    });
    const bars = svg("g", { "clip-path": "url(#strip-clip)" }, root);
    nodes = { root, labels: svg("g", {}, root), names: [] };
    nodes.rects = ties.map((t) => {
      const r = svg("rect", { fill: t.p < 0.5 ? css("--s2") : css("--s1"), class: "grow strip-bar", style: `--d:${seasons.indexOf(t.season) * 55}ms` }, bars);
      hover(r, () => `<b>${t.season}, ${ROUND_SHORT[t.round]}</b><br>${clean(t.winner)} beat ${clean(loserOf(t))}<br>${scoreTip(t)}<br>` +
        `${pct(t.p)} chance beforehand${t.p < 0.35 ? " · an upset" : t.p < 0.5 ? " · the underdog" : ""}` +
        (view ? "" : `<br><span style="opacity:.6">Click to zoom into this season</span>`),
        () => { if (!view) filterTies({ season: t.season }); });
      return r;
    });
    geo = geometry(L);
    place(geo);
    label(L);
    update();
  }

  // Labels for the current view: season names when zoomed out; rounds, winners and chances when in.
  function label(L) {
    nodes.labels.innerHTML = "";
    nodes.names = [];
    const g = nodes.labels;
    const base = L.y(0);
    if (!L.zoom) {
      seasons.forEach((season, i) => {
        if (L.narrow && i % 2) return;
        const [a, b] = bounds(season);
        svg("text", { x: (L.x(a) + L.x(b)) / 2, y: base + 15, "text-anchor": "middle", class: "strip-label" }, g).textContent = L.narrow ? `’${season.slice(5)}` : season;
      });
      svg("text", { x: (L.m.l + L.W - L.m.r) / 2, y: base + (L.narrow ? 36 : 44), "text-anchor": "middle", class: "strip-label" }, g)
        .textContent = "Click a season to zoom in";
      return;
    }
    const mine = ties.filter((t) => t.season === view);
    [...new Set(mine.map((t) => t.round))].forEach((round) => {
      const inRound = mine.filter((t) => t.round === round);
      const a = L.x(inRound[0].u), b = L.x(inRound[inRound.length - 1].u + 0.8);
      svg("line", { x1: a, x2: b, y1: base + 5, y2: base + 5, stroke: css("--axis") }, g);
      const text = b - a > ROUND_SHORT[round].length * 7 ? ROUND_SHORT[round] : ROUND_TINY[round];
      svg("text", { x: (a + b) / 2, y: L.H - 6, "text-anchor": "middle", class: "strip-label label-strong" }, g).textContent = text;
    });
    const w = 0.8 * L.k;
    mine.forEach((t) => {
      const i = ties.indexOf(t), cx = L.x(t.u) + w / 2;
      const name = L.names && w >= 14 ? svg("text", { x: cx + 3, y: base + 14, "text-anchor": "end", transform: `rotate(-55 ${cx + 3} ${base + 14})`, class: "strip-label strip-name" }, g) : null;
      if (name) name.textContent = shortClub(t.winner).slice(0, 10);
      const chanceLabel = w >= 24 ? svg("text", { x: cx, y: L.y(t.p) - 5, "text-anchor": "middle", class: "strip-label" }, g) : null;
      if (chanceLabel) chanceLabel.textContent = pct(t.p);
      nodes.names[i] = [name, chanceLabel].filter(Boolean);
    });
  }

  // Fade what the other filters exclude, and show the season controls when zoomed in.
  function update() {
    const passes = tieFilter(false); // the season is the strip's zoom, not a filter
    ties.forEach((t, i) => {
      const match = passes(t);
      nodes.rects[i].style.opacity = match ? 1 : 0.15;
      (nodes.names[i] || []).forEach((n) => { n.style.opacity = match ? 1 : 0.3; });
    });
    nav.hidden = !view;
    box.classList.toggle("zoomed", Boolean(view));
    if (view) {
      const at = seasons.indexOf(view);
      const [prev, next] = [seasons[at - 1], seasons[at + 1]];
      nav.querySelector("[data-step='-1']").disabled = !prev;
      nav.querySelector("[data-step='-1'] span").textContent = prev || "";
      nav.querySelector("[data-step='1']").disabled = !next;
      nav.querySelector("[data-step='1'] span").textContent = next || "";
      nav.querySelector("b").textContent = view;
    }
  }

  // Zoom (or pan) from wherever the bars are now to the new view.
  function show(season) {
    if (season === view) return update();
    view = season;
    const L = layout(view);
    const from = geo, to = geometry(L);
    geo = to;
    nodes.labels.innerHTML = ""; // the old labels go at once; the new ones arrive with the bars
    nodes.names = [];
    update();
    cancelAnimationFrame(frame);
    const start = performance.now(), duration = STILL ? 0 : 750;
    const ease = (q) => (q < 0.5 ? 4 * q ** 3 : 1 - (-2 * q + 2) ** 3 / 2);
    const step = (now) => {
      const q = duration ? Math.min(1, (now - start) / duration) : 1, e = ease(q);
      place(from.map((a, i) => ({ x: a.x + (to[i].x - a.x) * e, w: a.w + (to[i].w - a.w) * e, y: to[i].y, h: to[i].h })));
      if (q < 1) frame = requestAnimationFrame(step);
      else { label(L); update(); }
    };
    if (duration) frame = requestAnimationFrame(step);
    else step(start);
  }

  f.season.addEventListener("change", () => show(f.season.value || null));
  [f.round, f.upsets].forEach((n) => n.addEventListener("change", update));
  [f.club, f.against].forEach((n) => n.addEventListener("input", update));
  nav.addEventListener("click", (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    const at = seasons.indexOf(view);
    filterTies({ season: button.dataset.all !== undefined ? "" : seasons[at + Number(button.dataset.step)] });
  });
  return build;
}

// Point the tie explorer somewhere, as if the reader had picked it. Only the fields given
// change, so clicking a season keeps the reader's own club search and other filters.
function filterTies(changes, scroll = false) {
  const fields = { season: "f-season", round: "f-round", club: "f-club", against: "f-against" };
  for (const [key, id] of Object.entries(fields)) if (key in changes) document.getElementById(id).value = changes[key];
  if ("club" in changes && !("against" in changes)) document.getElementById("f-against").value = ""; // a new club is a new search
  if ("upsets" in changes) document.getElementById("f-upsets").checked = changes.upsets;
  document.getElementById("f-season").dispatchEvent(new Event("change"));
  hideTip();
  if (scroll) document.querySelector("#ties .ticker").scrollIntoView({ behavior: STILL ? "auto" : "smooth" });
}

// ---------- champions' runs ----------
function drawRuns(data) {
  const box = document.getElementById("runs-chart");
  const runs = data.champions;
  // Full season and club labels need about 66px per bar; otherwise fall back to "’13".
  const narrow = (box.clientWidth - 44) / runs.length < 66;
  const { root, width, height } = canvas(box, narrow ? 260 : 300);
  const m = { l: 36, r: 8, t: 22, b: narrow ? 46 : 52 };
  const top = Math.ceil(Math.max(...runs.map((r) => r.probability)) * 10) / 10;
  const y = (v) => m.t + (1 - v / top) * (height - m.t - m.b);
  const step = (width - m.l - m.r) / runs.length;
  const barWidth = Math.min(44, step - 4);

  for (let v = 0; v <= top + 1e-9; v += 0.1) {
    svg("line", { x1: m.l, x2: width - m.r, y1: y(v), y2: y(v), stroke: css("--grid") }, root);
    svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = pct(v);
  }
  svg("line", { x1: m.l, x2: width - m.r, y1: y(0), y2: y(0), stroke: css("--axis") }, root);

  const most = runs.reduce((a, b) => (b.probability > a.probability ? b : a));
  const least = runs.reduce((a, b) => (b.probability < a.probability ? b : a));
  runs.forEach((run, i) => {
    const cx = m.l + step * (i + 0.5);
    const top_y = y(run.probability);
    const h = y(0) - top_y;
    // Each bar, its labels and its hover zone share a group, so the other bars can be faded.
    const col = svg("g", { class: "bar-col" }, root);
    svg("rect", { x: cx - barWidth / 2, y: top_y, width: barWidth, height: h, fill: run === least ? css("--s2") : css("--s1"), class: "grow bar", style: `--d:${i * 45}ms` }, col);
    if (run === most || run === least) {
      svg("text", { x: cx, y: top_y - 6, "text-anchor": "middle", class: "label-strong" }, root).textContent = pct(run.probability);
    }
    const season = svg("text", { x: cx, y: y(0) + 16, "text-anchor": "middle" }, root);
    season.textContent = narrow ? `’${run.season.slice(5)}` : run.season; // "2012-13" -> "’13"
    if (!narrow) {
      const name = svg("text", { x: cx, y: y(0) + 31, "text-anchor": "middle" }, root);
      name.textContent = shortClub(run.champion);
    }
    // The hover zone is the bar plus a little room above it and the labels below, not the
    // whole column: the empty space above a short bar shouldn't count as the bar.
    const hit = svg("rect", { x: cx - step / 2, y: top_y - 12, width: step, height: height - top_y + 12, class: "hit" }, col);
    hover(hit, `<b>${run.season}: ${clean(run.champion)}</b><br>${pct(run.probability, 1)} chance of winning every tie<br>${run.ties.map((t) => `${ROUND_SHORT[t.round]} v ${clean(t.opponent)}: ${pct(t.probability)}`).join("<br>")}`,
      () => showPath(run));
    // Fade the other bars while this one is pointed at. (A CSS :has(:hover) rule did this, but
    // WebKit on Linux doesn't re-check it, nor always send pointerenter, as the pointer moves;
    // pointermove, which the tooltip uses, always arrives.)
    const light = () => { root.classList.add("focusing"); col.classList.add("lit"); };
    hit.addEventListener("pointerenter", light);
    hit.addEventListener("pointermove", light);
    hit.addEventListener("pointerleave", () => { root.classList.remove("focusing"); col.classList.remove("lit"); });
  });
  if (chosenRun) showPath(chosenRun, true);
  else showPath(least);
}

function shortClub(name) {
  const map = {
    "Bayern Munich": "Bayern", "Real Madrid": "Real", "Man City": "Man City", "Man United": "Man Utd", "Paris SG": "PSG",
    "Barcelona": "Barça", "Ath Madrid": "Atlético", "Ein Frankfurt": "Frankfurt", "Newcastle": "Newcastle",
    "Leicester": "Leicester", "PSV": "PSV", "Sociedad": "Sociedad", "Shakhtar Donetsk": "Shakhtar", "Zenit St. Petersburg": "Zenit",
  };
  return map[name] || clean(name);
}

// A champion's run as a funnel: each tie multiplies the chance down, and the bars drain in turn.
let chosenRun = null;
function setupRunPicker(data) {
  const select = document.getElementById("runs-pick");
  select.innerHTML = data.champions.map((r) => `<option value="${r.season}">${r.season}: ${clean(r.champion)}</option>`).join("");
  select.addEventListener("change", () => showPath(data.champions.find((r) => r.season === select.value)));
}

function showPath(run, quiet) {
  chosenRun = run;
  document.getElementById("runs-pick").value = run.season;
  let left = 1;
  const rows = run.ties.map((t, i) => {
    const from = left;
    const last = i === run.ties.length - 1;
    left = last ? run.probability : left * t.probability; // the stored product, unrounded, so every label agrees
    return `<li class="${last ? "f-end" : ""}" style="--from:${(from * 100).toFixed(2)}%;--to:${(left * 100).toFixed(2)}%;--d:${200 + i * 420}ms">
      <span class="f-label">${ROUND_SHORT[t.round]} v ${clean(t.opponent)} <em>× ${pct(t.probability)}</em></span>
      <span class="f-bar"><s></s><i></i></span><b>${left < 0.1 ? pct(left, 1) : pct(left)}</b></li>`;
  }).join("");
  document.getElementById("runs-path").innerHTML =
    `<p class="funnel-head"><b>${run.season}, ${clean(run.champion)}</b> had to win ${run.ties.length} ties in a row. Multiply the chances and watch the luck drain away:</p>
    <ol class="funnel${quiet ? " quiet" : ""}"><li style="--from:100%;--to:100%"><span class="f-label">Before the first tie</span><span class="f-bar"><s></s><i></i></span><b>100%</b></li>${rows}</ol>`;
}

// ---------- favourites by round ----------
function drawRounds(data) {
  const box = document.getElementById("rounds-chart");
  const rows = data.rounds;
  const { root, width, height } = canvas(box, 240);
  const m = { l: 40, r: 12, t: 12, b: 30 };
  const low = 0.3, high = 1;
  const y = (v) => m.t + (1 - (v - low) / (high - low)) * (height - m.t - m.b);
  const step = (width - m.l - m.r) / rows.length;
  for (let v = low; v <= high + 1e-9; v += 0.1) {
    svg("line", { x1: m.l, x2: width - m.r, y1: y(v), y2: y(v), stroke: css("--grid") }, root);
    svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = pct(v);
  }
  legend("rounds-legend", [["Favourite actually went through (likely range)", css("--s1")], ["Model expected", css("--muted")]]);
  rows.forEach((row, i) => {
    const cx = m.l + step * (i + 0.5);
    const lo = Math.max(low, row.won - row.error), hi = Math.min(high, row.won + row.error);
    svg("line", { x1: cx + 7, x2: cx + 7, y1: y(lo), y2: y(hi), stroke: css("--s1"), "stroke-width": 2, class: "grow-c", style: `--d:${300 + i * 110}ms` }, root);
    svg("circle", { cx: cx + 7, cy: y(row.won), r: 5, fill: css("--s1"), stroke: css("--surface"), "stroke-width": 2, class: "pop", style: `--d:${500 + i * 110}ms` }, root);
    svg("circle", { cx: cx - 7, cy: y(row.expected), r: 5, fill: "none", stroke: css("--muted"), "stroke-width": 2, class: "pop", style: `--d:${200 + i * 110}ms` }, root);
    svg("text", { x: cx, y: height - 8, "text-anchor": "middle" }, root).textContent = ROUND_SHORT[row.round];
    const hit = svg("rect", { x: cx - step / 2, y: m.t, width: step, height: height - m.t - m.b, class: "hit" }, root);
    hover(hit, `<b>${row.round}</b> (${row.ties} ties)<br>Model expected the favourite through: ${pct(row.expected)}<br>Actually went through: ${pct(row.won)}, give or take ${pct(row.error)}`);
  });
}

// ---------- skill vs luck: the better side over many ties ----------
// The chance of every number of wins for a side that wins each tie with chance p. Exact.
function winsDistribution(n, p) {
  let dist = [1];
  for (let i = 0; i < n; i++) dist = addTie(dist, p);
  return dist;
}
// Ahead (more wins than losses), level, or behind.
function standings(dist) {
  const n = dist.length - 1;
  const out = { ahead: 0, level: 0, behind: 0 };
  dist.forEach((q, k) => { out[2 * k > n ? "ahead" : 2 * k === n ? "level" : "behind"] += q; });
  return out;
}
// How many ties until the weaker side finishing ahead is rarer than 1 in 20, and stays that rare.
// (It isn't smooth: an even number of ties can finish level, which is not "behind".)
function tiesUntilSure(p, cap = 150) {
  let dist = [1], lastBad = 0;
  for (let n = 1; n <= cap; n++) {
    dist = addTie(dist, p);
    if (standings(dist).behind > 0.05) lastBad = n;
  }
  return lastBad < cap ? lastBad + 1 : null;
}

function setupSkill(data) {
  const edge = document.getElementById("sk-edge");
  const count = document.getElementById("sk-n");
  edge.value = Math.round(data.headline.favourite_expected * 100); // what a typical favourite really had
  const sure = {}; // tiesUntilSure for each edge, so dragging the other slider stays instant
  function draw() {
    const p = Number(edge.value) / 100, n = Number(count.value);
    document.getElementById("sk-edge-out").textContent = `${edge.value}%`;
    document.getElementById("sk-n-out").textContent = `${n} ${n === 1 ? "tie" : "ties"}`;
    const dist = winsDistribution(n, p);
    const { ahead, level, behind } = standings(dist);
    document.getElementById("sk-ahead").textContent = chance(ahead);
    document.getElementById("sk-level").textContent = chance(level);
    document.getElementById("sk-behind").textContent = chance(behind);

    const colour = (k) => (2 * k > n ? css("--s1") : 2 * k === n ? css("--s3") : css("--s2"));
    legend("sk-legend", [["Better side finishes ahead", css("--s1")], ...(n % 2 ? [] : [["Level", css("--s3")]]), ["Weaker side finishes ahead", css("--s2")]]);
    const box = document.getElementById("sk-chart");
    const { root, width, height } = canvas(box, 230);
    const m = { l: 44, r: 8, t: 12, b: 46 };
    const top = Math.ceil(Math.max(...dist) * 10) / 10;
    const y = (v) => m.t + (1 - v / top) * (height - m.t - m.b);
    for (let v = 0; v <= top + 1e-9; v += top > 0.5 ? 0.2 : 0.1) {
      svg("line", { x1: m.l, x2: width - m.r, y1: y(v), y2: y(v), stroke: css("--grid") }, root);
      svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = pct(v);
    }
    const step = (width - m.l - m.r) / (n + 1);
    const every = n <= 12 ? 1 : n <= 20 ? 2 : 5;
    dist.forEach((q, k) => {
      const cx = m.l + step * (k + 0.5), w = Math.min(step * 0.78, 38);
      svg("rect", { x: cx - w / 2, y: y(q), width: w, height: Math.max(0, height - m.b - y(q)), fill: colour(k) }, root);
      if (k % every === 0) svg("text", { x: cx, y: height - m.b + 16, "text-anchor": "middle" }, root).textContent = k;
      const hit = svg("rect", { x: cx - step / 2, y: m.t, width: step, height: height - m.t - m.b, class: "hit" }, root);
      hover(hit, `<b>${k} of ${n} won by the better side</b><br>${chance(q)} of the time<br>${2 * k > n ? "Better side finishes ahead" : 2 * k === n ? "Level" : "Weaker side finishes ahead"}`);
    });
    svg("text", { x: (m.l + width - m.r) / 2, y: height - 6, "text-anchor": "middle" }, root).textContent = "Ties won by the better side";

    sure[edge.value] ??= tiesUntilSure(p);
    const until = sure[edge.value];
    const needed = until ? `It takes about ${until} ties before the weaker side finishing ahead is rarer than 1 in 20.` : "It would take more than 150 ties before the weaker side finishing ahead is rarer than 1 in 20.";
    document.getElementById("sk-text").innerHTML = n === 1
      ? `In a single tie, even the better side goes out ${chance(1 - p)} of the time. That's the lottery. ${needed}`
      : `Winning <b>every</b> one of ${n} ties is much harder: ${chance(p ** n)}. ${needed}`;
    box.setAttribute("aria-label", `Chance of each number of wins for the better side over ${n} ${n === 1 ? "tie" : "ties"}: ahead ${chance(ahead)}, level ${chance(level)}, behind ${chance(behind)}`);
  }
  [edge, count].forEach((input) => input.addEventListener("input", draw));
  return draw;
}

// ---------- the wildest seasons ----------
// Per season: how many underdogs went through (an underdog is the side with the lower pre-match
// chance), how many the model expected, and who they were.
function seasonUpsets(ties) {
  const seasons = new Map();
  for (const t of ties) {
    const row = seasons.get(t.season) ?? { season: t.season, ties: 0, expected: 0, variance: 0, upsets: [] };
    const favourite = Math.max(t.p_a, 1 - t.p_a);
    const chanceOfWinner = t.winner === t.team_a ? t.p_a : 1 - t.p_a;
    row.ties++;
    row.expected += 1 - favourite;
    row.variance += favourite * (1 - favourite);
    if (chanceOfWinner < 0.5) row.upsets.push({ club: t.winner, over: t.winner === t.team_a ? t.team_b : t.team_a, chance: chanceOfWinner });
    seasons.set(t.season, row);
  }
  return [...seasons.values()].map((r) => ({ ...r, actual: r.upsets.length, z: (r.upsets.length - r.expected) / Math.sqrt(r.variance) }));
}

function drawWild(data) {
  const box = document.getElementById("wild-chart");
  const rows = seasonUpsets(data.ties).sort((a, b) => (b.actual - b.expected) - (a.actual - a.expected));
  const rowH = 30;
  const { root, width, height } = canvas(box, rows.length * rowH + 40);
  const m = { l: 64, r: 48, t: 8, b: 30 };
  const max = Math.ceil(Math.max(...rows.map((r) => Math.max(r.actual, r.expected))));
  const x = (v) => m.l + (v / max) * (width - m.l - m.r);
  for (let v = 0; v <= max; v++) {
    svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: height - m.b, stroke: css("--grid") }, root);
    svg("text", { x: x(v), y: height - 10, "text-anchor": "middle" }, root).textContent = v;
  }
  svg("text", { x: m.l - 10, y: height - 10, "text-anchor": "end" }, root).textContent = "Underdogs";
  legend("wild-legend", [["Underdogs that went through", css("--s1")], ["Wildest season", css("--s2")], ["Model expected", css("--muted")]]);
  rows.forEach((row, i) => {
    const cy = m.t + rowH * (i + 0.5);
    const colour = i === 0 ? css("--s2") : css("--s1");
    const gap = row.actual - row.expected;
    svg("text", { x: m.l - 10, y: cy + 4, "text-anchor": "end", class: i === 0 ? "label-strong" : "" }, root).textContent = row.season;
    svg("line", { x1: x(row.expected), x2: x(row.actual), y1: cy, y2: cy, stroke: colour, "stroke-width": 2, pathLength: 1, class: "draw", style: `--d:${400 + i * 45}ms` }, root);
    svg("circle", { cx: x(row.expected), cy, r: 5, fill: css("--surface"), stroke: css("--muted"), "stroke-width": 2, class: "pop", style: `--d:${200 + i * 45}ms` }, root);
    svg("circle", { cx: x(row.actual), cy, r: 5, fill: colour, stroke: css("--surface"), "stroke-width": 2, class: "pop", style: `--d:${600 + i * 45}ms` }, root);
    svg("text", { x: width - 2, y: cy + 4, "text-anchor": "end" }, root).textContent = `${gap > 0 ? "+" : gap < 0 ? "−" : ""}${Math.abs(gap).toFixed(1)}`;
    const hit = svg("rect", { x: 0, y: cy - rowH / 2, width, height: rowH, class: "hit" }, root);
    const upsets = row.upsets.sort((a, b) => a.chance - b.chance);
    const names = upsets.slice(0, 7).map((u) => `${clean(u.club)} over ${clean(u.over)} (${chance(u.chance)})`).join("<br>");
    hover(hit, `<b>${row.season}</b><br>${row.actual} underdog${row.actual === 1 ? "" : "s"} went through; the model expected ${row.expected.toFixed(1)}<br>${names}${upsets.length > 7 ? `<br>and ${upsets.length - 7} more` : ""}<br><i>Click to see this season's ties</i>`,
      () => filterTies({ season: row.season }, true));
  });
  const wild = rows[0], calm = rows[rows.length - 1];
  const sizes = rows.map((r) => r.ties), few = Math.min(...sizes), many = Math.max(...sizes);
  const odd = rows.filter((r) => Math.abs(r.z) >= 2).map((r) => r.season);
  document.getElementById("wild-note").textContent =
    `${wild.season} was the wildest: ${wild.actual} underdogs went through against ${wild.expected.toFixed(1)} expected. ${calm.season} was the calmest: ${calm.actual} against ${calm.expected.toFixed(1)}. `
    + (odd.length
      ? `${odd.join(" and ")} ${odd.length === 1 ? "is" : "are"} further from the model than luck usually allows.`
      : `With only ${few === many ? few : `${few} to ${many}`} ties a season, swings like this are normal: none of them is far enough from what the model expected to call it anything but luck.`);
}

// ---------- clubs: expected vs actual ----------
function drawClubs(data) {
  const box = document.getElementById("clubs-chart");
  const clubs = data.clubs;
  const rowH = 26;
  const narrow = box.clientWidth < 560;
  const { root, width, height } = canvas(box, clubs.length * rowH + 40);
  const m = { l: narrow ? 108 : 150, r: 16, t: 8, b: 30 };
  const max = Math.ceil(Math.max(...clubs.map((c) => Math.max(c.won, c.expected))) / 10) * 10;
  const x = (v) => m.l + (v / max) * (width - m.l - m.r);
  for (let v = 0; v <= max; v += 10) {
    svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: height - m.b, stroke: css("--grid") }, root);
    svg("text", { x: x(v), y: height - 10, "text-anchor": "middle" }, root).textContent = v;
  }
  svg("text", { x: m.l - 10, y: height - 10, "text-anchor": "end" }, root).textContent = "Ties won";
  legend("clubs-legend", [["Ties won", css("--s1")], ["Real Madrid", css("--s2")], ["Model expected", css("--muted")]]);
  clubs.forEach((club, i) => {
    const cy = m.t + rowH * (i + 0.5);
    const real = club.club === "Real Madrid";
    const color = real ? css("--s2") : css("--s1");
    svg("text", { x: m.l - 10, y: cy + 4, "text-anchor": "end", class: real ? "label-strong" : "" }, root).textContent = narrow && clean(club.club).length > 14 ? shortClub(club.club) : clean(club.club);
    svg("line", { x1: x(club.expected), x2: x(club.won), y1: cy, y2: cy, stroke: color, "stroke-width": 2, pathLength: 1, class: "draw", style: `--d:${400 + i * 45}ms` }, root);
    svg("circle", { cx: x(club.expected), cy, r: 5, fill: css("--surface"), stroke: css("--muted"), "stroke-width": 2, class: "pop", style: `--d:${200 + i * 45}ms` }, root);
    svg("circle", { cx: x(club.won), cy, r: 5, fill: color, stroke: css("--surface"), "stroke-width": 2, class: "pop", style: `--d:${real ? 1500 : 900 + i * 45}ms` }, root);
    const hit = svg("rect", { x: 0, y: cy - rowH / 2, width, height: rowH, class: "hit" }, root);
    hover(hit, `<b>${clean(club.club)}</b><br>Won ${club.won} of ${club.ties} ties<br>Model expected ${club.expected.toFixed(1)}`);
  });
}

// ---------- Real Madrid: where the extra wins came from, and did it last? ----------
// The numbers come from src/real_madrid.py (data.real_madrid). If that analysis is missing or out
// of date the whole block stays hidden and the page keeps its shorter explanation.
const oneIn = (p) => `1 in ${Number((1 / p).toPrecision(2)).toLocaleString("en-GB")}`;
const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][n % 100 >= 11 && n % 100 <= 13 ? 0 : n % 10 < 4 ? n % 10 : 0]}`;
const signed = (v, digits = 1) => {
  const size = Math.abs(v).toFixed(digits);
  return Number(size) === 0 ? size : `${v < 0 ? "−" : "+"}${size}`; // zero has no sign
};

function drawRmSplit(data) {
  const rm = data.real_madrid;
  if (!rm) return;
  const n = rm.normal_time;
  const rows = [
    ["Won, normal time", n.won_normal, `Won ${n.won_normal.actual} ties in normal time; the model expected ${n.won_normal.expected.toFixed(1)} (${oneIn(n.won_normal.p_at_least)} by luck)`],
    ["Lost, normal time", n.lost_normal, `Lost ${n.lost_normal.actual} ties in normal time; the model expected ${n.lost_normal.expected.toFixed(1)} (${oneIn(n.lost_normal.p_at_most)} by luck)`],
    ["Went to extra time", n.extra_time, `${n.extra_time.actual} ties went to extra time; the model expected ${n.extra_time.expected.toFixed(1)}`],
    ["Won in extra time", n.won_extra, `Won ${n.won_extra.actual} of those ${n.extra_time.actual}; the model expected ${n.won_extra.expected.toFixed(1)} (${oneIn(n.won_extra.p_at_least)} by luck)`],
  ];
  const box = document.getElementById("rm-split");
  const rowH = 38;
  const { root, width, height } = canvas(box, rows.length * rowH + 40);
  const m = { l: 150, r: 14, t: 8, b: 30 }; // room for the longest label, "Went to extra time"
  const max = Math.ceil(Math.max(...rows.map(([, r]) => Math.max(r.actual, r.expected))) / 5) * 5;
  const x = (v) => m.l + (v / max) * (width - m.l - m.r);
  for (let v = 0; v <= max; v += 5) {
    svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: height - m.b, stroke: css("--grid") }, root);
    svg("text", { x: x(v), y: height - 10, "text-anchor": "middle" }, root).textContent = v;
  }
  svg("text", { x: m.l - 10, y: height - 10, "text-anchor": "end" }, root).textContent = "Ties";
  legend("rm-split-legend", [["What happened", css("--s2")], ["Model expected", css("--muted")]]);
  rows.forEach(([label, r, tip], i) => {
    const cy = m.t + rowH * (i + 0.5);
    svg("text", { x: m.l - 10, y: cy + 4, "text-anchor": "end", class: "label-strong" }, root).textContent = label;
    svg("line", { x1: x(r.expected), x2: x(r.actual), y1: cy, y2: cy, stroke: css("--s2"), "stroke-width": 2 }, root);
    svg("circle", { cx: x(r.expected), cy, r: 5, fill: css("--surface"), stroke: css("--muted"), "stroke-width": 2 }, root);
    svg("circle", { cx: x(r.actual), cy, r: 5, fill: css("--s2"), stroke: css("--surface"), "stroke-width": 2 }, root);
    hover(svg("rect", { x: 0, y: cy - rowH / 2, width, height: rowH, class: "hit" }, root), tip);
  });
}

// One dot per club: how far it was from the model's expectation in the first seven seasons (across)
// and the last seven (up). Distances are in units of normal luck: 0 is exactly as expected and
// beyond 2 is more than luck usually allows.
function drawRmLast(data) {
  const rm = data.real_madrid;
  if (!rm) return;
  const box = document.getElementById("rm-last");
  const side = Math.max(box.clientWidth, 280);
  const { root, width, height } = canvas(box, Math.round(Math.min(380, Math.max(270, side * 0.85))));
  const m = { l: 34, r: 12, t: 10, b: 40 };
  const lim = 3.2;
  const x = (v) => m.l + ((v + lim) / (2 * lim)) * (width - m.l - m.r);
  const y = (v) => m.t + (1 - (v + lim) / (2 * lim)) * (height - m.t - m.b);
  [-2, 0, 2].forEach((v) => {
    const mid = v === 0;
    svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: height - m.b, stroke: mid ? css("--axis") : css("--grid") }, root);
    svg("line", { x1: m.l, x2: width - m.r, y1: y(v), y2: y(v), stroke: mid ? css("--axis") : css("--grid") }, root);
    svg("text", { x: x(v), y: height - m.b + 15, "text-anchor": "middle" }, root).textContent = signed(v, 0);
    svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = signed(v, 0);
  });
  svg("text", { x: (m.l + width - m.r) / 2, y: height - 6, "text-anchor": "middle" }, root).textContent = "First seven seasons →";
  svg("text", { x: 11, y: (m.t + height - m.b) / 2, "text-anchor": "middle", transform: `rotate(-90 11 ${(m.t + height - m.b) / 2})` }, root).textContent = "Last seven seasons →";
  const ordered = [...rm.clubs].sort((a, b) => (a.club === rm.club) - (b.club === rm.club)); // Real Madrid drawn last, on top
  ordered.forEach((c) => {
    const real = c.club === rm.club;
    svg("circle", { cx: x(c.first), cy: y(c.second), r: real ? 7 : 4.5, fill: real ? css("--s2") : css("--s1"),
      "fill-opacity": real ? 1 : 0.55, stroke: css("--surface"), "stroke-width": 1.5 }, root);
    if (real) svg("text", { x: x(c.first) - 11, y: y(c.second) + 4, "text-anchor": "end", class: "label-strong" }, root).textContent = clean(c.club);
    hover(svg("circle", { cx: x(c.first), cy: y(c.second), r: 11, class: "hit" }, root),
      `<b>${clean(c.club)}</b><br>First seven seasons (${c.ties_first} ties): ${signed(c.first)}<br>Last seven (${c.ties_second} ties): ${signed(c.second)}<br><span style="opacity:.6">0 is exactly what the model expected</span>`);
  });
}

// The last paragraphs of the verdict. With the line-up check (src/real_madrid_squad.py) they say what
// it found; without it, why the model can't tell the explanations apart.
function squadParagraphs(rm, { liga, groups, knockouts, separate }) {
  const climb = `The gap does grow with the stakes, from ${signed(liga.gap, 2)} points a match in La Liga to ${signed(groups.gap, 2)} in the Champions League groups and ${signed(knockouts.gap, 2)} in the knockouts. ${separate ? "That climb is bigger than luck would explain." : "But those three each have wide error bars that overlap, so I wouldn't lean on that."}`;
  const sq = rm.squad;
  if (!sq) {
    return `
    <p><b>What I can't tell you is why.</b> There are no line-ups, injuries or bookmaker odds for these matches, so the model can't separate "Real Madrid lift their level in Europe" from "they rotate in La Liga" or "their best eleven is stronger than their league record shows". ${climb}</p>`;
  }
  const rot = sq.rotation, ko = sq.strength.real.knockouts, mg = sq.managers;
  const explained = ko.explained_by_fielded + ko.explained_by_quality;
  return `
    <p><b>It isn't the line-ups either.</b> Transfermarkt's starting elevens and market values test the obvious explanations. <i>Rotation:</i> Real do field a fuller eleven in the knockouts than in La Liga (${pct(rot.real.knockouts)} of their best eleven's value against ${pct(rot.real.league)}), but every big club does: the other ${rot.others.clubs} average ${signed(rot.others.gap, 3)} against Real's ${signed(rot.real.gap, 3)}, and Real are ${ordinal(rot.real_rank)} of ${rot.clubs}. <i>Strength:</i> between the eleven Real fielded and the gap in squad quality with their opponents, only ${signed(explained, 2)} of the ${signed(ko.actual, 2)} goals a match they beat the model by in knockouts is accounted for. <i>The manager:</i> Real beat the model under Ancelotti (${signed(mg.ancelotti_at_real.points, 2)} points a match) and under Zidane (${signed(mg.zidane_at_real.points, 2)}), but Ancelotti's ${mg.ancelotti_elsewhere.matches} matches elsewhere (${signed(mg.ancelotti_elsewhere.points, 2)}) are too few to tell a coach from a club.</p>
    <p><b>What I still can't tell you is why.</b> It isn't rotation, a stronger eleven or (clearly) the manager, so what's left is something neither results nor line-ups can see (how Real manage a tie, experience in these games, or something about the club itself, to give three possibilities). Bookmaker odds for these matches would be the next test, since they'd show whether the market also rated Real above the model. ${climb}</p>`;
}

function fillRealMadrid(data) {
  const rm = data.real_madrid;
  document.getElementById("rm").hidden = !rm;
  if (!rm) return;
  document.getElementById("rm-lead").textContent = "So is it luck, or something the model can't see? Two checks follow, then what I make of them.";
  const others = rm.clubs.filter((c) => c.club !== rm.club);
  const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
  const [mx, my] = [mean(others.map((c) => c.first)), mean(others.map((c) => c.second))];
  const corr = others.reduce((s, c) => s + (c.first - mx) * (c.second - my), 0)
    / Math.sqrt(others.reduce((s, c) => s + (c.first - mx) ** 2, 0) * others.reduce((s, c) => s + (c.second - my) ** 2, 0));
  document.getElementById("rm-last-note").textContent =
    `Distances are in luck-units: 0 is exactly what the model expected, and beyond 2 is more than luck usually allows. The other ${others.length} clubs scatter around the middle, and a good first half told you nothing about the second (the two correlate at ${signed(corr, 2)}). Real Madrid are top right: ahead of the model in both halves.`;

  const [h1, h2] = rm.halves, f = rm.forecast, n = rm.normal_time;
  const stage = Object.fromEntries(rm.stages.map((s) => [s.label, s]));
  const liga = stage["La Liga"], groups = stage["Champions League groups"], knockouts = stage["Champions League knockouts"];
  const [barca, atleti] = [rm.spanish["Barcelona"], rm.spanish["Ath Madrid"]];
  const separate = knockouts.gap - knockouts.error > liga.gap + liga.error;
  document.getElementById("rm-verdict").innerHTML = `
    <p><b>The short answer: mostly not luck, though a bit of it is.</b> The model only sees league results and Champions League scores, and it keeps underrating Real Madrid in Europe.</p>
    <p><b>It doesn't look like a lucky streak.</b> Split the ${rm.seasons} seasons in half and Real Madrid beat the model by about the same amount in both: ${h1.won} of ${h1.ties} ties won when ${h1.expected.toFixed(1)} were expected, then ${h2.won} of ${h2.ties} when ${h2.expected.toFixed(1)} were. They were ahead of it in ${rm.seasons_above} of ${rm.seasons} seasons. A boost worked out from the first seven seasons alone would have forecast the next seven clearly better (error per tie ${f.without.toFixed(2)} down to ${f.with.toFixed(2)}). Ordinary clubs don't show that: no other club is further than ${rm.others.largest_z.toFixed(1)} luck-units from the model.</p>
    <p><b>It isn't a Spanish thing.</b> Barcelona won ${barca.won} of ${barca.ties} ties when ${barca.expected.toFixed(1)} were expected, and Atlético Madrid ${atleti.won} of ${atleti.ties} when ${atleti.expected.toFixed(1)} were. Real Madrid's own La Liga results are close to the model's too: ${liga.points.toFixed(2)} points a match against ${liga.expected.toFixed(2)} expected.</p>
    <p><b>Part of it is probably luck.</b> ${n.extra_time.actual} of Real's ties went to extra time or penalties, which are close to coin flips, and they won all ${n.won_extra.actual} (about ${n.won_extra.expected.toFixed(1)} expected). That run is the likeliest piece of pure luck. But they also lost only ${n.lost_normal.actual} ties in normal time when the model expected ${n.lost_normal.expected.toFixed(0)}, and that part isn't a coin flip.</p>
${squadParagraphs(rm, { liga, groups, knockouts, separate })}`;
}

// ---------- calibration ----------
// Two views of the same bins. "Full" is the classic diagonal chart and the one that answers the
// heading's question (lines hugging the diagonal mean the chances were honest), so it comes first.
// "Gap" plots how far each model was from honest, which is where the small differences between
// models are visible.
let calView = "full";
function drawCalibration(data) {
  const box = document.getElementById("cal-chart");
  const gapView = calView === "gap";
  const across = Math.max(box.clientWidth, 280);
  const { root, width, height } = canvas(box, gapView ? Math.round(Math.min(across * 0.72, 360)) : Math.min(across, 460));
  const m = { l: 52, r: gapView ? 58 : 14, t: 14, b: 42 }; // room on the right for the "Honest" label
  const colors = { "Dixon–Coles": css("--s1"), "Elo": css("--s3"), "Bookmakers": css("--s2") };
  const dashed = { "Elo": "5 3" }; // so Elo never reads as the reference line
  const x = (v) => m.l + v * (width - m.l - m.r);
  const all = data.calibration.flatMap((s) => s.points);
  const span = gapView ? Math.min(0.2, Math.ceil(Math.max(...all.map((p) => Math.abs(p.actual - p.predicted) + p.error)) * 20) / 20) : 1;
  const value = (p) => (gapView ? p.actual - p.predicted : p.actual);
  const y = gapView ? (v) => m.t + (0.5 - v / (2 * span)) * (height - m.t - m.b) : (v) => m.t + (1 - v) * (height - m.t - m.b);
  const clamp = (v) => (gapView ? Math.max(-span, Math.min(span, v)) : Math.max(0, Math.min(1, v)));

  for (let v = 0; v <= 1.0001; v += 0.2) {
    svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: height - m.b, stroke: css("--grid") }, root);
    svg("text", { x: x(v), y: height - m.b + 16, "text-anchor": "middle" }, root).textContent = pct(v);
  }
  const step = gapView ? 0.05 : 0.2;
  for (let v = gapView ? -span : 0; v <= (gapView ? span : 1) + 1e-9; v += step) {
    svg("line", { x1: x(0), x2: x(1), y1: y(v), y2: y(v), stroke: css("--grid") }, root);
    const label = gapView ? (Math.abs(v) < 1e-9 ? "0" : `${v > 0 ? "+" : "−"}${Math.round(Math.abs(v) * 100)}`) : pct(v);
    svg("text", { x: x(0) - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = label;
  }
  svg("text", { x: x(0.5), y: height - 4, "text-anchor": "middle" }, root).textContent = "Predicted chance of a home win";
  const mid = m.t + (height - m.t - m.b) / 2;
  svg("text", { x: 12, y: mid, "text-anchor": "middle", transform: `rotate(-90 12 ${mid})` }, root).textContent =
    gapView ? "How far off (percentage points)" : "How often the home team actually won";

  if (gapView) {
    svg("line", { x1: x(0), x2: x(1), y1: y(0), y2: y(0), stroke: css("--ink-2"), "stroke-width": 1.5 }, root);
    svg("text", { x: x(1) + 6, y: y(0) + 4, class: "label-strong" }, root).textContent = "Honest";
    // The long wording needs about 280px; narrow screens get the short one.
    const roomy = x(1) - x(0) - 16 > 42 * 6.7;
    svg("text", { x: x(0) + 8, y: m.t + 14 }, root).textContent = roomy ? "↑ Home side won more often than predicted" : "↑ Won more than predicted";
    svg("text", { x: x(0) + 8, y: height - m.b - 8 }, root).textContent = roomy ? "↓ Home side won less often than predicted" : "↓ Won less than predicted";
  } else {
    svg("line", { x1: x(0), y1: y(0), x2: x(1), y2: y(1), stroke: css("--ink-2"), "stroke-width": 1.5, "stroke-dasharray": "2 4" }, root);
    // Up and to the left of the diagonal is empty: the lines hug it, so a label there covers nothing.
    const roomy = x(0.5) - x(0) > 16 * 6.7 + 8;
    svg("text", { x: x(0.5), y: y(0.62) + 4, "text-anchor": "end", class: "label-strong" }, root).textContent = roomy ? "Perfectly honest ↘" : "Honest ↘";
  }
  legend("cal-legend", data.calibration.map((s) => [MODEL_NAMES[s.name] || s.name, colors[s.name], dashed[s.name] ? "line dash" : "line"]));

  data.calibration.forEach((series, k) => {
    const color = colors[series.name];
    const nudge = (k - 1) * 3; // keep error bars from sitting on top of each other
    svg("polyline", {
      points: series.points.map((p) => `${x(p.predicted) + nudge},${y(clamp(value(p)))}`).join(" "),
      fill: "none", stroke: color, "stroke-width": 2, "stroke-dasharray": dashed[series.name] || "none",
    }, root);
    series.points.forEach((p, j) => {
      const px = x(p.predicted) + nudge, v = value(p);
      svg("line", { x1: px, x2: px, y1: y(clamp(v + p.error)), y2: y(clamp(v - p.error)), stroke: color, "stroke-width": 1.5, opacity: 0.7, class: "fade", style: `--d:${k * 280 + j * 90}ms` }, root);
      svg("circle", { cx: px, cy: y(clamp(v)), r: 4, fill: dashed[series.name] ? css("--surface") : color, stroke: color, "stroke-width": 2, class: "pop", style: `--d:${k * 280 + j * 90}ms` }, root);
      const hit = svg("circle", { cx: px, cy: y(clamp(v)), r: 12, class: "hit" }, root);
      const gap = Math.round((p.actual - p.predicted) * 1000) / 10;
      hover(hit, `<b>${MODEL_NAMES[series.name] || series.name}</b><br>Said ${pct(p.predicted)} on average<br>Home team won ${pct(p.actual)}, give or take ${pct(p.error)}<br>` +
        `${gap === 0 ? "Exactly honest" : `${Math.abs(gap)} points ${gap > 0 ? "more" : "less"} often than predicted`}<br>${p.n.toLocaleString("en-GB")} matches`);
    });
  });

  // The takeaway in words: each model's average miss, weighted by matches.
  const misses = data.calibration.map((s) => {
    const n = s.points.reduce((t, p) => t + p.n, 0);
    return { name: s.name, miss: s.points.reduce((t, p) => t + p.n * Math.abs(p.actual - p.predicted), 0) / n };
  }).sort((a, b) => a.miss - b.miss);
  document.getElementById("cal-note").innerHTML = `On average, the home side's real win rate was off from the prediction by ` +
    misses.map((s) => `<b>${(s.miss * 100).toFixed(1)} points</b> for ${s.name === "Bookmakers" ? "the bookmakers" : (MODEL_NAMES[s.name] || s.name).toLowerCase()}`)
      .join(", ").replace(/, ([^,]*)$/, " and $1") +
    `. Gaps that small mean all three are honest. Near 0% and 100% there are few matches, so the lines showing the likely range get long.` +
    (gapView ? ` This view is the same points with the honest line laid flat at 0, so that small gaps show.` : "");
}

function setupCalibration(data) {
  const buttons = document.querySelectorAll(".cal-view button");
  buttons.forEach((button) => button.addEventListener("click", () => {
    calView = button.dataset.view;
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    drawCalibration(data);
  }));
}

function fillScores(data) {
  const best = Math.min(...data.scores.map((s) => s.brier));
  const name = (model) => MODEL_NAMES[model] || model;
  document.querySelector("#scores-table tbody").innerHTML = data.scores.map((s) =>
    `<tr class="${s.brier === best ? "best" : ""}"><td>${name(s.model)}</td><td class="num">${s.brier.toFixed(4)}</td><td class="num">${s.log_loss.toFixed(4)}</td></tr>`).join("");
  // The same scores as a share of the distance from knowing nothing to the bookmakers.
  const floor = data.scores.find((s) => s.model === "Base rates"), book = data.scores.find((s) => s.brier === best);
  document.getElementById("gap-closed").innerHTML = data.scores.filter((s) => s !== floor).map((s) => {
    const share = (floor.brier - s.brier) / (floor.brier - book.brier);
    return `<div class="meter-row${s === book ? " book" : ""}"><div class="meter-head"><span>${name(s.model)}</span><b>${pct(share)}</b></div>` +
      `<div class="meter" role="img" aria-label="${name(s.model)}: ${pct(share)} of the way"><span style="width:${pct(share, 1)}"></span></div></div>`;
  }).join("");
}

// ---------- scores ----------
// What happened in a tie, from data.json's `legs` (team_a's goals first, extra time included).
// `first` is the club whose goals are written first.
function scoreParts(t, first) {
  const turn = (pair) => (first === t.team_a ? pair : [pair[1], pair[0]]);
  const legs = t.legs.map(turn);
  const last = legs.length - 1;
  return {
    legs: legs.map((pair, i) => `${pair[0]}–${pair[1]}${i === last && t.aet ? " a.e.t." : ""}`),
    aggregate: legs.length === 2 ? `${legs[0][0] + legs[1][0]}–${legs[0][1] + legs[1][1]}` : null,
    decider: t.pens ? `${turn(t.pens).join("–")} on penalties` : t.away ? "away goals" : null,
  };
}
// For the tie list: "1st leg 1–1 · 2nd leg 3–1 a.e.t. · 4–2 on aggregate", read in the order of the names.
function scoreLine(t) {
  const { legs, aggregate, decider } = scoreParts(t, t.team_a);
  const parts = legs.length === 1 ? [`Match ${legs[0]}`] : legs.map((leg, i) => `${i ? "2nd" : "1st"} leg ${leg}`);
  if (aggregate) parts.push(`${aggregate} on aggregate`);
  if (decider) parts.push(decider);
  return parts.join(" · ");
}
// For tooltips, which say who beat whom: the winner's goals come first.
function scoreTip(t) {
  const { legs, aggregate, decider } = scoreParts(t, t.winner);
  return legs.join(", ") + (aggregate ? ` (${aggregate} on aggregate)` : "") + (decider ? `, ${decider}` : "");
}

// What the tie explorer's filters let through. The list and the season strip both use it, so
// they always agree. Two clubs (Club and Against) mean one on each side of the tie; one box
// filled means that club on either side. `withSeason: false` for the strip, where the season
// is the zoom rather than a filter.
function tieFilter(withSeason = true) {
  const text = (id) => document.getElementById(id).value.trim().toLowerCase();
  const season = withSeason ? document.getElementById("f-season").value : "";
  const round = document.getElementById("f-round").value;
  const upsetsOnly = document.getElementById("f-upsets").checked;
  const club = text("f-club"), against = text("f-against");
  const named = called;
  return (t) => {
    if (season && t.season !== season) return false;
    if (round && t.round !== round) return false;
    if (upsetsOnly && winnerChance(t) >= 0.35) return false;
    if (club && against) return (named(t.team_a, club) && named(t.team_b, against)) || (named(t.team_b, club) && named(t.team_a, against));
    const q = club || against;
    return !q || named(t.team_a, q) || named(t.team_b, q);
  };
}

// "Real Madrid v Man City: 7 ties. ..." for the ties currently listed, but only when each box
// names one club (typing just "real" could mean several, and a summary of that would mislead).
function headToHead(rows, club, against) {
  const clubsMatching = (q) => [...new Set(rows.flatMap((t) => [t.team_a, t.team_b]).filter((name) => called(name, q)))];
  const [a, b] = [clubsMatching(club), clubsMatching(against)];
  if (!rows.length || a.length !== 1 || b.length !== 1 || a[0] === b[0]) return "";
  const [one, two] = [a[0], b[0]];
  const wins = (name) => rows.filter((t) => t.winner === name).length;
  const expected = rows.reduce((sum, t) => sum + (t.team_a === one ? t.p_a : 1 - t.p_a), 0);
  const times = (k) => (k === 1 ? "once" : k === 0 ? "never" : `${k} times`);
  return `<b>${clean(one)} v ${clean(two)}: ${rows.length} tie${rows.length === 1 ? "" : "s"}.</b> ${clean(one)} went through ${times(wins(one))}, ${clean(two)} ${times(wins(two))}. `
    + (rows.length === 1 ? `Before the tie, the model gave ${clean(one)} a ${pct(expected)} chance.`
      : `Before each tie, the model expected ${clean(one)} to go through ${expected.toFixed(1)} times.`);
}

// ---------- tie explorer ----------
function setupTies(data) {
  const seasons = [...new Set(data.ties.map((t) => t.season))].sort().reverse();
  const rounds = ["Playoffs", "Round of 16", "Quarterfinals", "Semifinals", "Final"].filter((r) => data.ties.some((t) => t.round === r));
  const seasonSelect = document.getElementById("f-season");
  const roundSelect = document.getElementById("f-round");
  seasonSelect.innerHTML = `<option value="">All seasons</option>` + seasons.map((s) => `<option>${s}</option>`).join("");
  roundSelect.innerHTML = `<option value="">All rounds</option>` + rounds.map((r) => `<option value="${r}">${ROUND_SHORT[r]}</option>`).join("");
  const club = document.getElementById("f-club");
  const against = document.getElementById("f-against");
  const upsets = document.getElementById("f-upsets");
  const order = Object.fromEntries(rounds.map((r, i) => [r, i]));
  const more = document.getElementById("ties-more");
  const PAGE = 30;
  let shown = PAGE;
  more.addEventListener("click", () => { shown += PAGE; render(true); });

  // Suggestions while typing a club, and the pairings that have met most often, one click each.
  const names = [...new Set(data.ties.flatMap((t) => [clean(t.team_a), clean(t.team_b)]))].sort((x, y) => x.localeCompare(y));
  document.getElementById("club-names").replaceChildren(...names.map((name) => Object.assign(document.createElement("option"), { value: name })));
  const meetings = new Map();
  for (const t of data.ties) {
    const pair = [clean(t.team_a), clean(t.team_b)].sort().join("\n");
    meetings.set(pair, (meetings.get(pair) ?? 0) + 1);
  }
  const common = [...meetings].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0])).slice(0, 4);
  const tryBox = document.getElementById("h2h-try");
  tryBox.append(Object.assign(document.createElement("span"), { textContent: "Try" }), ...common.map(([pair, n]) => {
    const [one, two] = pair.split("\n");
    const chip = Object.assign(document.createElement("button"), { type: "button", className: "chip", textContent: `${one} v ${two} ` });
    chip.append(Object.assign(document.createElement("em"), { textContent: `${n} ties` }));
    chip.addEventListener("click", () => filterTies({ club: one, against: two, season: "", round: "", upsets: false }));
    return chip;
  }));

  function render(keepCount) {
    if (keepCount !== true) shown = PAGE;
    const rows = data.ties.filter(tieFilter()).sort((a, b) => b.season.localeCompare(a.season) || order[b.round] - order[a.round]);
    const summary = club.value.trim() && against.value.trim() ? headToHead(rows, club.value.trim().toLowerCase(), against.value.trim().toLowerCase()) : "";
    const note = document.getElementById("h2h");
    note.hidden = !summary;
    note.innerHTML = summary;
    document.getElementById("ties-count").textContent = `${rows.length} tie${rows.length === 1 ? "" : "s"}`;
    more.hidden = rows.length <= shown;
    more.textContent = `Show more ties (${rows.length - shown} left)`;
    document.getElementById("ties-list").innerHTML = rows.slice(0, shown).map((t) => {
      const pWinner = t.winner === t.team_a ? t.p_a : 1 - t.p_a;
      const upset = pWinner < 0.35 ? `<span class="badge">upset</span>` : "";
      const a = Math.round(t.p_a * 100);
      return `<div class="tie">
        <div class="tie-meta">${t.season}<br>${ROUND_SHORT[t.round]}${upset}</div>
        <div class="team-a ${t.winner === t.team_a ? "through" : ""}">${clean(t.team_a)}</div>
        <div class="split-bar" role="img" aria-label="${clean(t.team_a)} ${a}%, ${clean(t.team_b)} ${100 - a}%">
          <span class="a" style="flex:${Math.max(a, 1)}">${a >= 12 ? a + "%" : ""}</span>
          <span class="b" style="flex:${Math.max(100 - a, 1)}">${100 - a >= 12 ? 100 - a + "%" : ""}</span>
        </div>
        <div class="team-b ${t.winner === t.team_b ? "through" : ""}">${clean(t.team_b)}</div>
        <div class="tie-score">${scoreLine(t)}</div>
      </div>`;
    }).join("") || `<p class="small">No ties match these filters.</p>`;
  }
  [seasonSelect, roundSelect, upsets].forEach((n) => n.addEventListener("change", () => render()));
  [club, against].forEach((n) => n.addEventListener("input", () => render()));
  render();
}

// ---------- butterfly effect: what if one result changed? ----------
const ROUND_TITLES = { "Round of 16": "Last 16", "Quarterfinals": "Quarter-finals", "Semifinals": "Semi-finals", "Final": "Final" };

function setupButterfly(data) {
  const select = document.getElementById("bf-season");
  const brackets = [...data.brackets].reverse();
  select.innerHTML = brackets.map((b, i) => `<option value="${i}">${b.season}</option>`).join("");
  let bracket, locks, baseline, parent, index, ready = false;

  // The season and picks live in the address (?season=2021-22&picks=3.5-9.2#butterfly: node id
  // and team number), so a set of picks can be sent to someone and opens exactly as it was.
  function writeUrl() {
    const params = new URLSearchParams(location.search);
    const picks = bracket.nodes.filter((n) => locks[n.id]).map((n) => `${n.id}.${index[locks[n.id]]}`).join("-");
    if (picks || select.value !== "0") params.set("season", bracket.season); else params.delete("season");
    if (picks) params.set("picks", picks); else params.delete("picks");
    const query = params.toString();
    history.replaceState(null, "", location.pathname + (query ? `?${query}` : "") + location.hash);
  }

  function readUrl() {
    const params = new URLSearchParams(location.search);
    const i = brackets.findIndex((b) => b.season === params.get("season"));
    if (i < 0) return;
    select.value = String(i);
    load(i);
    // Applied in round order, and only where the club can really be in that tie, so a
    // mangled or hand-edited link gives the valid part of the picks rather than nonsense.
    const wanted = Object.fromEntries((params.get("picks") || "").split("-").map((p) => p.split(".").map(Number)));
    for (const node of bracket.nodes) {
      const team = bracket.teams[wanted[node.id]];
      const both = sides(node);
      if (team && both && both.includes(team)) locks[node.id] = team;
    }
    render();
  }

  function load(i) {
    bracket = brackets[i];
    locks = {};
    index = Object.fromEntries(bracket.teams.map((t, k) => [t, k]));
    parent = {};
    bracket.nodes.forEach((n) => (n.from || []).forEach((child) => { parent[child] = n.id; }));
    baseline = titleChances();
    document.getElementById("bf-note").textContent = bracket.fixed_bracket
      ? "This season's bracket was fixed before the round of 16."
      : "Before 2024-25, each later round was drawn after the one before. This uses the draws as they happened.";
    render();
  }

  const beats = (node, x, y) => bracket[node.format][index[x]][index[y]];

  // Chance of each club winning each node, given the picks so far.
  function distributions() {
    const dist = {};
    for (const node of bracket.nodes) { // nodes are stored in round order
      if (locks[node.id]) { dist[node.id] = { [locks[node.id]]: 1 }; continue; }
      const out = {};
      if (!node.from) {
        const [a, b] = node.teams;
        out[a] = beats(node, a, b);
        out[b] = 1 - out[a];
      } else {
        const left = dist[node.from[0]], right = dist[node.from[1]];
        for (const [x, px] of Object.entries(left)) {
          for (const [y, py] of Object.entries(right)) {
            const w = beats(node, x, y);
            out[x] = (out[x] || 0) + px * py * w;
            out[y] = (out[y] || 0) + px * py * (1 - w);
          }
        }
      }
      dist[node.id] = out;
    }
    return dist;
  }

  function titleChances() {
    const final = bracket.nodes.find((n) => n.round === "Final");
    const dist = distributions()[final.id];
    return Object.fromEntries(bracket.teams.map((t) => [t, dist[t] || 0]));
  }

  // The two clubs in a tie, if both are known yet.
  function sides(node) {
    if (!node.from) return node.teams;
    const known = node.from.map((child) => locks[child]);
    return known.every(Boolean) ? known : null;
  }

  function clearAbove(nodeId) {
    let up = parent[nodeId];
    while (up !== undefined) { delete locks[up]; up = parent[up]; }
  }

  function pick(nodeId, team) {
    if (locks[nodeId] === team) delete locks[nodeId];
    else locks[nodeId] = team;
    clearAbove(nodeId);
    render();
    // The bracket is rebuilt, which drops keyboard focus; put it back on the button just pressed.
    const again = [...document.querySelectorAll("#bf-bracket .bf-pick")].find((b) => Number(b.dataset.node) === nodeId && b.dataset.team === team);
    if (again) again.focus({ preventScroll: true });
  }

  function waitingText(node, dist) {
    const names = node.from.map((child) => {
      const likely = Object.entries(dist[child]).filter(([, p]) => p > 0).sort((a, b) => b[1] - a[1]).map(([t]) => shortClub(t));
      if (likely.length === 1) return likely[0];
      if (likely.length === 2) return `${likely[0]} or ${likely[1]}`;
      return `${likely[0]}, ${likely[1]} or ${likely.length - 2} other${likely.length === 3 ? "" : "s"}`;
    });
    return `${names[0]}<br>v ${names[1]}`;
  }

  function render() {
    const box = document.getElementById("bf-bracket");
    const dist = distributions();
    box.innerHTML = ["Round of 16", "Quarterfinals", "Semifinals", "Final"].map((rnd) => {
      const nodes = bracket.nodes.filter((n) => n.round === rnd).sort((a, b) => firstSlot(a) - firstSlot(b));
      const cards = nodes.map((node) => {
        const s = sides(node);
        if (!s) return `<div class="bf-tie open"><div class="bf-wait">${waitingText(node, dist)}</div></div>`;
        return `<div class="bf-tie">${s.map((team, k) => {
          const p = beats(node, team, s[1 - k]);
          const picked = locks[node.id] === team;
          const out = locks[node.id] && !picked;
          const real = node.winner === team ? `<span class="real" title="Went through in real life">✓</span>` : "";
          const name = `${clean(team)} to beat ${clean(s[1 - k])}, ${pct(p)} chance`;
          return `<button class="bf-pick ${picked ? "picked" : ""} ${out ? "out" : ""}" data-node="${node.id}" data-team="${team.replace(/"/g, "&quot;")}" type="button" aria-pressed="${picked}" aria-label="Pick ${name.replace(/"/g, "&quot;")}">
            <span>${clean(team)}${real}</span><span class="p">${pct(p)}</span></button>`;
        }).join("")}</div>`;
      }).join("");
      return `<div><p class="round-title">${ROUND_TITLES[rnd]}</p><div class="round-ties ${rnd === "Final" ? "one" : ""}">${cards}</div></div>`;
    }).join("");
    box.querySelectorAll(".bf-pick").forEach((button) =>
      button.addEventListener("click", () => pick(Number(button.dataset.node), button.dataset.team)));
    drawButterfly();
    if (ready) writeUrl();
  }

  function firstSlot(node) {
    if (!node.from) return node.slot;
    return Math.min(...node.from.map((child) => firstSlot(bracket.nodes[child])));
  }

  function drawButterfly() {
    const now = titleChances();
    const teams = [...bracket.teams].sort((a, b) => baseline[b] - baseline[a]);
    const box = document.getElementById("bf-chart");
    const rowH = 24;
    const { root, width, height } = canvas(box, teams.length * rowH + 28);
    const m = { l: 112, r: 52, t: 4, b: 24 };
    const x = (v) => m.l + v * (width - m.l - m.r);
    for (let v = 0; v <= 1.0001; v += 0.25) {
      svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: height - m.b, stroke: css("--grid") }, root);
      svg("text", { x: x(v), y: height - 6, "text-anchor": "middle" }, root).textContent = pct(v);
    }
    legend("bf-legend", [["Gained", css("--s1")], ["Lost", css("--s2")], ["Before your picks", css("--muted")]]);
    teams.forEach((team, i) => {
      const cy = m.t + rowH * (i + 0.5);
      const before = baseline[team], after = now[team];
      const delta = after - before;
      const color = Math.abs(delta) < 0.005 ? css("--axis") : delta > 0 ? css("--s1") : css("--s2");
      svg("text", { x: m.l - 8, y: cy + 4, "text-anchor": "end", class: Math.abs(delta) >= 0.005 ? "label-strong" : "" }, root).textContent = shortClub(team);
      if (delta <= -0.005) { // what was lost, as a faded band from now back to before
        svg("rect", { x: x(after), y: cy - 7, width: x(before) - x(after), height: 14, fill: css("--s2"), opacity: 0.35 }, root);
      }
      const w = Math.max(x(after) - x(0), after > 0 ? 2 : 0);
      if (w > 0) svg("rect", { x: x(0), y: cy - 7, width: w, height: 14, fill: color, class: "grow-x", style: `--d:${i * 30}ms` }, root);
      svg("line", { x1: x(before), x2: x(before), y1: cy - 9, y2: cy + 9, stroke: css("--ink-2"), "stroke-width": 2 }, root);
      const label = Math.abs(delta) >= 0.005 ? `${delta > 0 ? "+" : "−"}${Math.round(Math.abs(delta) * 100)}` : pct(after);
      svg("text", { x: width - 4, y: cy + 4, "text-anchor": "end", class: Math.abs(delta) >= 0.005 ? "label-strong" : "" }, root).textContent = label;
      const hit = svg("rect", { x: 0, y: cy - rowH / 2, width, height: rowH, class: "hit" }, root);
      hover(hit, `<b>${clean(team)}</b><br>Before your picks: ${pct(before, 1)}<br>Now: ${pct(after, 1)}`);
    });
    const moved = teams.filter((t) => Math.abs(now[t] - baseline[t]) >= 0.005)
      .sort((a, b) => Math.abs(now[b] - baseline[b]) - Math.abs(now[a] - baseline[a]));
    const swing = document.getElementById("bf-swing");
    if (!moved.length) {
      swing.innerHTML = "Pick a winner in any tie to see the knock-on effects. The tick marks each club's chance before your picks.";
    } else {
      const t = moved[0];
      const others = moved.length - 1;
      swing.innerHTML = `Biggest swing: <b>${clean(t)}</b>, ${pct(baseline[t])} → <b>${pct(now[t])}</b>.` +
        (others ? ` Your picks moved ${others} other club${others === 1 ? "" : "s"} too.` : "");
    }
  }

  select.addEventListener("change", () => load(Number(select.value)));
  document.getElementById("bf-reset").addEventListener("click", () => { locks = {}; render(); });
  document.getElementById("bf-real").addEventListener("click", () => {
    locks = Object.fromEntries(bracket.nodes.map((n) => [n.id, n.winner]));
    render();
  });
  document.getElementById("bf-share").addEventListener("click", async () => {
    const status = document.getElementById("bf-share-status");
    const url = `${location.origin}${location.pathname}${location.search}#butterfly`;
    const moved = Object.keys(locks).length;
    const title = `What if? ${bracket.season} Champions League`;
    try {
      if (navigator.share && matchMedia("(pointer: coarse)").matches) {
        await navigator.share({ title, text: moved ? "Look what my picks do to everyone's chances" : title, url });
        return;
      }
      await navigator.clipboard.writeText(url);
      status.textContent = "Link copied";
    } catch (e) {
      if (e && e.name === "AbortError") return; // closed the share sheet
      status.textContent = "Copy this link: " + url;
    }
    clearTimeout(status.timer);
    status.timer = setTimeout(() => { status.textContent = ""; }, 4000);
  });
  load(0);
  readUrl();
  ready = true;
  return () => drawButterfly();
}

// ---------- comeback meter ----------
const RHO = -0.05;       // Dixon–Coles low-score correction, tuned in week 2
const HOME_EDGE = 0.29;  // home advantage in log-goals, from the Dixon–Coles fit
const MAX = 10;
const RAMP = ["#ebe5d6", "#d6cbb1", "#b9aa88", "#94866a", "#6b604c", "#433c30", "#1c1a15"]; // sequential paper to ink

function poissonPmf(lambda) {
  const out = [Math.exp(-lambda)];
  for (let k = 1; k <= MAX; k++) out.push(out[k - 1] * lambda / k);
  return out;
}

function scoreGrid(home, away, rho) {
  const h = poissonPmf(home), a = poissonPmf(away);
  const grid = h.map((ph) => a.map((pa) => ph * pa));
  if (rho) {
    grid[0][0] *= 1 - home * away * rho;
    grid[0][1] *= 1 + home * rho;
    grid[1][0] *= 1 + away * rho;
    grid[1][1] *= 1 - rho;
  }
  const total = grid.flat().reduce((s, v) => s + v, 0);
  return grid.map((row) => row.map((v) => v / total));
}

// Chance that "we" go through, given the first-leg score and who hosts the second leg.
function throughChance({ venue, us, them, strength, awayRule, base }) {
  const weHost = venue === "away"; // away in the first leg means at home in the second
  const ours = base * Math.exp(strength / 2), theirs = base * Math.exp(-strength / 2);
  const edge = Math.exp(HOME_EDGE / 2);
  const hostGoals = (weHost ? ours : theirs) * edge;
  const visitorGoals = (weHost ? theirs : ours) / edge;
  const second = scoreGrid(hostGoals, visitorGoals, RHO);
  const extra = scoreGrid(hostGoals / 3, visitorGoals / 3, 0);
  let hostET = 0, visitorET = 0, levelScoring = 0;
  extra.forEach((row, k) => row.forEach((p, l) => {
    if (k > l) hostET += p; else if (l > k) visitorET += p; else if (k > 0) levelScoring += p;
  }));
  const goalless = extra[0][0];
  // In extra time under the away-goals rule, a scoring draw goes to the visitors.
  const visitorAfterET = visitorET + (awayRule ? levelScoring + goalless / 2 : (levelScoring + goalless) / 2);
  const weAfterET = weHost ? 1 - visitorAfterET : visitorAfterET;

  let chance = 0;
  second.forEach((row, k) => row.forEach((p, l) => {
    const usTotal = us + (weHost ? k : l);
    const themTotal = them + (weHost ? l : k);
    const usAway = weHost ? us : l;   // goals we scored away from home
    const themAway = weHost ? l : them;
    if (usTotal > themTotal) chance += p;
    else if (usTotal === themTotal) {
      if (awayRule && usAway !== themAway) chance += usAway > themAway ? p : 0;
      else chance += p * weAfterET;
    }
  }));
  return chance;
}

// Real ties that started this way, played under the chosen rules (t[3] is 1 for away goals).
function historyFor(ties, venue, us, them, awayRule) {
  const matching = ties.filter((t) => t[3] === (awayRule ? 1 : 0) &&
    (venue === "home" ? t[0] === us && t[1] === them : t[1] === us && t[0] === them));
  const through = matching.filter((t) => (venue === "home" ? t[2] === 1 : t[2] === 0)).length;
  return { n: matching.length, through };
}

function wilson(k, n) {
  if (!n) return [0, 0];
  const z = 1.96, p = k / n;
  const centre = (p + z * z / (2 * n)) / (1 + z * z / n);
  const half = (z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n);
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

function rampColor(t) {
  const x = Math.max(0, Math.min(1, t)) * (RAMP.length - 1);
  const i = Math.min(Math.floor(x), RAMP.length - 2), f = x - i;
  const hex = (c) => [1, 3, 5].map((j) => parseInt(c.slice(j, j + 2), 16));
  const [a, b] = [hex(RAMP[i]), hex(RAMP[i + 1])];
  return `rgb(${a.map((v, j) => Math.round(v + (b[j] - v) * f)).join(",")})`;
}

// Ink or paper text, whichever has more contrast on this cell colour.
function textOn(fill) {
  const [r, g, b] = fill.match(/\d+/g).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const l = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return (l + 0.05) / 0.0568 > 0.9 / (l + 0.05) ? "#16140f" : "#f2eee4"; // 0.0568, 0.9: ink and paper luminance + 0.05
}

function setupComeback(data) {
  const history = data.comebacks;
  const base = Math.sqrt(history.second_leg_home_goals * history.second_leg_away_goals);
  const state = { venue: "away", us: 0, them: 2 };
  const usSelect = document.getElementById("cb-us"), themSelect = document.getElementById("cb-them");
  const goals = [0, 1, 2, 3, 4, 5].map((g) => `<option value="${g}">${g}</option>`).join("");
  usSelect.innerHTML = goals;
  themSelect.innerHTML = goals;
  const strength = document.getElementById("cb-strength"), rules = document.getElementById("cb-rules");
  const settings = () => ({ venue: state.venue, strength: Number(strength.value), awayRule: rules.value === "1", base });

  function render() {
    usSelect.value = state.us;
    themSelect.value = state.them;
    document.querySelectorAll(".cb-controls .seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.venue === state.venue)));
    const model = throughChance({ ...settings(), us: state.us, them: state.them });
    const real = historyFor(history.ties, state.venue, state.us, state.them, settings().awayRule);
    const era = settings().awayRule ? "with away goals" : "under today's rules";
    document.getElementById("cb-model").textContent = chance(model);
    document.getElementById("cb-model-bar").style.width = pct(model, 1);
    const histBar = document.getElementById("cb-hist-bar"), range = document.getElementById("cb-hist-range");
    if (real.n) {
      const rate = real.through / real.n;
      const [lo, hi] = wilson(real.through, real.n);
      document.getElementById("cb-hist").textContent = pct(rate);
      document.getElementById("cb-hist-label").textContent = `Real ties ${era}: ${real.through} of ${real.n} went through`;
      histBar.style.width = pct(rate, 1);
      range.style.left = pct(lo, 1);
      range.style.width = pct(hi - lo, 1);
      range.hidden = false;
    } else {
      document.getElementById("cb-hist").textContent = "–";
      document.getElementById("cb-hist-label").textContent = `Real ties ${era}: none started this way`;
      histBar.style.width = "0%";
      range.hidden = true;
    }
    const where = state.venue === "home" ? "at home" : "away";
    const result = state.us > state.them ? "won" : state.us < state.them ? "lost" : "drew";
    document.getElementById("cb-text").innerHTML =
      `You ${result} <b>${state.us}-${state.them} ${where}</b> in the first leg, so the second leg is ${state.venue === "home" ? "away" : "at home"}. ` +
      (state.venue === "away" && real.n ? "Real teams in your spot usually host the second leg because they were seeded, so they tend to be the stronger side. Try \"Stronger\" to compare like with like. " : "") +
      (real.n >= 10 ? `The grey line on the real-ties bar shows the 95% range: with ${real.n} ties, the true rate is probably between ${pct(wilson(real.through, real.n)[0])} and ${pct(wilson(real.through, real.n)[1])}.`
        : real.n ? `Only ${real.n} real tie${real.n === 1 ? "" : "s"} started this way, so trust the model more than the history here.` : "");
    drawHeat();
  }

  function drawHeat() {
    const box = document.getElementById("cb-heat");
    const n = 5;
    const size = Math.min(box.clientWidth, 380);
    const { root, width } = canvas(box, size + 44);
    const m = { l: 44, t: 40 };
    const cell = (Math.min(width, size) - m.l) / n;
    document.getElementById("cb-heat-sub").textContent =
      `Rows: your first-leg goals. Columns: theirs. First leg ${state.venue === "home" ? "at home" : "away"}; tap a square to choose that score.` +
      (rules.value === "1" ? " With away goals, a 2-2 draw is not the same as 0-0: the team that scored away has the edge."
        : " Under today's rules only the goal difference matters, so each diagonal shows the same chance.");
    svg("text", { x: m.l + (cell * n) / 2, y: 12, "text-anchor": "middle" }, root).textContent = "Their goals";
    const yLabel = svg("text", { x: 12, y: m.t + (cell * n) / 2, "text-anchor": "middle", transform: `rotate(-90 12 ${m.t + (cell * n) / 2})` }, root);
    yLabel.textContent = "Your goals";
    for (let k = 0; k < n; k++) {
      svg("text", { x: m.l + cell * (k + 0.5), y: m.t - 6, "text-anchor": "middle" }, root).textContent = k;
      svg("text", { x: m.l - 8, y: m.t + cell * (k + 0.5) + 4, "text-anchor": "end" }, root).textContent = k;
    }
    for (let us = 0; us < n; us++) {
      for (let them = 0; them < n; them++) {
        const p = throughChance({ ...settings(), us, them });
        const x = m.l + them * cell, y = m.t + us * cell;
        const wave = `--d:${(us + them) * 70}ms`;
        const rect = svg("rect", { x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, fill: rampColor(p), class: "cell pop", style: wave }, root);
        svg("text", { x: x + cell / 2, y: y + cell / 2 + 4, "text-anchor": "middle", style: `fill:${textOn(rampColor(p))};font-weight:500;pointer-events:none;${wave}`, class: "fade" }, root).textContent = chance(p);
        if (us === state.us && them === state.them) {
          svg("rect", { x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, fill: "none", stroke: css("--s2"), "stroke-width": 3, "pointer-events": "none" }, root);
        }
        const real = historyFor(history.ties, state.venue, us, them, settings().awayRule);
        hover(rect, `<b>${us}-${them} ${state.venue === "home" ? "at home" : "away"}</b><br>Model: ${chance(p)} chance to go through<br>` +
          (real.n ? `Real ties: ${real.through} of ${real.n}` : "No real ties started this way"),
          () => { state.us = us; state.them = them; render(); });
      }
    }
  }

  document.querySelectorAll(".cb-controls .seg button").forEach((b) => b.addEventListener("click", () => { state.venue = b.dataset.venue; render(); }));
  usSelect.addEventListener("change", () => { state.us = Number(usSelect.value); render(); });
  themSelect.addEventListener("change", () => { state.them = Number(themSelect.value); render(); });
  [strength, rules].forEach((s) => s.addEventListener("change", render));
  render();
  return drawHeat;
}

// ---------- the season forecast ----------
// Who will win this season's Champions League, from src/forecast.py: the rest of the season played out
// 100,000 times. Each number is the share of those seasons in which the club got that far.
const FORECAST_STAGES = [
  ["top8", "Top 8", "finish the league phase in the top eight, straight into the last 16"],
  ["top24", "Top 24", "finish the league phase in the top 24 and reach the knockouts"],
  ["last16", "Last 16", "reach the round of 16"],
  ["quarter", "QF", "reach the quarter-finals"],
  ["semi", "SF", "reach the semi-finals"],
  ["final", "Final", "reach the final"],
  ["win", "Win", "win the trophy"],
];
const FORECAST_ROWS = 12;
// A small chance of winning needs a decimal, or the foot of the table would be a column of "1%"s.
const forecastChance = (stage, p) => (stage === "win" && p > 0 && p < 0.1 ? (p < 0.0005 ? "<0.1%" : `${(p * 100).toFixed(1)}%`) : chance(p));
const forecastDate = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

// The title chance of the leading clubs on every day the forecast was made, from before the first matchday on.
function drawForecastHistory(data) {
  const fc = data.forecast, box = document.getElementById("fc-hist-chart"), section = document.getElementById("fc-history");
  const h = fc && fc.history;
  section.hidden = !(h && h.dates.length >= 2);
  if (section.hidden) return;
  const lead = Object.keys(h.win).sort((a, b) => h.win[b].at(-1) - h.win[a].at(-1)).slice(0, 6);
  const times = h.dates.map((d) => Date.parse(`${d}T12:00:00Z`));
  const t0 = times[0], t1 = times.at(-1);
  const top = Math.max(...lead.map((c) => Math.max(...h.win[c])));
  const maxY = Math.ceil(top * 20) / 20;
  const { root, width, height } = canvas(box, 260);
  const m = { l: 36, r: width < 560 ? 100 : 150, t: 10, b: 28 };
  const x = (i) => m.l + ((times[i] - t0) / (t1 - t0 || 1)) * (width - m.l - m.r);
  const y = (v) => height - m.b - (v / maxY) * (height - m.t - m.b);
  for (let v = 0; v <= maxY + 1e-9; v += 0.05) {
    svg("line", { x1: m.l, x2: width - m.r, y1: y(v), y2: y(v), stroke: css("--grid") }, root);
    svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = pct(v);
  }
  const day = (iso) => forecastDate(iso).replace(/ \d{4}$/, "");
  [0, h.dates.length - 1].forEach((i) => svg("text", { x: x(i), y: height - 8, "text-anchor": i ? "end" : "start" }, root).textContent = i ? day(h.dates[i]) : "Before matchday 1");
  const colours = [css("--s2"), css("--s1"), css("--s3"), css("--muted"), css("--ink-2"), css("--axis")];
  const ends = [];
  lead.forEach((club, k) => {
    const pts = h.win[club].map((v, i) => `${x(i)},${y(v)}`).join(" ");
    svg("polyline", { points: pts, fill: "none", stroke: colours[k], "stroke-width": k === 0 ? 3 : 2, "stroke-linejoin": "round" }, root);
    h.win[club].forEach((v, i) => svg("circle", { cx: x(i), cy: y(v), r: 3, fill: colours[k] }, root));
    ends.push({ club, y: y(h.win[club].at(-1)), colour: colours[k] });
  });
  ends.sort((a, b) => a.y - b.y);  // keep the end labels from landing on top of each other
  for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 14);
  ends.forEach((e) => svg("text", { x: width - m.r + 8, y: e.y + 4, fill: e.colour === css("--axis") ? css("--ink-2") : e.colour }, root).textContent = width < 560 ? shortClub(e.club) : clean(e.club));
  h.dates.forEach((d, i) => {
    const left = i ? (x(i - 1) + x(i)) / 2 : 0, right = i < h.dates.length - 1 ? (x(i) + x(i + 1)) / 2 : width - m.r;
    const hit = svg("rect", { x: left, y: 0, width: Math.max(right - left, 8), height, class: "hit" }, root);
    hover(hit, () => `<b>${i ? `After ${day(d)}` : "Before matchday 1"}</b>` + lead.map((c) => `<br>${clean(c)} ${forecastChance("win", h.win[c][i])}`).join(""));
  });
  document.getElementById("fc-history-note").textContent =
    `One forecast for each day of results so far, from before the first matchday to ${day(h.dates.at(-1))}. Each is made only from what was known on that day. The six clubs shown are today's most likely winners.`;
}

function fillForecast(data) {
  const fc = data.forecast;
  const section = document.getElementById("forecast");
  const link = document.querySelector('nav a[href="#forecast"]');
  section.hidden = link.hidden = !fc;
  if (!fc) return;
  const sims = fc.simulations.toLocaleString("en-GB");
  const day = forecastDate(fc.as_of);
  const term = (key, text) => `<span class="term" tabindex="0" data-term="${key}">${text}</span>`;
  document.getElementById("fc-title").textContent = `Who'll win ${fc.season}?`;
  const PHASES = { // where the season is: what is over, what the model plays out
    playoffs: ["the league phase is over", "the play-offs and then the rest of the knockout phase, "],
    last16: ["the play-offs are over", "the last 16 and then the rest of the knockout phase, "],
    quarter: ["the last 16 is over", "the quarter-finals and then the rest of the knockout phase, "],
    semi: ["the quarter-finals are over", "the semi-finals and the final, "],
    final: ["the semi-finals are over", "the final, "],
  };
  const phase = PHASES[fc.phase];
  const suffix = `${sims} times (a ${term("simulation", "simulation")}) and counts how often each club gets how far. It runs again every morning.`;
  document.getElementById("fc-sub").innerHTML = fc.phase === "done"
    ? `As of ${day}, the final has been played: ${clean(fc.clubs.reduce((a, b) => (b.win > a.win ? b : a)).club)} won the trophy. This forecast comes down in a few days.`
    : ((!fc.phase || fc.phase === "league") && fc.left
      ? `As of ${day}, ${fc.played} of the ${fc.matches} matches of the ${term("league-phase", "league phase")} have been played. The model plays the other ${fc.left}, then the whole knockout phase, `
      : `As of ${day}, ${phase ? phase[0] : `the ${term("league-phase", "league phase")} is over`}. The model plays out ${phase ? phase[1] : "the whole knockout phase, "}`) + suffix;

  const byClub = new Map(fc.clubs.map((c) => [c.club, c]));
  const isNew = new Set(fc.new_clubs || []);
  let sortBy = "win";
  let expanded = false;
  const head = document.getElementById("fc-head");
  head.innerHTML = `<th scope="col">Club</th><th scope="col" class="num fc-pts" title="Points so far in the league phase">Pts</th>` +
    FORECAST_STAGES.map(([stage, label, what]) =>
      `<th scope="col" class="num fc-${stage}"><button class="fc-sort" type="button" data-stage="${stage}" title="Sort by the chance to ${what}">${label}</button></th>`).join("");
  const body = document.querySelector("#fc-table tbody");
  const more = document.getElementById("fc-more");

  const render = () => {
    const ordered = [...fc.clubs].sort((a, b) => b[sortBy] - a[sortBy] || b.win - a.win || a.club.localeCompare(b.club));
    const shown = expanded ? ordered : ordered.slice(0, FORECAST_ROWS);
    body.innerHTML = shown.map((c) =>
      `<tr data-club="${c.club.replace(/"/g, "&quot;")}"><td class="fc-club">${clean(c.club)}${isNew.has(c.club) ? `<span class="fc-star" title="Rated from this season's matches alone">*</span>` : ""}</td>` +
      `<td class="num fc-pts">${c.points}</td>` +
      FORECAST_STAGES.map(([stage]) =>
        `<td class="num fc-cell fc-${stage}" data-stage="${stage}" style="--p:${c[stage]}">${stage === "win" ? `<b>${forecastChance(stage, c[stage])}</b>` : forecastChance(stage, c[stage])}</td>`).join("") + "</tr>").join("");
    head.querySelectorAll("th").forEach((th) => {
      const button = th.querySelector(".fc-sort");
      if (!button) return;
      th.setAttribute("aria-sort", button.dataset.stage === sortBy ? "descending" : "none");
    });
    body.querySelectorAll(".fc-cell").forEach((cell) => hover(cell, () => {
      const c = byClub.get(cell.closest("tr").dataset.club);
      const [stage, , what] = FORECAST_STAGES.find(([key]) => key === cell.dataset.stage);
      const p = c[stage];
      return `<b>${clean(c.club)}</b><br>${p > 0 && p < 0.5 ? `${(p * 100).toFixed(1)}% to ${what} (about ${oneIn(p)})` : `${(p * 100).toFixed(1)}% to ${what}`}<br>${c.points} points after ${c.played} matches`;
    }));
    more.textContent = expanded ? `Show the top ${FORECAST_ROWS}` : `Show all ${fc.clubs.length} clubs`;
    more.hidden = fc.clubs.length <= FORECAST_ROWS;
  };
  head.addEventListener("click", (e) => {
    const button = e.target.closest(".fc-sort");
    if (!button) return;
    sortBy = button.dataset.stage;
    render();
  });
  more.addEventListener("click", () => { expanded = !expanded; render(); });
  render();

  const best = [...fc.clubs].sort((a, b) => b.win - a.win);
  const topFive = best.slice(0, 5).reduce((sum, c) => sum + c.win, 0);
  document.getElementById("fc-text").innerHTML = fc.phase === "done" ? `<b>${clean(best[0].club)}</b> won the trophy.` :
    `The favourite is <b>${clean(best[0].club)}</b>, which wins in ${pct(best[0].win)} of the simulated seasons, about ${Math.round(1 / best[0].win) === 1 ? "every one" : `1\u00a0in\u00a0${Math.round(1 / best[0].win)}`}. ` +
    `Even the five best clubs together win ${pct(topFive)}, so in about ${Math.round(1 / (1 - topFive)) <= 1 ? "no" : `1\u00a0in\u00a0${Math.round(1 / (1 - topFive))}`} seasons the trophy goes to a club outside them.`;
  const strangers = (fc.new_clubs || []).map(clean);
  const note = document.getElementById("fc-new");
  note.hidden = !strangers.length;
  if (strangers.length) {
    const names = strangers.length > 1 ? `${strangers.slice(0, -1).join(", ")} and ${strangers.at(-1)}` : strangers[0];
    note.textContent = `* ${names} ${strangers.length > 1 ? "have" : "has"} no earlier matches in the data, so ${strangers.length > 1 ? "are" : "is"} rated from this season's matches alone. Their numbers are the least certain.`;
  }
  document.getElementById("fc-how-list").innerHTML = [
    `<b>Strength.</b> The same goals model that rates every club on this page, fitted to results up to ${day}, including this season's league-phase matches. Clubs don't improve or decline during the season in the simulations, and the model knows nothing about injuries, transfers, line-ups or the betting market.`,
    `<b>League phase.</b> ${fc.left ? `Each of the ${fc.left} matches still to play` : "Every match"} gets a scoreline drawn at random from the model's chances. The table is sorted the way UEFA sorts it: points, goal difference, goals scored, away goals scored, wins, away wins. What UEFA looks at after that is left to chance.`,
    `<b>Knockouts.</b> ${fc.phase && fc.phase !== "league" ? "Once a draw is made the ties are the real ones, and every leg already played counts: after a first leg, the second is played out knowing its score. " : ""}The top eight go straight to the last 16, and 9th to 24th play off for the other eight places. The bracket, and the second leg at home for the better-placed side, follow the 2025-26 rules, with random draws and no country protection, as then. Each tie uses the exact chance of going through two legs (extra time, then penalties); the final is one match on neutral ground.`,
    `<b>How exact is it?</b> Each number comes from ${sims} simulated seasons, so it is good to a few tenths of a point. The bigger uncertainty is the model: it treats every club's strength as known, which makes favourites look a little surer than they are, and bookmakers' title odds also use team news and the betting market, so they will differ. This is a forecast from results alone, not betting advice.`,
    `<b>Source.</b> This season's fixtures and results are read each morning from <a href="${fc.source}" rel="noopener">Wikipedia</a> (<a href="https://creativecommons.org/licenses/by-sa/4.0/" rel="noopener">CC BY-SA 4.0</a>).`,
  ].map((html) => `<li>${html}</li>`).join("");
}

// ---------- live ----------
function fillLive(data) {
  const live = data.live;
  const section = document.getElementById("live");
  if (!live) {
    section.hidden = true;
    document.querySelector('nav a[href="#live"]').hidden = true;
    return;
  }
  document.getElementById("live-sub").textContent =
    `How each club would do in one match against an average club from this season's big five leagues, on a neutral pitch: ` +
    `the goals it would score and concede on average, and its chance of winning. ` +
    `From the goals model${live.updated ? `, updated ${live.updated}` : ""}, using ${live.window_years ? `the last ${live.window_years} years of matches` : "recent matches"}` +
    `${live.fitted_through ? ` up to ${live.fitted_through}` : ""}, with recent matches counting more.`;
  document.querySelector("#ratings-table tbody").innerHTML = live.ratings.map((r, i) =>
    `<tr><td class="num">${i + 1}</td><td>${clean(r.club)}</td><td class="num">${r.scores.toFixed(1)}</td><td class="num">${r.concedes.toFixed(1)}</td><td class="num"><b>${pct(r.win)}</b></td>` +
    `<td class="rbar-cell"><span class="rbar" style="width:${r.win * 100}%"></span></td></tr>`).join("");
  const cell = (value, label) => `<div class="stat"><span class="stat-value">${value}</span><span class="stat-label">${label}</span></div>`;
  document.getElementById("ledger").innerHTML = !live.predictions
    ? `<p class="small ledger-wait">No predictions yet this week. League fixtures are usually published a few days ahead, ` +
      `and the model's predictions for them appear here the next morning${live.updated ? ` (last checked ${live.updated})` : ""}.</p>`
    : cell(live.predictions, "predictions saved") +
      cell(live.scored, "matches played and scored") +
      (live.model_brier != null ? cell(live.model_brier.toFixed(3), "the model's error score so far (lower is better)") + cell(live.book_brier.toFixed(3), "the bookmakers' error score so far")
        : `<p class="small" style="grid-column:1/-1">None of these matches has been played yet. Each is scored once it has.</p>`);
  // The predictions waiting for kick-off, soonest first, in the reader's own time zone.
  const upcoming = [...(live.upcoming || [])].sort((a, b) => String(a.kickoff || a.date).localeCompare(String(b.kickoff || b.date))).slice(0, 10);
  const box = document.getElementById("upcoming");
  box.hidden = !upcoming.length;
  if (!upcoming.length) return;
  const when = (m) => {
    const at = m.kickoff ? new Date(m.kickoff.replace(" UTC", "Z").replace(" ", "T")) : null;
    return at && !isNaN(at) ? at.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
      : new Date(`${String(m.date).slice(0, 10)}T12:00:00Z`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  };
  const meta = (m) => `<div class="tie-meta">${LEAGUE_NAMES[m.competition] || m.competition} · ${when(m)}</div>`;
  const hasOdds = (m) => [m.odds_home, m.odds_draw, m.odds_away].every((v) => typeof v === "number");

  // Upsets watch: for each game, the result the model rates furthest above the bookmakers.
  const watch = (live.upcoming || []).filter(hasOdds).map((m) => {
    const options = [
      { gap: m.p_home - m.odds_home, model: m.p_home, book: m.odds_home, text: `${clean(m.home)} win` },
      { gap: m.p_draw - m.odds_draw, model: m.p_draw, book: m.odds_draw, text: "Draw" },
      { gap: m.p_away - m.odds_away, model: m.p_away, book: m.odds_away, text: `${clean(m.away)} win` },
    ];
    return { m, ...options.reduce((a, b) => (b.gap > a.gap ? b : a)) };
  }).filter((w) => w.gap >= 0.05).sort((a, b) => b.gap - a.gap).slice(0, 5);
  const watchBox = document.getElementById("watch");
  watchBox.hidden = !watch.length;
  watchBox.querySelector(".fixtures").innerHTML = watch.map((w) =>
    `<div class="fixture">${meta(w.m)}<div class="fixture-teams"><b>${clean(w.m.home)}</b> v <b>${clean(w.m.away)}</b></div>` +
    `<p class="small watch-line"><b>${w.text}</b>: model ${pct(w.model)}, bookmakers ${pct(w.book)}</p></div>`).join("");

  box.querySelector(".fixtures").innerHTML = upcoming.map((m) => {
    const [h, d] = [Math.round(m.p_home * 100), Math.round(m.p_draw * 100)], a = 100 - h - d;
    const book = hasOdds(m) ? `<div class="tie-meta">Bookmakers: ${pct(m.odds_home)} · ${pct(m.odds_draw)} · ${pct(m.odds_away)}</div>` : "";
    return `<div class="fixture">${meta(m)}` +
      `<div class="fixture-teams"><b>${clean(m.home)}</b> v <b>${clean(m.away)}</b></div>` +
      `<div class="split-bar three" role="img" aria-label="${clean(m.home)} win ${h}%, draw ${d}%, ${clean(m.away)} win ${a}%">` +
      `<span class="a" style="flex:${h}">${h}%</span><span class="d" style="flex:${d}">${d >= 12 ? `${d}%` : ""}</span><span class="b" style="flex:${a}">${a}%</span></div>${book}</div>`;
  }).join("");
}

const LEAGUE_NAMES = { E0: "Premier League", SP1: "La Liga", D1: "Bundesliga", I1: "Serie A", F1: "Ligue 1" };

// ---------- theme ----------
// Charts bake their colours in when drawn, so they are redrawn whenever the theme really
// changes, however it changed: the button, the system switching, or another tab. A saved
// choice is applied in index.html, before anything draws.
function setupTheme(redraw) {
  const root = document.documentElement;
  const button = document.getElementById("theme");
  const system = matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : system.matches);
  let drawnDark = isDark();
  const sync = () => {
    button.setAttribute("aria-pressed", String(isDark()));
    if (isDark() === drawnDark) return;
    drawnDark = isDark();
    redraw();
  };
  button.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* storage unavailable */ }
  });
  new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
  if (system.addEventListener) system.addEventListener("change", sync);
  else system.addListener(sync); // Safari 13
  // Paper is white and most printers skip backgrounds, so print in the light theme.
  let screenTheme;
  // A printout can't be clicked open, so every fold-out prints open.
  let closedFolds = [];
  addEventListener("beforeprint", () => {
    closedFolds = [...document.querySelectorAll("details:not([open])")];
    closedFolds.forEach((d) => { d.open = true; });
    screenTheme = root.dataset.theme;
    if (isDark()) { root.dataset.theme = "light"; sync(); }
  });
  addEventListener("afterprint", () => {
    closedFolds.forEach((d) => { d.open = false; });
    if (screenTheme === undefined) delete root.dataset.theme;
    else root.dataset.theme = screenTheme;
    sync();
  });
  addEventListener("storage", (e) => {
    if (e.key !== "theme") return;
    if (e.newValue) root.dataset.theme = e.newValue;
    else delete root.dataset.theme;
  });
  sync();
}

// ---------- back to top ----------
// The page is long on a phone; once the reader is two screens down, offer a way back up.
function setupToTop() {
  const button = document.getElementById("to-top");
  const update = () => { button.hidden = scrollY < innerHeight * 2; };
  addEventListener("scroll", update, { passive: true });
  update();
  // Drop the nav's edge fade once it is scrolled to the end, so the last link isn't faded.
  const nav = document.querySelector("nav");
  const edge = () => nav.classList.toggle("at-end", nav.scrollLeft + nav.clientWidth >= nav.scrollWidth - 2);
  nav.addEventListener("scroll", edge, { passive: true });
  addEventListener("resize", edge);
  edge();
  button.addEventListener("click", (e) => {
    e.preventDefault();
    scrollTo({ top: 0, behavior: STILL ? "auto" : "smooth" });
    history.replaceState(null, "", location.pathname + location.search);
  });
}

// ---------- start ----------
setupReveal();
setupToTop();
setupNav();
let drawAll = () => {}; // replaced once the data has arrived
setupTheme(() => drawAll());

function start(data) {
  fillHeadline(data);
  document.querySelectorAll(".hero .stat-value").forEach((node, i) => roll(node, 650 + i * 260));
  fillScores(data);
  setupRunPicker(data);
  setupCalibration(data);
  setupTies(data);
  fillLive(data);
  fillForecast(data);
  setupGlossary();
  fillRealMadrid(data);
  const redrawSkill = setupSkill(data);
  const redrawButterfly = setupButterfly(data);
  const redrawHeat = setupComeback(data);
  setupWire(data);
  const redrawMachine = setupMachine(data);
  const redrawTicker = setupTicker(data);
  drawAll = () => { drawForecastHistory(data); redrawMachine(); redrawTicker(); drawRuns(data); redrawSkill(); drawRounds(data); drawWild(data); drawClubs(data); drawRmSplit(data); drawRmLast(data); drawCalibration(data); redrawButterfly(); redrawHeat(); };
  drawAll();
  const luck = document.querySelector("h1 em");
  document.fonts.ready.then(() => setTimeout(() => scramble(luck), 500));
  luck.addEventListener("pointerenter", () => scramble(luck));
  // Only a change of width changes the charts. Phones fire resize as the address bar
  // slides in and out, and redrawing everything then would stutter the scroll.
  let pending, drawnWidth = innerWidth;
  window.addEventListener("resize", () => {
    if (innerWidth === drawnWidth) return;
    drawnWidth = innerWidth;
    clearTimeout(pending);
    pending = setTimeout(drawAll, 120);
  });
  // The browser jumps to a #section link before the charts exist, so it lands short. Jump
  // again now they are drawn, and keep the section in place while web fonts arrive and reflow
  // the page (on a first visit they come after this), until the reader scrolls themself.
  let target = null;
  try { target = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (e) { /* malformed hash */ }
  if (target) {
    const pin = () => target.scrollIntoView({ behavior: "instant" });
    const keep = new ResizeObserver(pin);
    keep.observe(document.querySelector("main"));
    const stop = () => keep.disconnect();
    ["wheel", "touchstart", "keydown", "pointerdown"].forEach((type) => addEventListener(type, stop, { once: true, passive: true }));
    setTimeout(stop, 5000);
  }
  window.addEventListener("scroll", hideTip, { passive: true });
}

function problem(html, error) {
  console.error(error);
  document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="load-error">${html}</p>`);
}

// "no-cache" still uses the browser's copy, but only after checking it is current: the daily
// update rewrites data.json, and readers should never see yesterday's numbers.
fetch("data.json", { cache: "no-cache" })
  .then((r) => {
    if (!r.ok) throw new Error(`data.json: HTTP ${r.status}`);
    return r.json();
  })
  .then(start, (error) => problem(location.protocol === "file:"
    ? "Couldn't load data.json. Open this page through a web server (for example <code>python3 -m http.server</code> in the site folder), not as a file."
    : `Couldn't load data.json (${error.message}). Create it with <code>python src/export_site.py</code>.`, error))
  .catch((error) => problem("Something went wrong while drawing this page. Try reloading; if it keeps happening, data.json may have changed shape.", error));
