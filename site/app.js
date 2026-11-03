// Knockout Luck dashboard. Reads data.json (written by src/export_site.py) and draws
// everything with plain SVG, so the page needs no libraries and no build step.

const SVG = "http://www.w3.org/2000/svg";
const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;
// For chances shown to readers: never round a near-certainty up to 100% or down to 0%.
const chance = (x) => (x > 0.995 && x < 1 ? ">99%" : x < 0.005 && x > 0 ? "<1%" : pct(x));
const clean = (name) => name.replace(/ \([A-Z]{3}\)$/, "");
const ROUND_SHORT = { "Playoffs": "Play-offs", "Round of 16": "Last 16", "Quarterfinals": "Quarter-finals", "Semifinals": "Semi-finals", "Final": "Final" };

function svg(tag, attrs = {}, parent) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

function canvas(container, height) {
  container.innerHTML = "";
  const width = Math.max(container.clientWidth, 280);
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height }, container);
  return { root, width, height };
}

// ---------- tooltip ----------
const tip = document.getElementById("tip");
function showTip(html, event) {
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
const hideTip = () => tip.classList.remove("on");
function hover(node, html, onPick) {
  node.addEventListener("pointermove", (e) => showTip(html, e));
  node.addEventListener("pointerleave", hideTip);
  if (onPick) node.addEventListener("click", onPick);
}

function legend(id, items) {
  document.getElementById(id).innerHTML = items
    .map(([label, color, kind]) => `<span><i class="${kind || ""}" style="background:${color}"></i>${label}</span>`)
    .join("");
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------- headline ----------
function fillHeadline(data) {
  const h = data.headline;
  const fills = {
    seasons: `${h.first_season} to ${h.last_season} · ${h.ties} ties`,
    underdog: pct(h.underdog),
    "median-run": pct(h.median_champion_run),
    real: `${h.real_won} of ${h.real_ties}`,
    "real-label": `ties won by Real Madrid, when the model expected ${h.real_expected.toFixed(1)}`,
    "real-won": `${h.real_won} of ${h.real_ties}`,
    "real-expected": h.real_expected.toFixed(1),
    "test-matches": data.scores[0].matches.toLocaleString("en-GB"),
    built: data.built,
  };
  document.querySelectorAll("[data-fill]").forEach((node) => { node.textContent = fills[node.dataset.fill] ?? ""; });
}

// ---------- champions' runs ----------
function drawRuns(data) {
  const box = document.getElementById("runs-chart");
  const runs = data.champions;
  const narrow = box.clientWidth < 560;
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
    const r = Math.min(4, h, barWidth / 2);
    // Rounded top, square base anchored to the baseline.
    const x0 = cx - barWidth / 2, x1 = cx + barWidth / 2;
    svg("path", {
      d: `M${x0},${y(0)} V${top_y + r} Q${x0},${top_y} ${x0 + r},${top_y} H${x1 - r} Q${x1},${top_y} ${x1},${top_y + r} V${y(0)} Z`,
      fill: css("--s1"),
    }, root);
    if (run === most || run === least) {
      svg("text", { x: cx, y: top_y - 6, "text-anchor": "middle", class: "label-strong" }, root).textContent = pct(run.probability);
    }
    const season = svg("text", { x: cx, y: y(0) + 16, "text-anchor": "middle" }, root);
    season.textContent = narrow ? `’${run.season.slice(5)}` : run.season; // "2012-13" -> "’13"
    if (!narrow) {
      const name = svg("text", { x: cx, y: y(0) + 31, "text-anchor": "middle" }, root);
      name.textContent = shortClub(run.champion);
    }
    const hit = svg("rect", { x: cx - step / 2, y: m.t, width: step, height: height - m.t, class: "hit" }, root);
    hover(hit, `<b>${run.season}: ${clean(run.champion)}</b><br>${pct(run.probability, 1)} chance of winning every tie<br>${run.ties.map((t) => `${ROUND_SHORT[t.round]} v ${clean(t.opponent)}: ${pct(t.probability)}`).join("<br>")}`,
      () => showPath(run));
  });
  showPath(least);
}

function shortClub(name) {
  const map = { "Bayern Munich": "Bayern", "Real Madrid": "Real", "Man City": "Man City", "Paris SG": "PSG", "Barcelona": "Barça" };
  return map[name] || clean(name);
}

function showPath(run) {
  const steps = run.ties.map((t) => `<span class="path-step">${ROUND_SHORT[t.round]} v ${clean(t.opponent)}: <b>${pct(t.probability)}</b></span>`).join("");
  document.getElementById("runs-path").innerHTML =
    `<b style="color:var(--ink)">${run.season}, ${clean(run.champion)}:</b> ${pct(run.probability, 1)} to win every tie it played. Multiply the chances of each step:<div class="path-steps">${steps}</div>`;
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
  legend("rounds-legend", [["Actually went through (95% range)", css("--s1")], ["Model expected", css("--muted")]]);
  rows.forEach((row, i) => {
    const cx = m.l + step * (i + 0.5);
    const lo = Math.max(low, row.won - row.error), hi = Math.min(high, row.won + row.error);
    svg("line", { x1: cx + 7, x2: cx + 7, y1: y(lo), y2: y(hi), stroke: css("--s1"), "stroke-width": 2 }, root);
    svg("circle", { cx: cx + 7, cy: y(row.won), r: 5, fill: css("--s1"), stroke: css("--surface"), "stroke-width": 2 }, root);
    svg("circle", { cx: cx - 7, cy: y(row.expected), r: 5, fill: "none", stroke: css("--muted"), "stroke-width": 2 }, root);
    svg("text", { x: cx, y: height - 8, "text-anchor": "middle" }, root).textContent = ROUND_SHORT[row.round];
    const hit = svg("rect", { x: cx - step / 2, y: m.t, width: step, height: height - m.t - m.b, class: "hit" }, root);
    hover(hit, `<b>${row.round}</b> (${row.ties} ties)<br>Model expected the favourite through: ${pct(row.expected)}<br>Actually went through: ${pct(row.won)} (±${pct(row.error)})`);
  });
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
    svg("text", { x: m.l - 10, y: cy + 4, "text-anchor": "end", class: real ? "label-strong" : "" }, root).textContent = clean(club.club);
    svg("line", { x1: x(club.expected), x2: x(club.won), y1: cy, y2: cy, stroke: color, "stroke-width": 2 }, root);
    svg("circle", { cx: x(club.expected), cy, r: 5, fill: css("--surface"), stroke: css("--muted"), "stroke-width": 2 }, root);
    svg("circle", { cx: x(club.won), cy, r: 5, fill: color, stroke: css("--surface"), "stroke-width": 2 }, root);
    const hit = svg("rect", { x: 0, y: cy - rowH / 2, width, height: rowH, class: "hit" }, root);
    hover(hit, `<b>${clean(club.club)}</b><br>Won ${club.won} of ${club.ties} ties<br>Model expected ${club.expected.toFixed(1)}`);
  });
}

// ---------- calibration ----------
function drawCalibration(data) {
  const box = document.getElementById("cal-chart");
  const size = Math.min(box.clientWidth, 460);
  const { root, width, height } = canvas(box, size);
  const m = { l: 40, r: 12, t: 12, b: 40 };
  const x = (v) => m.l + v * (width - m.l - m.r);
  const y = (v) => m.t + (1 - v) * (height - m.t - m.b);
  for (let v = 0; v <= 1.0001; v += 0.2) {
    svg("line", { x1: x(v), x2: x(v), y1: y(0), y2: y(1), stroke: css("--grid") }, root);
    svg("line", { x1: x(0), x2: x(1), y1: y(v), y2: y(v), stroke: css("--grid") }, root);
    svg("text", { x: x(v), y: y(0) + 16, "text-anchor": "middle" }, root).textContent = pct(v);
    svg("text", { x: x(0) - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = pct(v);
  }
  svg("line", { x1: x(0), y1: y(0), x2: x(1), y2: y(1), stroke: css("--axis"), "stroke-dasharray": "4 4" }, root);
  svg("text", { x: x(0.5), y: height - 4, "text-anchor": "middle" }, root).textContent = "Predicted chance of a home win";
  const colors = { "Dixon–Coles": css("--s1"), "Elo": css("--s3"), "Bookmakers": css("--s2") };
  legend("cal-legend", [...data.calibration.map((s) => [s.name, colors[s.name], "line"]), ["Perfectly honest", css("--axis"), "line"]]);
  data.calibration.forEach((series, k) => {
    const color = colors[series.name];
    const nudge = (k - 1) * 3; // keep error bars from sitting on top of each other
    svg("polyline", { points: series.points.map((p) => `${x(p.predicted) + nudge},${y(p.actual)}`).join(" "), fill: "none", stroke: color, "stroke-width": 2 }, root);
    series.points.forEach((p) => {
      const px = x(p.predicted) + nudge;
      svg("line", { x1: px, x2: px, y1: y(Math.min(1, p.actual + p.error)), y2: y(Math.max(0, p.actual - p.error)), stroke: color, "stroke-width": 1.5, opacity: 0.7 }, root);
      svg("circle", { cx: px, cy: y(p.actual), r: 4, fill: color, stroke: css("--surface"), "stroke-width": 2 }, root);
      const hit = svg("circle", { cx: px, cy: y(p.actual), r: 12, class: "hit" }, root);
      hover(hit, `<b>${series.name}</b><br>Said ${pct(p.predicted)} on average<br>Home team won ${pct(p.actual)} (±${pct(p.error)})<br>${p.n.toLocaleString("en-GB")} matches`);
    });
  });
}

function fillScores(data) {
  const best = Math.min(...data.scores.map((s) => s.brier));
  document.querySelector("#scores-table tbody").innerHTML = data.scores.map((s) =>
    `<tr class="${s.brier === best ? "best" : ""}"><td>${s.model === "Base rates" ? "Knowing nothing (base rates)" : s.model}</td><td class="num">${s.brier.toFixed(4)}</td><td class="num">${s.log_loss.toFixed(4)}</td></tr>`).join("");
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
  const upsets = document.getElementById("f-upsets");
  const order = Object.fromEntries(rounds.map((r, i) => [r, i]));
  const more = document.getElementById("ties-more");
  const PAGE = 30;
  let shown = PAGE;
  more.addEventListener("click", () => { shown += PAGE; render(true); });

  function render(keepCount) {
    if (keepCount !== true) shown = PAGE;
    const query = club.value.trim().toLowerCase();
    const rows = data.ties.filter((t) => {
      const pWinner = t.winner === t.team_a ? t.p_a : 1 - t.p_a;
      return (!seasonSelect.value || t.season === seasonSelect.value)
        && (!roundSelect.value || t.round === roundSelect.value)
        && (!query || clean(t.team_a).toLowerCase().includes(query) || clean(t.team_b).toLowerCase().includes(query))
        && (!upsets.checked || pWinner < 0.35);
    }).sort((a, b) => b.season.localeCompare(a.season) || order[b.round] - order[a.round]);
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
        <div class="split-bar" aria-label="${clean(t.team_a)} ${a}%, ${clean(t.team_b)} ${100 - a}%">
          <span class="a" style="flex:${Math.max(a, 1)}">${a >= 12 ? a + "%" : ""}</span>
          <span class="b" style="flex:${Math.max(100 - a, 1)}">${100 - a >= 12 ? 100 - a + "%" : ""}</span>
        </div>
        <div class="team-b ${t.winner === t.team_b ? "through" : ""}">${clean(t.team_b)}</div>
      </div>`;
    }).join("") || `<p class="small">No ties match these filters.</p>`;
  }
  [seasonSelect, roundSelect, upsets].forEach((n) => n.addEventListener("change", () => render()));
  club.addEventListener("input", () => render());
  render();
}

// ---------- butterfly effect: what if one result changed? ----------
const ROUND_TITLES = { "Round of 16": "Last 16", "Quarterfinals": "Quarter-finals", "Semifinals": "Semi-finals", "Final": "Final" };

function setupButterfly(data) {
  const select = document.getElementById("bf-season");
  const brackets = [...data.brackets].reverse();
  select.innerHTML = brackets.map((b, i) => `<option value="${i}">${b.season}</option>`).join("");
  let bracket, locks, baseline, parent, index;

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
        svg("rect", { x: x(after), y: cy - 7, width: x(before) - x(after), height: 14, rx: 3, fill: css("--s2"), opacity: 0.35 }, root);
      }
      const w = Math.max(x(after) - x(0), after > 0 ? 2 : 0);
      if (w > 0) svg("rect", { x: x(0), y: cy - 7, width: w, height: 14, rx: Math.min(4, w / 2), fill: color }, root);
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
  load(0);
  return () => drawButterfly();
}

// ---------- comeback meter ----------
const RHO = -0.05;       // Dixon–Coles low-score correction, tuned in week 2
const HOME_EDGE = 0.29;  // home advantage in log-goals, from the Dixon–Coles fit
const MAX = 10;
const RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]; // sequential blue, light to dark

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

function historyFor(ties, venue, us, them) {
  const matching = ties.filter((t) => (venue === "home" ? t[0] === us && t[1] === them : t[1] === us && t[0] === them));
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
    document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.venue === state.venue)));
    const model = throughChance({ ...settings(), us: state.us, them: state.them });
    const real = historyFor(history.ties, state.venue, state.us, state.them);
    document.getElementById("cb-model").textContent = chance(model);
    document.getElementById("cb-model-bar").style.width = pct(model, 1);
    const histBar = document.getElementById("cb-hist-bar"), range = document.getElementById("cb-hist-range");
    if (real.n) {
      const rate = real.through / real.n;
      const [lo, hi] = wilson(real.through, real.n);
      document.getElementById("cb-hist").textContent = pct(rate);
      document.getElementById("cb-hist-label").textContent = `Real ties: ${real.through} of ${real.n} went through`;
      histBar.style.width = pct(rate, 1);
      range.style.left = pct(lo, 1);
      range.style.width = pct(hi - lo, 1);
      range.hidden = false;
    } else {
      document.getElementById("cb-hist").textContent = "–";
      document.getElementById("cb-hist-label").textContent = "Real ties: none started this way";
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
        const rect = svg("rect", { x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, rx: 4, fill: rampColor(p), class: "cell" }, root);
        const dark = p > 0.45;
        svg("text", { x: x + cell / 2, y: y + cell / 2 + 4, "text-anchor": "middle", style: `fill:${dark ? "#fff" : "#0b0b0b"};font-weight:600;pointer-events:none` }, root).textContent = chance(p);
        if (us === state.us && them === state.them) {
          svg("rect", { x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, rx: 4, fill: "none", stroke: css("--s2"), "stroke-width": 3, "pointer-events": "none" }, root);
        }
        const real = historyFor(history.ties, state.venue, us, them);
        hover(rect, `<b>${us}-${them} ${state.venue === "home" ? "at home" : "away"}</b><br>Model: ${chance(p)} chance to go through<br>` +
          (real.n ? `Real ties: ${real.through} of ${real.n}` : "No real ties started this way"),
          () => { state.us = us; state.them = them; render(); });
      }
    }
  }

  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => { state.venue = b.dataset.venue; render(); }));
  usSelect.addEventListener("change", () => { state.us = Number(usSelect.value); render(); });
  themSelect.addEventListener("change", () => { state.them = Number(themSelect.value); render(); });
  [strength, rules].forEach((s) => s.addEventListener("change", render));
  render();
  return drawHeat;
}

// ---------- live ----------
function fillLive(data) {
  const live = data.live;
  const section = document.getElementById("live");
  if (!live) { section.hidden = true; return; }
  document.getElementById("live-sub").textContent =
    `Attack and defence strengths from the goals model, refitted on every match up to ${live.updated}. Higher is better; 0 is an average big-five club.`;
  const sign = (v) => (v >= 0 ? "+" : "") + v.toFixed(2);
  document.querySelector("#ratings-table tbody").innerHTML = live.ratings.map((r, i) =>
    `<tr><td class="num">${i + 1}</td><td>${clean(r.club)}</td><td class="num">${sign(r.attack)}</td><td class="num">${sign(r.defence)}</td><td class="num"><b>${sign(r.overall)}</b></td></tr>`).join("");
  const cell = (value, label) => `<div class="stat"><span class="stat-value">${value}</span><span class="stat-label">${label}</span></div>`;
  document.getElementById("ledger").innerHTML =
    cell(live.predictions, "predictions saved") +
    cell(live.scored, "matches played and scored") +
    (live.model_brier != null ? cell(live.model_brier.toFixed(3), "model Brier so far") + cell(live.book_brier.toFixed(3), "bookmakers' Brier so far")
      : `<p class="small" style="grid-column:1/-1">No predictions scored yet. The ledger fills as upcoming fixtures are published and played.</p>`);
}

// ---------- theme ----------
function setupTheme(redraw) {
  const button = document.getElementById("theme");
  try {
    const saved = localStorage.getItem("theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (e) { /* storage unavailable: follow the system setting */ }
  button.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
    redraw();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
}

// ---------- start ----------
fetch("data.json")
  .then((r) => r.json())
  .then((data) => {
    fillHeadline(data);
    fillScores(data);
    setupTies(data);
    fillLive(data);
    const redrawButterfly = setupButterfly(data);
    const redrawHeat = setupComeback(data);
    const drawAll = () => { drawRuns(data); drawRounds(data); drawClubs(data); drawCalibration(data); redrawButterfly(); redrawHeat(); };
    drawAll();
    setupTheme(drawAll);
    let pending;
    window.addEventListener("resize", () => { clearTimeout(pending); pending = setTimeout(drawAll, 120); });
    window.addEventListener("scroll", hideTip, { passive: true });
  })
  .catch(() => {
    document.querySelector("main").insertAdjacentHTML("afterbegin",
      `<p class="card">Couldn't load data.json. Open this page through a web server (for example <code>python3 -m http.server</code> in the site folder), not as a file.</p>`);
  });
