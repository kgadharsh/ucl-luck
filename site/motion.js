// Motion for the Knockout Luck page: the luck machine, the upsets wire, rolling numbers,
// the scrambled headline, scroll reveals and the reading progress bar. Loaded before
// app.js, which calls these once data.json has arrived and supplies css(), pct(),
// clean(), showTip(), hideTip(), ROUND_SHORT, scoreTip() and filterTies().

const STILL = matchMedia("(prefers-reduced-motion: reduce)").matches;
const ROUND_ORDER = { Playoffs: 0, "Round of 16": 1, Quarterfinals: 2, Semifinals: 3, Final: 4 };
const winnerChance = (t) => (t.winner === t.team_a ? t.p_a : 1 - t.p_a);
const loserOf = (t) => (t.winner === t.team_a ? t.team_b : t.team_a);

// ---------- the luck machine ----------
// Every tie drops through a Galton board and lands on the chance the team that went
// through had before the first leg. The path through the pegs is random; the bin is not.
// The line under the board describes the ball as it is released, so the text and the ball
// you are watching fall are the same tie. (Every ball takes about 1.3 seconds to fall, and
// up to dozens are in the air at once, so describing a ball only as it lands would always
// be about one you've already stopped watching.) The pile, ripples and tallies update on landing.
function setupMachine(data) {
  const board = document.getElementById("machine");
  const ctx = board.getContext("2d");
  const readout = document.getElementById("machine-now");
  const scoreUnder = document.getElementById("ms-under"), scoreFav = document.getElementById("ms-fav");
  const ROWS = 9, BINS = 10, DROP = 260, HOP = 82, EXIT = 360;
  const FLIGHT = DROP + (ROWS - 1) * HOP + EXIT;

  // In the order they were played, so the board fills season by season.
  const ties = data.ties.map((t) => ({ ...t, p: winnerChance(t) }))
    .sort((a, b) => a.season.localeCompare(b.season) || ROUND_ORDER[a.round] - ROUND_ORDER[b.round]);
  const counts = Array(BINS).fill(0);
  ties.forEach((t) => {
    t.bin = Math.min(BINS - 1, Math.floor(t.p * BINS));
    t.upset = t.p < 0.5;
    t.slot = counts[t.bin]++; // every ball takes as long to fall, so slots fill in release order
  });
  const tallest = Math.max(...counts);
  const upsetCount = ties.filter((t) => t.upset).length;
  board.setAttribute("aria-label", `A Galton board of all ${ties.length} knockout ties. Each ball lands on the chance the team that went through had beforehand; ` +
    `${upsetCount} land left of 50%, where the underdog went through.`);

  let g, colors, balls = [], ghosts = [], ripples = [];
  const pegs = new Map();
  // The machine runs on its own clock, advanced frame by frame, so a background tab
  // pauses it instead of letting every ball land at once when the reader comes back.
  let clock = 0, lastFrame = 0, frameId = 0, idleTimer = 0, hovered = null, visible = false, started = false, finished = false;
  let tally = { under: 0, fav: 0 };
  let paused = false;
  const pauseButton = document.getElementById("machine-pause");
  pauseButton.hidden = STILL;

  // Moving content needs a way to stop it: Pause holds the drop and the idle replays.
  function setPaused(on) {
    paused = on;
    pauseButton.textContent = on ? "Resume" : "Pause";
    // Resuming always restarts the loop: even with nothing falling, the last ripples need
    // to fade and finish() needs to run if the pause landed in that last moment.
    if (!on && started && !frameId) frameId = requestAnimationFrame(frame);
  }

  function layout() {
    const w = board.parentElement.clientWidth;
    const s = Math.min(56, w / BINS); // peg spacing, which is also the bin width
    const pileLimit = Math.max(110, s * 2.5);
    let fit = { r: 0 };
    for (let c = 2; c <= 8; c++) { // balls per row in a bin: the biggest balls that still fit the tallest pile
      const r = Math.min((s - 4) / (2 * c), pileLimit / (2 * Math.ceil(tallest / c)));
      if (r > fit.r) fit = { c, r };
    }
    const pegTop = 34, dy = s * 0.56;
    const lastRow = pegTop + (ROWS - 1) * dy;
    const base = lastRow + s * 0.45 + Math.ceil(tallest / fit.c) * 2 * fit.r + 6;
    const h = Math.ceil(base + 24);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    board.width = Math.round(w * dpr);
    board.height = Math.round(h * dpr);
    board.style.width = `${w}px`;
    board.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    g = { w, h, s, dy, pegTop, lastRow, base, x0: (w - s * BINS) / 2, cx: w / 2, c: fit.c, r: fit.r, pegR: Math.max(1.6, s * 0.05) };
  }

  const pegX = (row, m) => g.cx + (2 * m - row) * g.s / 2;
  const pegY = (row) => g.pegTop + row * g.dy;
  function slotXY(t) {
    const col = t.slot % g.c, row = Math.floor(t.slot / g.c);
    const left = g.x0 + t.bin * g.s + (g.s - g.c * 2 * g.r) / 2;
    return [left + g.r + col * 2 * g.r, g.base - g.r - row * 2 * g.r];
  }

  // A random route through the pegs that still ends in the right bin: `bin` rights out of ROWS.
  function route(bin) {
    const moves = Array.from({ length: ROWS }, (_, k) => (k < bin ? 1 : 0));
    for (let k = ROWS - 1; k > 0; k--) {
      const j = Math.floor(Math.random() * (k + 1));
      [moves[k], moves[j]] = [moves[j], moves[k]];
    }
    return moves;
  }

  // Where a ball is `age` ms after release: [x, y, last peg row touched, that peg's index].
  function place(ball, age) {
    const lift = g.r + g.pegR; // the ball's centre sits this far above a peg it touches
    if (age < DROP) {
      const u = age / DROP;
      return [g.cx, 6 + (pegY(0) - lift - 6) * u * u, -1, 0];
    }
    const into = age - DROP;
    const row = Math.min(ROWS - 1, Math.floor(into / HOP));
    let m = 0;
    for (let k = 0; k < row; k++) m += ball.moves[k];
    const xa = pegX(row, m), ya = pegY(row) - lift;
    let xb, yb, u, bounce;
    if (row < ROWS - 1) {
      u = (into - row * HOP) / HOP;
      xb = pegX(row + 1, m + ball.moves[row]);
      yb = pegY(row + 1) - lift;
      bounce = g.dy * 0.42;
    } else { // off the last peg and down into the pile
      u = Math.min(1, (into - row * HOP) / EXIT);
      [xb, yb] = slotXY(ball.t);
      bounce = g.dy * 0.3;
    }
    const sideways = 1 - (1 - u) * (1 - u);
    return [xa + (xb - xa) * sideways, ya + (yb - ya) * u * u - bounce * 4 * u * (1 - u), row, m];
  }

  function fly(ball, age, time) {
    const [x, y, row, m] = place(ball, age);
    if (row > ball.row) {
      ball.row = row;
      pegs.set(row * 16 + m, { at: time, color: ball.t.upset ? colors.red : colors.ink });
    }
    ball.trail.push([x, y]);
    if (ball.trail.length > 6) ball.trail.shift();
    ball.x = x;
    ball.y = y;
  }

  function ripple(t, time) {
    const [x, y] = slotXY(t);
    ripples.push({ x, y, at: time, color: t.upset ? colors.red : colors.ink });
  }

  function say(t) {
    readout.innerHTML = `<b>${t.season} · ${ROUND_SHORT[t.round]}</b> ${clean(t.winner)} beat ${clean(loserOf(t))}, ` +
      `<span class="${t.upset ? "red" : ""}">${pct(t.p)} chance</span>`;
  }

  function score() {
    scoreUnder.textContent = tally.under;
    scoreFav.textContent = tally.fav;
  }

  function land(ball, time) {
    ball.landed = true;
    tally[ball.t.upset ? "under" : "fav"]++;
    score();
    if (time !== undefined) ripple(ball.t, time);
  }

  function release() {
    cancelAnimationFrame(frameId);
    clearTimeout(idleTimer);
    frameId = 0;
    started = true;
    finished = false;
    paused = false; // not setPaused(): that would start a second loop alongside the one below
    pauseButton.textContent = "Pause";
    hovered = null;
    ghosts = [];
    ripples = [];
    pegs.clear();
    tally = { under: 0, fav: 0 };
    score();
    let at = 0;
    balls = ties.map((t, i) => {
      const ball = { t, moves: route(t.bin), start: at, row: -1, trail: [], landed: false };
      at += 24 + 125 * Math.exp(-i / 14); // slow enough to follow at first, then a downpour
      return ball;
    });
    if (STILL) {
      balls.forEach((ball) => land(ball));
      finish();
      draw(performance.now());
      return;
    }
    clock = 0;
    lastFrame = 0;
    frameId = requestAnimationFrame(frame);
  }

  function frame(time) {
    if (paused) { frameId = 0; lastFrame = 0; return; }
    clock += lastFrame ? Math.min(64, time - lastFrame) : 0;
    lastFrame = time;
    let busy = false;
    for (const ball of balls) {
      if (ball.landed) continue;
      busy = true;
      const age = clock - ball.start;
      if (age < 0) continue;
      if (!ball.said) { ball.said = true; say(ball.t); } // in release order, so the newest one is what stays on screen
      if (age >= FLIGHT) land(ball, time);
      else fly(ball, age, time);
    }
    ghosts = ghosts.filter((ghost) => {
      const age = clock - ghost.start;
      if (age < FLIGHT) { fly(ghost, age, time); return true; }
      ripple(ghost.t, time);
      return false;
    });
    ripples = ripples.filter((r) => time - r.at < 700);
    draw(time);
    const glowing = ripples.length || [...pegs.values()].some((p) => time - p.at < 500);
    if (busy || ghosts.length || glowing) frameId = requestAnimationFrame(frame);
    else {
      frameId = 0;
      lastFrame = 0;
      if (!finished) finish();
    }
  }

  function finish() {
    finished = true;
    readout.innerHTML = `All ${ties.length} ties are in: the underdog went through ${tally.under} times (${pct(tally.under / ties.length)}), ` +
      `close to the ${pct(data.headline.underdog)} the model expected. <span class="screen-only"><b>${matchMedia("(hover: hover)").matches ? "Hover" : "Tap"} a ball</b> to see its tie.</span>`;
    idle();
  }

  // Once the board is full it keeps ticking over: every few seconds one tie is replayed.
  function idle() {
    if (STILL) return;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      if (visible && !document.hidden && !hovered && !paused && finished) {
        const t = ties[Math.floor(Math.random() * ties.length)];
        ghosts.push({ t, moves: route(t.bin), start: clock, row: -1, trail: [], ghost: true });
        say(t);
        if (!frameId) frameId = requestAnimationFrame(frame);
      }
      idle();
    }, 2600);
  }

  function dot(x, y, r) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  function ring(x, y, r) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
  }

  function draw(time) {
    const { w, h, s, x0, base, lastRow, r } = g;
    ctx.clearRect(0, 0, w, h);

    // Hopper, bin walls and floor.
    ctx.strokeStyle = colors.wall;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(g.cx - s * 0.75, 2);
    ctx.lineTo(g.cx - r * 2, g.pegTop - g.dy * 0.75);
    ctx.moveTo(g.cx + s * 0.75, 2);
    ctx.lineTo(g.cx + r * 2, g.pegTop - g.dy * 0.75);
    ctx.stroke();
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let k = 0; k <= BINS; k++) {
      const x = Math.round(x0 + k * s) + 0.5;
      ctx.moveTo(x, k === 0 || k === BINS ? lastRow + s * 0.3 : lastRow);
      ctx.lineTo(x, base);
    }
    ctx.stroke();
    ctx.strokeStyle = colors.red; // the 50% wall: everything left of it was an upset
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(g.cx, lastRow + g.pegR + 2);
    ctx.lineTo(g.cx, base);
    ctx.stroke();
    ctx.strokeStyle = colors.rule;
    ctx.beginPath();
    ctx.moveTo(x0, base + 1);
    ctx.lineTo(x0 + BINS * s, base + 1);
    ctx.stroke();
    ctx.fillStyle = colors.text;
    ctx.font = `500 10px "IBM Plex Mono", ui-monospace, monospace`;
    ctx.textBaseline = "top";
    [[0, "left", "0%"], [5, "center", "50%"], [10, "right", "100%"]].forEach(([k, align, label]) => {
      ctx.textAlign = align;
      ctx.fillText(label, x0 + k * s, base + 9);
    });
    for (let k = 1; k < BINS; k++) {
      ctx.fillRect(Math.round(x0 + k * s), base + 3, 1, k === 5 ? 0 : 3);
    }

    // Pegs, glowing for a moment after each hit.
    for (let row = 0; row < ROWS; row++) {
      for (let m = 0; m <= row; m++) {
        const x = pegX(row, m), y = pegY(row);
        const hit = pegs.get(row * 16 + m);
        const f = hit ? Math.max(0, 1 - (time - hit.at) / 500) : 0;
        if (f > 0) {
          ctx.strokeStyle = hit.color;
          ctx.globalAlpha = f * 0.5;
          ctx.lineWidth = 1.5;
          ring(x, y, g.pegR + (1 - f) * s * 0.32);
          ctx.globalAlpha = 1;
        }
        ctx.fillStyle = f > 0 ? hit.color : colors.peg;
        dot(x, y, g.pegR * (1 + f * 0.9));
      }
    }

    // The pile. Hovering a ball lights up the rest of its season.
    for (const ball of balls) {
      if (!ball.landed) continue;
      const [x, y] = slotXY(ball.t);
      ctx.globalAlpha = hovered && ball.t.season !== hovered.t.season ? 0.16 : 1;
      ctx.fillStyle = ball.t.upset ? colors.red : colors.ink;
      dot(x, y, r - 0.4);
    }
    ctx.globalAlpha = 1;
    if (hovered) {
      const [x, y] = slotXY(hovered.t);
      ctx.strokeStyle = colors.ink;
      ctx.lineWidth = 1.5;
      ring(x, y, r + 2.5);
    }

    // Balls in flight, with a short fading trail.
    for (const ball of [...balls, ...ghosts]) {
      if (ball.landed || ball.x === undefined) continue;
      const color = ball.t.upset ? colors.red : colors.ink;
      ctx.fillStyle = color;
      ball.trail.forEach(([x, y], k) => {
        ctx.globalAlpha = ((k + 1) / (ball.trail.length + 1)) * 0.3;
        dot(x, y, r * (0.45 + (0.5 * k) / ball.trail.length));
      });
      ctx.globalAlpha = ball.ghost ? 0.8 : 1;
      dot(ball.x, ball.y, r);
    }

    for (const rp of ripples) {
      const f = (time - rp.at) / 700;
      ctx.globalAlpha = (1 - f) * 0.7;
      ctx.strokeStyle = rp.color;
      ctx.lineWidth = 1.5;
      ring(rp.x, rp.y, r + f * s * 0.45);
    }
    ctx.globalAlpha = 1;
  }

  function ballAt(e) {
    const box = board.getBoundingClientRect();
    const x = e.clientX - box.left, y = e.clientY - box.top;
    let best = null, bestD = (g.r + 3) ** 2;
    for (const ball of balls) {
      if (!ball.landed) continue;
      const [bx, by] = slotXY(ball.t);
      const d = (bx - x) ** 2 + (by - y) ** 2;
      if (d <= bestD) { best = ball; bestD = d; }
    }
    return best;
  }

  const tipFor = (t) => `<b>${t.season}, ${ROUND_SHORT[t.round]}</b><br>${clean(t.winner)} beat ${clean(loserOf(t))}<br>${scoreTip(t)}<br>` +
    `${pct(t.p)} chance beforehand${t.p < 0.35 ? " · an upset" : t.upset ? " · the underdog" : ""}<br><span style="opacity:.6">Click to find it below</span>`;

  board.addEventListener("pointermove", (e) => {
    const ball = ballAt(e);
    if (ball !== hovered) {
      hovered = ball;
      if (!frameId) draw(performance.now());
    }
    board.style.cursor = ball ? "pointer" : "";
    if (ball) showTip(tipFor(ball.t), e);
    else hideTip();
  });
  // The highlighted season must clear however the pointer leaves the board; a stuck one would
  // also hold off the idle replays, which wait for the board not to be hovered.
  const unhover = () => {
    if (!hovered) return;
    hovered = null;
    board.style.cursor = "";
    if (!frameId) draw(performance.now());
  };
  board.addEventListener("pointerleave", () => { unhover(); hideTip(); });
  document.addEventListener("pointermove", (e) => { if (e.target !== board) unhover(); }, { passive: true });
  document.documentElement.addEventListener("pointerleave", unhover);
  window.addEventListener("blur", unhover);
  board.addEventListener("click", (e) => {
    const ball = ballAt(e);
    if (ball) filterTies({ season: ball.t.season, round: ball.t.round, club: clean(ball.t.winner), upsets: false }, true);
  });
  document.getElementById("machine-replay").addEventListener("click", release);
  pauseButton.addEventListener("click", () => setPaused(!paused));

  // Printing or saving as PDF captures whatever is on the canvas, so show the finished board.
  function settle() {
    if (finished && !frameId) return;
    cancelAnimationFrame(frameId);
    frameId = 0;
    lastFrame = 0;
    started = true;
    if (!balls.length) balls = ties.map((t) => ({ t, moves: route(t.bin), start: 0, row: -1, trail: [], landed: false }));
    ghosts = [];
    ripples = [];
    pegs.clear();
    tally = { under: 0, fav: 0 };
    balls.forEach((ball) => { ball.landed = true; tally[ball.t.upset ? "under" : "fav"]++; });
    score();
    finish();
    draw(performance.now());
  }
  addEventListener("beforeprint", settle);
  matchMedia("print").addEventListener?.("change", (e) => { if (e.matches) settle(); });

  // Start when the board comes into view, once the fonts it labels with have loaded.
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible && !started) {
      started = true;
      // Wait for the fonts it labels with, and for the hero's opening animation to settle.
      document.fonts.ready.then(() => setTimeout(release, STILL ? 0 : Math.max(0, 1400 - performance.now())));
    }
  }, { threshold: 0.2 }).observe(board);

  return function redraw() {
    colors = { ink: css("--s1"), red: css("--s2"), wall: css("--axis"), peg: css("--ink-2"), rule: css("--rule"), text: css("--muted") };
    layout();
    draw(performance.now());
  };
}

// ---------- upsets wire ----------
function setupWire(data) {
  const belt = document.getElementById("wire-belt");
  const upsets = data.ties.map((t) => ({ ...t, p: winnerChance(t) })).filter((t) => t.p < 0.35).sort((a, b) => a.p - b.p);
  // Items stay out of the tab order: 22 stops before the nav is too many, and the same
  // upsets are one filter away in the tie explorer.
  const item = (t, i) => `<button type="button" class="wire-item" data-i="${i}" tabindex="-1">` +
    `<b>${clean(t.winner)}</b> beat ${clean(loserOf(t))} <span class="wp">${pct(t.p)} chance</span> <span class="wm">${t.season} ${ROUND_SHORT[t.round]}</span></button>`;
  const run = (hidden) => `<div class="wire-run"${hidden ? ' aria-hidden="true"' : ""}>${upsets.map(item).join("")}</div>`;
  belt.innerHTML = run(false) + run(true); // two copies, so sliding by half loops seamlessly
  document.fonts.ready.then(() => belt.style.setProperty("--wire-time", `${Math.round(belt.firstElementChild.scrollWidth / 42)}s`));
  belt.addEventListener("click", (e) => {
    const button = e.target.closest(".wire-item");
    if (!button) return;
    const t = upsets[button.dataset.i];
    filterTies({ season: t.season, round: t.round, club: clean(t.winner), upsets: false }, true);
  });
  const wire = belt.closest(".wire"), pause = document.getElementById("wire-pause");
  // With reduced motion the strip stands still and scrolls sideways instead, so it must be
  // reachable by keyboard.
  if (STILL) belt.parentElement.tabIndex = 0;
  pause.addEventListener("click", () => {
    const on = !wire.classList.contains("paused");
    wire.classList.toggle("paused", on);
    pause.setAttribute("aria-pressed", String(on));
  });
}

// ---------- rolling numbers ----------
// Each digit is a strip of digits that rolls up into place, like a stadium scoreboard.
function roll(node, delay) {
  const text = node.textContent;
  if (STILL || !text) return;
  node.innerHTML = `<span class="sr">${text}</span>` + [...text].map((ch, i) => {
    if (!/\d/.test(ch)) return `<span class="odo" aria-hidden="true"><span>${ch === " " ? "&nbsp;" : ch}</span></span>`;
    const d = Number(ch), n = 10 + d;
    const strip = Array.from({ length: n + 1 }, (_, k) => (d - k + 20) % 10).join("<br>");
    return `<span class="odo odo-roll" aria-hidden="true" style="--n:${n};--d:${delay + i * 120}ms"><span>${strip}</span></span>`;
  }).join("");
}

// ---------- the headline's last word, shuffled like a fruit machine ----------
// The shuffled letters are drawn over the word by CSS (data-scramble), never written into
// it, so the real text is always "luck?" for copying, printing, search engines and screen readers.
function scramble(node) {
  if (STILL || node.dataset.scramble !== undefined) return;
  const final = node.textContent, glyphs = "ABCDEFGHKLMNPRSTUVWXYZ0123456789%";
  const start = performance.now();
  let last = 0;
  function step(time) {
    const k = (time - start) / 950;
    if (time - last > 60) {
      last = time;
      const settled = Math.floor(Math.max(0, k) * final.length);
      node.dataset.scramble = [...final].map((ch, i) => (i < settled ? ch : glyphs[Math.floor(Math.random() * glyphs.length)])).join("");
    }
    if (k < 1) requestAnimationFrame(step);
    else delete node.dataset.scramble;
  }
  requestAnimationFrame(step);
}

// ---------- scroll reveals ----------
// Each section's rule draws across, then its heading, intro and charts arrive in turn.
function setupReveal() {
  const cards = document.querySelectorAll(".card");
  if (STILL || !("IntersectionObserver" in window)) {
    cards.forEach((card) => card.classList.add("in", "done"));
    return;
  }
  // Arriving from a link to a section (#butterfly), the reader came for that section: show it,
  // and anything else already on screen, finished at once rather than waiting for its entrance.
  // The page re-pins the section as charts and fonts arrive, so "arriving" lasts until the reader
  // scrolls themself (or 5 seconds); sections they scroll to after that still animate in.
  let arriving = Boolean(location.hash);
  if (arriving) {
    const done = () => { arriving = false; };
    ["wheel", "touchstart", "keydown", "pointerdown"].forEach((type) => addEventListener(type, done, { once: true, passive: true }));
    setTimeout(done, 5000);
  }
  const seen = new IntersectionObserver((entries) => entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    seen.unobserve(entry.target);
    if (arriving) { entry.target.classList.add("instant", "in", "done"); return; }
    entry.target.classList.add("in");
    setTimeout(() => entry.target.classList.add("done"), 2800); // later redraws appear without animating
  }), { rootMargin: "0px 0px -12% 0px" });
  cards.forEach((card) => seen.observe(card));
}

// ---------- reading progress and the section you're in ----------
// The current section is the last one whose top has passed 40% of the way down the
// screen, worked out from scroll position so it follows the reader exactly.
function setupNav() {
  const nav = document.querySelector("nav");
  const links = [...nav.querySelectorAll("a")];
  const sections = links.map((a) => document.querySelector(a.hash));
  const bar = document.getElementById("progress");
  let current = null, queued = false;
  const update = () => {
    queued = false;
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? scrollY / max : 0})`;
    let here = -1;
    sections.forEach((section, i) => { if (section && !section.hidden && section.getBoundingClientRect().top <= innerHeight * 0.4) here = i; });
    if (max > 0 && scrollY >= max - 2) { // the last section may be too short to reach the line
      for (let i = sections.length - 1; i >= 0; i--) if (sections[i] && !sections[i].hidden) { here = i; break; }
    }
    const link = links[here] || null;
    if (link === current) return;
    current = link;
    links.forEach((a) => (a === link ? a.setAttribute("aria-current", "location") : a.removeAttribute("aria-current")));
    if (link) nav.scrollTo({ left: link.offsetLeft - nav.offsetLeft - 16, behavior: STILL ? "auto" : "smooth" });
  };
  const queue = () => {
    if (!queued) { queued = true; requestAnimationFrame(update); }
  };
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue);
  addEventListener("load", queue);
  update();
}
