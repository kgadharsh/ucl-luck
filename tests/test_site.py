"""The dashboard in real browsers (Chromium, Firefox and WebKit, via Playwright).

Each test pins down something that was broken once: wrong colours after a theme change,
content off-screen on phones, tooltips that stuck, a hover zone bigger than its bar, blank
printouts, a deep link landing in the wrong place, and so on.
"""

import io
import re
from math import comb

import pytest
from pypdf import PdfReader

from test_data import odds_of_doing_as_well

REVEAL = "document.querySelectorAll('.card').forEach((c) => c.classList.add('in', 'done'))"

# Does anything on the page still use the *other* theme's colours?
THEME_CHECK = """() => {
  const T = {
    light: ["#16140f", "#d23d1c", "#dcd5c4", "#b3aa94", "#6c6556", "#f2eee4", "#a39878", "#4a463c"],
    dark: ["#ece6d6", "#ec5a35", "#2a2822", "#4a463c", "#857e6e", "#13120f", "#8c8263", "#bdb6a4"],
  };
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const mine = new Set(T[dark ? "dark" : "light"]);
  const foreign = new Set(T[dark ? "light" : "dark"].filter((c) => !mine.has(c)));
  const bad = [];
  document.querySelectorAll("svg *").forEach((el) => {
    if (el.closest("#cb-heat") && el.tagName === "text") return; // ink or paper, chosen per cell
    for (const a of ["fill", "stroke"]) {
      const v = (el.getAttribute(a) || "").toLowerCase();
      if (foreign.has(v)) bad.push(`${el.closest(".chart")?.id} ${el.tagName} ${a}=${v}`);
    }
  });
  const canvas = document.getElementById("machine"), d = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  let invisible = 0, marks = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] < 230) continue;
    marks++;
    const sum = d[i] + d[i + 1] + d[i + 2];
    if (dark ? sum < 120 : sum > 640) invisible++; // a mark the colour of the page
  }
  return { dark, bad, invisible, marks, pressed: document.getElementById("theme").getAttribute("aria-pressed") };
}"""

OVERFLOW = """() => {
  const W = document.documentElement.clientWidth;
  return [...document.querySelectorAll("main *, header *, .mast *")]
    .filter((el) => !el.closest(".wire-track, nav, .tip, .odo, #ticker-chart g[clip-path]"))
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && (r.right > W + 1 || r.left < -1); })
    .map((el) => `${el.tagName.toLowerCase()}#${el.id}.${el.getAttribute("class") || ""}`);
}"""


def underdog_count(data):
    return sum((t["p_a"] if t["winner"] == t["team_a"] else 1 - t["p_a"]) < 0.5 for t in data["ties"])


def only_in(browser_name, *names):
    if browser_name not in names:
        pytest.skip(f"only runs in {', '.join(names)}")


# ---------- the page loads and draws everything ----------

def test_page_draws_every_section(open_page, data):
    page = open_page()
    counts = page.evaluate("""() => ({
      strip: document.querySelectorAll('.strip-bar').length,
      champions: document.querySelectorAll('#runs-chart .bar').length,
      tieRows: document.querySelectorAll('#ties-list .tie').length,
      ratings: document.querySelectorAll('#ratings-table tbody tr').length,
      calibration: document.querySelectorAll('#cal-chart circle:not(.hit)').length,
      bracket: document.querySelectorAll('#bf-bracket .bf-pick').length,
      heat: document.querySelectorAll('#cb-heat rect.cell').length,
    })""")
    assert counts["strip"] == len(data["ties"])
    assert counts["champions"] == len(data["champions"])
    assert counts["tieRows"] == 30 and counts["ratings"] == 20 and counts["heat"] == 25
    assert counts["calibration"] > 0 and counts["bracket"] > 0


def test_numbers_are_filled_from_the_data(open_page, data):
    page = open_page()
    h = data["headline"]
    assert page.locator(".hero .stat-value .sr").first.text_content() == f"{round(h['underdog'] * 100)}%"
    assert page.locator('[data-fill="finals"]').first.text_content() == str(len(data["champions"]))
    assert page.locator('[data-fill="real-odds"]').first.text_content() == odds_of_doing_as_well(data["ties"], "Real Madrid")


def test_missing_data_says_why_and_the_theme_button_still_works(open_page):
    page = open_page(wait=False, allow_errors=True, routes={"**/data.json": lambda route: route.fulfill(status=404)})
    message = page.locator(".load-error")
    message.wait_for()
    assert "HTTP 404" in message.text_content()
    before = page.evaluate("document.documentElement.dataset.theme || null")
    page.click("#theme")
    assert page.evaluate("document.documentElement.dataset.theme") != before


# ---------- colours ----------

@pytest.mark.parametrize("system", ["light", "dark"])
@pytest.mark.parametrize("saved", [None, "light", "dark"])
def test_charts_use_the_current_themes_colours(open_page, site_url, system, saved):
    page = open_page(color_scheme=system, reduced_motion="reduce", wait=False)
    if saved:
        page.evaluate(f"localStorage.setItem('theme', '{saved}')")
    page.goto(site_url)
    page.wait_for_function("document.querySelectorAll('.strip-bar').length > 0")
    for step in ["load", "toggle", "toggle back"]:
        if step != "load":
            page.click("#theme")
        result = page.evaluate(THEME_CHECK)
        expected_dark = (saved or system) == "dark" if step != "toggle" else (saved or system) != "dark"
        assert result["dark"] == expected_dark, step
        assert result["bad"] == [], f"{step}: {result['bad'][:3]}"
        assert result["invisible"] == 0 and result["marks"] > 1000, step
        assert result["pressed"] == str(expected_dark).lower(), step


def test_charts_follow_a_system_theme_switch(open_page):
    page = open_page(color_scheme="light", reduced_motion="reduce")
    assert page.evaluate(THEME_CHECK)["dark"] is False
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(200)
    result = page.evaluate(THEME_CHECK)
    assert result["dark"] is True and result["bad"] == [] and result["invisible"] == 0


# ---------- layout ----------

@pytest.mark.parametrize("width", [320, 375, 768, 920, 1280, 1920])
def test_nothing_runs_off_screen(open_page, width):
    page = open_page(width=width, reduced_motion="reduce")
    page.evaluate(REVEAL)
    assert page.evaluate(OVERFLOW) == []
    page.select_option("#f-season", "2021-22")  # the zoomed season strip too
    page.wait_for_timeout(200)
    assert page.evaluate(OVERFLOW) == []


def test_accessibility_scan_finds_nothing(open_page):
    for scheme in ["light", "dark"]:
        page = open_page(color_scheme=scheme, reduced_motion="reduce")
        page.evaluate(REVEAL)
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js")
        violations = page.evaluate("""async () => (await axe.run(document, { resultTypes: ['violations'] })).violations
          .map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(', ')}`)""")
        assert violations == [], f"{scheme}: {violations}"


# ---------- motion ----------

def test_reduced_motion_shows_everything_finished(open_page, data):
    page = open_page(reduced_motion="reduce")
    hidden = page.evaluate("[...document.querySelectorAll('.card > *')].filter((el) => getComputedStyle(el).opacity !== '1').length")
    assert hidden == 0
    assert page.text_content("#ms-under") == str(underdog_count(data))
    assert page.text_content("#ms-fav") == str(len(data["ties"]) - underdog_count(data))
    assert page.evaluate("getComputedStyle(document.querySelector('.wire-belt')).animationName") == "none"


def test_headline_text_never_changes_while_it_shuffles(open_page):
    page = open_page()
    seen = set()
    for _ in range(15):
        seen.add(page.text_content("h1 em"))
        page.wait_for_timeout(100)
    assert seen == {"luck?"}


def test_the_machine_drops_every_tie_and_can_pause(open_page, data):
    page = open_page()
    page.locator("#machine").scroll_into_view_if_needed()
    page.wait_for_function("+document.getElementById('ms-under').textContent + +document.getElementById('ms-fav').textContent > 5", timeout=10000)
    page.click("#machine-pause")
    landed = page.evaluate("+document.getElementById('ms-under').textContent + +document.getElementById('ms-fav').textContent")
    page.wait_for_timeout(700)
    assert page.evaluate("+document.getElementById('ms-under').textContent + +document.getElementById('ms-fav').textContent") == landed
    page.click("#machine-pause")
    page.wait_for_function(f"document.getElementById('ms-fav').textContent === '{len(data['ties']) - underdog_count(data)}'", timeout=20000)
    page.wait_for_function("document.getElementById('machine-now').textContent.startsWith('All')", timeout=5000)


def test_replaying_the_machine_never_runs_two_loops(open_page, browser_name):
    only_in(browser_name, "chromium")
    page = open_page()
    page.locator("#machine").scroll_into_view_if_needed()
    for _ in range(4):
        page.click("#machine-replay")
        page.wait_for_timeout(250)
    per_frame = page.evaluate("""async () => {
      const ctx = document.getElementById('machine').getContext('2d');
      let draws = 0; const clear = ctx.clearRect.bind(ctx); ctx.clearRect = (...a) => { draws++; return clear(...a); };
      let frames = 0, run = true; const tick = () => { frames++; if (run) requestAnimationFrame(tick); };
      requestAnimationFrame(tick); await new Promise((r) => setTimeout(r, 600)); run = false;
      return draws / frames;
    }""")
    assert per_frame < 1.3


# ---------- pointer and keyboard ----------

def _shortest_champion_bar(page):
    page.locator("#runs-chart").scroll_into_view_if_needed()
    page.wait_for_timeout(150)  # let the scroll event pass: scrolling (correctly) hides tooltips
    return page.evaluate("""() => {
      const bars = [...document.querySelectorAll('#runs-chart .bar')];
      const r = bars.reduce((a, b) => (b.getBoundingClientRect().height < a.getBoundingClientRect().height ? b : a)).getBoundingClientRect();
      return { x: r.x + r.width / 2, top: r.top, bottom: r.bottom, height: r.height };
    }""")


def test_hover_zone_is_the_bar_not_the_whole_column(open_page):
    page = open_page(reduced_motion="reduce")
    bar = _shortest_champion_bar(page)
    tip = page.locator("#tip")
    page.mouse.move(bar["x"], bar["top"] - 60)
    assert "on" not in tip.get_attribute("class")
    page.mouse.move(bar["x"], bar["top"] + bar["height"] / 2)
    assert "on" in tip.get_attribute("class")
    page.wait_for_timeout(300)  # the fade is a short transition
    faded = page.evaluate("[...document.querySelectorAll('#runs-chart .bar')].filter((b) => getComputedStyle(b).opacity < 0.5).length")
    assert faded == page.locator("#runs-chart .bar").count() - 1  # every bar but the hovered one


def test_tooltip_hides_however_the_pointer_leaves(open_page):
    page = open_page(reduced_motion="reduce", color_scheme="light")
    bar = _shortest_champion_bar(page)
    tip = page.locator("#tip")
    page.mouse.move(bar["x"], bar["bottom"] - 4)
    assert "on" in tip.get_attribute("class")
    page.mouse.move(20, 20)  # straight to somewhere else, as when the pointer leaves quickly
    assert "on" not in tip.get_attribute("class")
    page.mouse.move(bar["x"], bar["bottom"] - 4)
    page.emulate_media(color_scheme="dark")  # the chart is redrawn under the pointer
    page.wait_for_timeout(100)
    assert "on" not in tip.get_attribute("class")


def test_a_tap_shows_a_tooltip_on_touch_screens(open_page, browser_name):
    only_in(browser_name, "chromium", "webkit")  # Playwright's Firefox can't emulate touch
    page = open_page(width=375, has_touch=True, is_mobile=browser_name == "chromium", reduced_motion="reduce")
    page.locator("#rounds-chart").scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    page.locator("#rounds-chart rect.hit").first.tap()
    assert "on" in page.locator("#tip").get_attribute("class")


def test_keyboard_reaches_the_nav_quickly(open_page):
    page = open_page(reduced_motion="reduce")
    order = page.evaluate("""[...document.querySelectorAll('a[href], button, select, input')]
      .filter((el) => el.tabIndex >= 0 && !el.hidden && el.offsetParent !== null)
      .slice(0, 4).map((el) => el.id || el.textContent.trim().slice(0, 12))""")
    assert order[:2] == ["theme", "wire-pause"] and order[2] == "Champions"


def test_a_bracket_pick_keeps_keyboard_focus(open_page):
    page = open_page(reduced_motion="reduce")
    first = page.locator("#bf-bracket .bf-pick").first
    node, team = first.get_attribute("data-node"), first.get_attribute("data-team")
    first.focus()
    page.keyboard.press("Enter")
    focused = page.evaluate("[document.activeElement.dataset.node, document.activeElement.dataset.team, document.activeElement.getAttribute('aria-pressed')]")
    assert focused == [node, team, "true"]


# ---------- navigation ----------

def test_a_link_to_a_section_lands_on_it(open_page):
    page = open_page("#honest")
    page.wait_for_timeout(1500)
    top = page.evaluate("document.getElementById('honest').getBoundingClientRect().top")
    padding = page.evaluate("parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop)")
    assert abs(top - padding) <= 8, f"section top at {top}px, should sit just below the sticky header at {padding}px"


def test_nav_highlights_the_section_you_are_reading(open_page):
    page = open_page(reduced_motion="reduce")
    mismatches = page.evaluate("""async () => {
      const max = document.documentElement.scrollHeight - innerHeight; let bad = 0;
      for (let y = 0; y <= max; y += 350) {
        window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60));
        const passed = [...document.querySelectorAll('main > section.card[id]')].filter((s) => s.getBoundingClientRect().top <= innerHeight * 0.4);
        const expected = scrollY >= max - 2 ? 'live' : passed.length ? passed[passed.length - 1].id : null;
        const current = document.querySelector('nav a[aria-current]')?.hash.slice(1) ?? null;
        if (current !== expected) bad++;
      }
      return bad;
    }""")
    assert mismatches == 0


# ---------- the tie explorer and its season strip ----------

def test_season_strip_zooms_pans_and_zooms_out(open_page, data):
    page = open_page(reduced_motion="reduce")
    assert page.locator("#strip-nav").is_hidden()
    page.select_option("#f-season", "2021-22")
    assert page.locator("#strip-nav b").text_content() == "2021-22"
    assert page.locator("#ticker-chart .strip-name").count() == sum(t["season"] == "2021-22" for t in data["ties"])
    page.click("#strip-nav [data-step='-1']")
    assert page.input_value("#f-season") == "2020-21"
    page.click("#strip-nav [data-all]")
    assert page.input_value("#f-season") == "" and page.locator("#strip-nav").is_hidden()


def test_strip_fades_ties_the_filters_exclude(open_page, data):
    page = open_page(reduced_motion="reduce")
    page.fill("#f-club", "Barcelona")
    bright = page.evaluate("[...document.querySelectorAll('.strip-bar')].filter((r) => r.style.opacity === '1').length")
    assert bright == sum("Barcelona" in (t["team_a"], t["team_b"]) for t in data["ties"])


def test_clicking_a_season_keeps_the_other_filters(open_page):
    page = open_page(reduced_motion="reduce")
    page.fill("#f-club", "Arsenal")
    page.evaluate("filterTies({ season: '2025-26' })")
    assert page.input_value("#f-club") == "Arsenal"


def test_comeback_compares_with_ties_played_under_the_same_rules(open_page):
    page = open_page(reduced_motion="reduce")
    page.select_option("#cb-us", "2")
    page.select_option("#cb-them", "2")
    today = page.text_content("#cb-hist-label")
    page.select_option("#cb-rules", "1")
    away = page.text_content("#cb-hist-label")
    assert "today's rules" in today and "away goals" in away and today.split(":")[1] != away.split(":")[1]


def test_calibration_view_switch_leaves_the_comeback_meter_alone(open_page):
    page = open_page(reduced_motion="reduce")
    venue = lambda: page.evaluate("[...document.querySelectorAll('.cb-controls .seg button')].map((b) => b.getAttribute('aria-pressed')).join()")
    before = venue()
    page.click(".cal-view [data-view='full']")
    assert venue() == before
    assert page.locator(".cal-view [data-view='full']").get_attribute("aria-pressed") == "true"


# ---------- skill vs luck, the wildest seasons, the glossary ----------

def exact_standings(n, p):
    """Chance that a side winning each tie with chance p ends n ties ahead, level or behind."""
    ahead = level = behind = 0.0
    for k in range(n + 1):
        q = comb(n, k) * p**k * (1 - p) ** (n - k)
        if 2 * k > n:
            ahead += q
        elif 2 * k == n:
            level += q
        else:
            behind += q
    return ahead, level, behind


def ties_until_sure(p, cap=150):
    """The fewest ties after which the weaker side finishing ahead is rarer than 1 in 20, for good."""
    last_bad = max((n for n in range(1, cap + 1) if exact_standings(n, p)[2] > 0.05), default=0)
    return last_bad + 1 if last_bad < cap else None


def shown_chance(x):
    """How the page writes a chance (never rounds a near-certainty to 100% or a long shot to 0%)."""
    if 0.995 < x < 1:
        return ">99%"
    if 0 < x < 0.005:
        return "<1%"
    return f"{x * 100:.0f}%"


def set_range(page, selector, value):
    page.evaluate("""([selector, value]) => {
      const input = document.querySelector(selector);
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }""", [selector, str(value)])


def test_skill_slider_matches_the_exact_odds(open_page, data):
    page = open_page(reduced_motion="reduce")
    typical = round(data["headline"]["favourite_expected"] * 100)
    assert page.input_value("#sk-edge") == str(typical)  # starts at what a typical favourite really had
    for edge, n in [(typical, 1), (68, 5), (68, 4), (90, 1), (75, 7), (55, 30)]:
        set_range(page, "#sk-edge", edge)
        set_range(page, "#sk-n", n)
        shown = page.evaluate("['sk-ahead', 'sk-level', 'sk-behind'].map((id) => document.getElementById(id).textContent)")
        assert shown == [shown_chance(x) for x in exact_standings(n, edge / 100)], (edge, n)
        assert page.locator("#sk-chart rect:not(.hit)").count() == n + 1  # one bar for each possible number of wins
        assert page.text_content("#sk-n-out") == f"{n} {'tie' if n == 1 else 'ties'}"


def test_skill_slider_says_how_many_ties_it_takes(open_page):
    page = open_page(reduced_motion="reduce")
    set_range(page, "#sk-edge", 68)
    assert f"about {ties_until_sure(0.68)} ties" in page.text_content("#sk-text")
    set_range(page, "#sk-edge", 55)  # so close to a coin toss that 150 ties still isn't enough
    assert ties_until_sure(0.55) is None and "more than 150 ties" in page.text_content("#sk-text")


def test_skill_sliders_work_from_the_keyboard(open_page):
    page = open_page(reduced_motion="reduce")
    page.locator("#sk-n").focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert page.text_content("#sk-n-out") == "3 ties"
    assert page.locator("#sk-chart rect:not(.hit)").count() == 4
    assert "Level" not in page.text_content("#sk-legend")  # three ties can't finish level
    page.keyboard.press("ArrowRight")
    assert "Level" in page.text_content("#sk-legend")


def test_wild_seasons_match_the_ties_and_link_to_them(open_page, data):
    seasons = {}
    for t in data["ties"]:
        chance_of_winner = t["p_a"] if t["winner"] == t["team_a"] else 1 - t["p_a"]
        row = seasons.setdefault(t["season"], {"ties": 0, "upsets": 0, "expected": 0.0})
        row["ties"] += 1
        row["upsets"] += chance_of_winner < 0.5
        row["expected"] += min(t["p_a"], 1 - t["p_a"])
    ranked = sorted(seasons, key=lambda s: seasons[s]["expected"] - seasons[s]["upsets"])  # wildest first
    gap = lambda s: seasons[s]["upsets"] - seasons[s]["expected"]
    page = open_page(reduced_motion="reduce")
    labels = page.evaluate("""[...document.querySelectorAll('#wild-chart text')].map((t) => t.textContent)""")
    assert [x for x in labels if re.fullmatch(r"20\d\d-\d\d", x)] == ranked
    assert [x for x in labels if re.fullmatch(r"[+−]?\d+\.\d", x)] == [
        f"{'+' if gap(s) > 0 else '−' if gap(s) < 0 else ''}{abs(gap(s)):.1f}" for s in ranked]
    page.locator("#wild-chart rect.hit").first.click()  # the wildest season opens in the tie explorer
    assert page.input_value("#f-season") == ranked[0]
    assert page.text_content("#ties-count") == f"{seasons[ranked[0]]['ties']} ties"
    assert str(seasons[ranked[0]]["upsets"]) in page.text_content("#wild-note")


def test_glossary_terms_open_on_hover(open_page):
    page = open_page(reduced_motion="reduce")
    terms = page.locator(".term")
    assert terms.count() >= 4
    assert all(terms.nth(i).get_attribute("aria-description") for i in range(terms.count()))  # nothing undefined
    terms.first.scroll_into_view_if_needed()
    page.wait_for_timeout(150)  # scrolling (correctly) hides tooltips
    tip = page.locator("#tip")
    terms.first.hover()
    assert "on" in tip.get_attribute("class") and "Pre-match chance" in tip.text_content()
    page.mouse.move(5, 300)
    assert "on" not in tip.get_attribute("class")


def test_glossary_terms_open_from_the_keyboard_even_far_down_the_page(open_page):
    page = open_page()  # with motion, so the page scrolls smoothly to the term
    tip = page.locator("#tip")
    page.locator(".term").last.focus()
    page.wait_for_function("document.getElementById('tip').classList.contains('on')", timeout=5000)
    assert "Elo" in tip.text_content()
    page.keyboard.press("Escape")
    assert "on" not in tip.get_attribute("class")


def test_a_tap_opens_a_glossary_term_on_touch_screens(open_page, browser_name):
    only_in(browser_name, "chromium", "webkit")  # Playwright's Firefox can't emulate touch
    page = open_page(width=375, has_touch=True, is_mobile=browser_name == "chromium", reduced_motion="reduce")
    page.locator(".term").first.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    page.locator(".term").first.tap()
    assert "on" in page.locator("#tip").get_attribute("class")  # tapping elsewhere-on-the-page closes tooltips, but not this


# ---------- scores and head-to-head in the tie explorer ----------

ROUND_ORDER = ["Playoffs", "Round of 16", "Quarterfinals", "Semifinals", "Final"]


def score_line(t):
    """How the tie list writes a result: team_a's goals first, as in the row's name order."""
    legs = [f"{a}–{b}" for a, b in t["legs"]]
    if t.get("aet"):
        legs[-1] += " a.e.t."
    parts = [f"Match {legs[0]}"] if len(legs) == 1 else [f"{'2nd' if i else '1st'} leg {leg}" for i, leg in enumerate(legs)]
    if len(legs) == 2:
        parts.append(f"{sum(a for a, _ in t['legs'])}–{sum(b for _, b in t['legs'])} on aggregate")
    if "pens" in t:
        parts.append(f"{t['pens'][0]}–{t['pens'][1]} on penalties")
    elif t.get("away"):
        parts.append("away goals")
    return " · ".join(parts)


def score_tip(t):
    """The same result as a tooltip writes it: the winner's goals first."""
    flip = t["winner"] != t["team_a"]
    turn = lambda pair: pair[::-1] if flip else pair
    legs = [f"{a}–{b}" for a, b in map(turn, t["legs"])]
    if t.get("aet"):
        legs[-1] += " a.e.t."
    text = ", ".join(legs)
    if len(legs) == 2:
        text += f" ({sum(turn(l)[0] for l in t['legs'])}–{sum(turn(l)[1] for l in t['legs'])} on aggregate)"
    if "pens" in t:
        text += f", {turn(t['pens'])[0]}–{turn(t['pens'])[1]} on penalties"
    elif t.get("away"):
        text += ", away goals"
    return text


def test_every_tie_shows_how_it_ended(open_page, data):
    page = open_page(reduced_motion="reduce")
    seasons = sorted({t["season"] for t in data["ties"]})
    for season in seasons:  # every season fits on one page of the list
        page.select_option("#f-season", season)
        shown = page.locator("#ties-list .tie-score").all_text_contents()
        mine = sorted((t for t in data["ties"] if t["season"] == season), key=lambda t: -ROUND_ORDER.index(t["round"]))
        assert shown == [score_line(t) for t in mine], season
    assert any("on penalties" in score_line(t) for t in data["ties"]) and any("away goals" in score_line(t) for t in data["ties"])


def test_head_to_head_summarises_exactly_the_ties_between_two_clubs(open_page, data):
    page = open_page(reduced_motion="reduce")
    page.fill("#f-club", "Real Madrid")
    page.fill("#f-against", "Man City")  # the way fans say it, not the way the page writes it
    meetings = [t for t in data["ties"] if {t["team_a"], t["team_b"]} == {"Real Madrid", "Man City"}]
    real_won = sum(t["winner"] == "Real Madrid" for t in meetings)
    city_won = len(meetings) - real_won
    expected = sum(t["p_a"] if t["team_a"] == "Real Madrid" else 1 - t["p_a"] for t in meetings)
    times = lambda k: "once" if k == 1 else "never" if k == 0 else f"{k} times"
    assert page.text_content("#ties-count") == f"{len(meetings)} ties"
    summary = page.text_content("#h2h")
    assert f"Real Madrid v Manchester City: {len(meetings)} ties." in summary
    assert f"Real Madrid went through {times(real_won)}, Manchester City {times(city_won)}." in summary
    assert f"to go through {expected:.1f} times" in summary
    bright = page.evaluate("[...document.querySelectorAll('.strip-bar')].filter((r) => r.style.opacity === '1').length")
    assert bright == len(meetings)  # the season strip shows the same ties as the list


def test_a_half_typed_name_gets_no_misleading_summary(open_page):
    page = open_page(reduced_motion="reduce")
    page.fill("#f-club", "real")
    page.fill("#f-against", "madrid")  # could mean several clubs
    assert page.locator("#h2h").is_hidden()
    assert page.locator("#ties-list .tie").count() > 0
    page.fill("#f-against", "")
    assert page.locator("#h2h").is_hidden()


def test_the_suggested_pairings_are_the_ones_that_met_most(open_page, data):
    page = open_page(reduced_motion="reduce")
    meetings = {}
    for t in data["ties"]:
        pair = frozenset((t["team_a"], t["team_b"]))
        meetings[pair] = meetings.get(pair, 0) + 1
    chips = page.locator("#h2h-try .chip")
    assert chips.count() == 4
    counts = [int(re.search(r"(\d+) ties$", chips.nth(i).text_content()).group(1)) for i in range(4)]
    assert counts == sorted(meetings.values(), reverse=True)[:4]
    for i in range(4):  # each chip leads to exactly the number of ties it promises
        chips.nth(i).click()
        assert page.text_content("#ties-count") == f"{counts[i]} ties"
        assert page.input_value("#f-club") and page.input_value("#f-against")
    page.evaluate("filterTies({ club: 'Barcelona' })")  # searching one club starts a new search
    assert page.input_value("#f-against") == "" and page.locator("#h2h").is_hidden()


def test_a_tooltip_on_the_season_strip_gives_the_score(open_page, data):
    page = open_page(reduced_motion="reduce")
    first = max((t for t in data["ties"] if t["season"] == "2012-13" and t["round"] == "Round of 16"),
                key=lambda t: t["p_a"] if t["winner"] == t["team_a"] else 1 - t["p_a"])  # the strip's first bar
    page.locator("#ticker-chart").scroll_into_view_if_needed()
    page.wait_for_timeout(150)  # scrolling (correctly) hides tooltips
    page.locator(".strip-bar").first.hover()
    tip = page.locator("#tip")
    assert "on" in tip.get_attribute("class")
    assert score_tip(first) in tip.text_content()


def test_a_ball_in_the_luck_machine_shows_its_tie_and_score(open_page, data, browser_name):
    only_in(browser_name, "chromium")  # scanning the canvas for a ball is slow enough once
    page = open_page(reduced_motion="reduce")  # the finished machine: every ball has landed
    page.locator("#machine").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    box = page.locator("#machine").bounding_box()
    tip = page.locator("#tip")
    for row in range(1, 20):  # sweep the pile until the pointer is over a ball
        for col in range(1, 40):
            page.mouse.move(box["x"] + box["width"] * col / 40, box["y"] + box["height"] * (1 - row / 20))
            if "on" in tip.get_attribute("class"):
                assert re.search(r"\d–\d", tip.text_content()), tip.text_content()
                assert " beat " in tip.text_content() and "chance beforehand" in tip.text_content()
                return
    pytest.fail("never found a ball to hover")


# ---------- Real Madrid: the checks ----------

def test_real_madrid_checks_are_drawn_from_the_analysis(open_page, data):
    rm = data["real_madrid"]
    page = open_page(reduced_motion="reduce")
    assert page.locator("#rm").is_visible()
    assert page.locator("#rm-split circle").count() == 8  # four kinds of ending, a hollow and a solid dot each
    assert page.locator("#rm-last circle:not(.hit)").count() == len(rm["clubs"])
    verdict = page.text_content("#rm-verdict")
    h1, h2, n = rm["halves"][0], rm["halves"][1], rm["normal_time"]
    assert f"{h1['won']} of {h1['ties']} ties won when {h1['expected']:.1f} were expected, then {h2['won']} of {h2['ties']} when {h2['expected']:.1f} were" in verdict
    assert f"ahead of it in {rm['seasons_above']} of {rm['seasons']} seasons" in verdict
    assert f"they won all {n['won_extra']['actual']}" in verdict and f"lost only {n['lost_normal']['actual']} ties in normal time" in verdict
    assert f"error per tie {rm['forecast']['without']:.2f} down to {rm['forecast']['with']:.2f}" in verdict


def test_real_madrid_dot_and_rows_explain_themselves(open_page, data):
    rm = data["real_madrid"]
    page = open_page(reduced_motion="reduce")
    page.locator("#rm-last").scroll_into_view_if_needed()
    page.wait_for_timeout(150)  # scrolling (correctly) hides tooltips
    tip = page.locator("#tip")
    page.locator("#rm-last circle.hit").last.hover()  # Real Madrid is drawn last, on top
    real = next(c for c in rm["clubs"] if c["club"] == "Real Madrid")
    assert "on" in tip.get_attribute("class")
    assert "Real Madrid" in tip.text_content() and f"First seven seasons ({real['ties_first']} ties)" in tip.text_content()
    page.mouse.move(5, 300)
    page.locator("#rm-split rect.hit").first.hover()
    n = rm["normal_time"]["won_normal"]
    assert f"Won {n['actual']} ties in normal time; the model expected {n['expected']:.1f}" in tip.text_content()


def test_without_the_analysis_the_page_keeps_its_short_explanation(open_page, data):
    import json
    without = json.dumps({**data, "real_madrid": None})
    page = open_page(reduced_motion="reduce", routes={"**/data.json": lambda route: route.fulfill(body=without, content_type="application/json")})
    assert page.locator("#rm").is_hidden()
    assert "part of Real Madrid's" in page.text_content("#rm-lead")
    assert page.locator("#rm-split circle").count() == 0 and page.locator("#rm-last circle").count() == 0


# ---------- printing ----------

def test_printout_shows_every_section_in_final_form(open_page, browser_name, data):
    only_in(browser_name, "chromium")  # only Chromium can print to PDF headless
    page = open_page(color_scheme="dark")
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")  # what a real print does first
    page.emulate_media(media="print")
    pdf = page.pdf(format="A4")
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    assert len(pdf) < 3_000_000
    pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages]
    text = "\n".join(pages)
    assert "LUCK?" in text.upper()
    assert not re.search(r"(?<![\d.])00%", text), "a rolling number caught mid-roll"
    assert f"{round(data['headline']['underdog'] * 100)}%" in text
    assert str(len(data["ties"]) - underdog_count(data)) in text  # the finished machine's scoreboard
    assert all(len(p.strip()) > 40 for p in pages), "a blank page"
