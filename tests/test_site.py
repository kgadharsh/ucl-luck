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
    """At every scroll position the nav marks the last section whose top has passed 40% down the screen.

    The nav catches up on the next animation frame after a scroll, and a busy runner can delay that well
    past a fixed wait: this test failed in WebKit on CI, on main, with a fixed 60 ms. A wrong highlight
    stays wrong, so each position gets up to a second to settle before it counts as a mismatch."""
    page = open_page(reduced_motion="reduce")
    mismatches = page.evaluate("""async () => {
      const maxScroll = () => document.documentElement.scrollHeight - innerHeight;
      const expected = () => {
        const passed = [...document.querySelectorAll('main > section.card[id]')].filter((s) => !s.hidden && s.getBoundingClientRect().top <= innerHeight * 0.4);
        return scrollY >= maxScroll() - 2 ? 'live' : passed.length ? passed[passed.length - 1].id : null;
      };
      const current = () => document.querySelector('nav a[aria-current]')?.hash.slice(1) ?? null;
      let bad = 0;
      for (let y = 0; y <= maxScroll(); y += 350) {
        window.scrollTo(0, y);
        let settled = false;
        for (let waited = 0; waited < 1000 && !settled; waited += 25) {
          await new Promise((r) => setTimeout(r, 25));
          settled = current() === expected();
        }
        if (!settled) bad++;
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


def test_comeback_says_why_past_ties_differ_from_the_model_whichever_leg_is_at_home(open_page):
    """The past-ties bar pools every strength, so it can sit far from the model's number. Say why, both ways round."""
    page = open_page(reduced_motion="reduce")  # opens on a 0-2 first leg away
    away = page.text_content("#cb-text")
    assert "hosting the second leg were usually the stronger" in away and "“Stronger”" in away
    page.click(".cb-controls .seg [data-venue='home']")
    page.select_option("#cb-us", "1")
    page.select_option("#cb-them", "0")
    home = page.text_content("#cb-text")
    assert "that hosted the first leg were usually the weaker" in home and "“Weaker”" in home
    words = page.text_content("#comeback").lower()
    assert "real ties" not in words and "95%" not in words  # "Real" reads as Real Madrid on this page


@pytest.mark.parametrize("system", ["light", "dark"])
def test_the_comeback_shading_gets_stronger_with_the_chance_in_either_theme(open_page, system):
    """More ink for a likelier result: dark squares on the light page, light squares on the dark one."""
    page = open_page(color_scheme=system, reduced_motion="reduce")
    shade = page.evaluate("""() => [...document.querySelectorAll('#cb-heat rect.cell')].map((r) =>
      r.getAttribute('fill').match(/\\d+/g).map(Number).reduce((a, b) => a + b))""")
    unlikely, likely = shade[4], shade[20]  # first row, last column / last row, first column
    assert (likely < unlikely) == (system == "light")
    keys = page.evaluate("[...document.querySelectorAll('#cb-heat rect.key')].map((r) => r.getAttribute('fill'))")
    assert len(keys) == 5 and len(set(keys)) == 5  # five distinct shades, from unlikely to likely
    assert {"Unlikely", "Likely"} <= set(page.evaluate("[...document.querySelectorAll('#cb-heat text')].map((t) => t.textContent)"))


def test_calibration_view_switch_leaves_the_comeback_meter_alone(open_page):
    page = open_page(reduced_motion="reduce")
    venue = lambda: page.evaluate("[...document.querySelectorAll('.cb-controls .seg button')].map((b) => b.getAttribute('aria-pressed')).join()")
    before = venue()
    page.click(".cal-view [data-view='gap']")
    assert venue() == before
    assert page.locator(".cal-view [data-view='gap']").get_attribute("aria-pressed") == "true"


def test_calibration_opens_on_the_whole_picture_and_can_zoom_in(open_page):
    """The heading asks "when it says 60%, does it happen 60% of the time?" and the diagonal answers it."""
    page = open_page(reduced_motion="reduce")
    assert page.locator(".cal-view [data-view='full']").get_attribute("aria-pressed") == "true"
    assert page.locator(".cal-view button").first.get_attribute("data-view") == "full"
    texts = lambda: page.evaluate("[...document.querySelectorAll('#cal-chart text')].map((t) => t.textContent).join('|')")
    assert "honest" in texts().lower() and "How often the home team actually won" in texts()
    assert "laid flat" not in page.text_content("#cal-note")
    page.click(".cal-view [data-view='gap']")
    assert "How far off" in texts() and "laid flat" in page.text_content("#cal-note")
    page.click(".cal-view [data-view='full']")
    assert "How often the home team actually won" in texts()


# ---------- the lottery, the wildest seasons, the glossary ----------

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


def shown_chance(x):
    """How the page writes a chance (never rounds a near-certainty to 100% or a long shot to 0%)."""
    if 0.995 < x < 1:
        return ">99%"
    if 0 < x < 0.005:
        return "<1%"
    return f"{x * 100:.0f}%"


def test_the_lottery_section_gives_the_exact_odds_for_a_typical_favourite(open_page, data):
    """Nothing to drag: three fixed numbers and a sentence, all from the typical favourite's chance."""
    p = data["headline"]["favourite_expected"]
    page = open_page(reduced_motion="reduce")
    assert page.locator("#skill input").count() == 0
    tiles = page.evaluate("[...document.querySelectorAll('#sk-stats .sk-stat')].map((t) => [t.querySelector('b').textContent, t.querySelector('span').textContent])")
    assert [label for _, label in tiles] == ["after 1 tie", "after 10 ties", "after 30 ties"]
    assert [value for value, _ in tiles] == [shown_chance(exact_standings(n, p)[2]) for n in (1, 10, 30)]  # more losses than wins
    sub = page.text_content("#sk-sub")
    assert f"{p:.0%} chance of winning a tie" in sub and f"1 time in {round(1 / (1 - p))}" in sub
    text = page.text_content("#sk-text")
    assert f"{shown_chance(p ** 4)} for four and {shown_chance(p ** 5)} for five" in text and "every" in text


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
    assert page.locator("#rm-last circle:not(.hit)").count() == 4  # two halves, a hollow and a solid dot each
    verdict = page.text_content("#rm-verdict")
    h1, h2, n = rm["halves"][0], rm["halves"][1], rm["normal_time"]
    assert f"{h1['won']} of {h1['ties']} ties won when {h1['expected']:.1f} were expected, then {h2['won']} of {h2['ties']} when {h2['expected']:.1f} were" in verdict
    assert f"ahead of it in {rm['seasons_above']} of {rm['seasons']} seasons" in verdict
    assert f"they won all {n['won_extra']['actual']}" in verdict and f"lost only {n['lost_normal']['actual']} ties in normal time" in verdict
    assert f"average miss per tie {rm['forecast']['without']:.2f} down to {rm['forecast']['with']:.2f}" in verdict


def test_did_it_last_uses_plain_words_and_only_says_real_madrid_stands_alone_when_it_does(open_page, data):
    """No luck-units or correlations on the page. "Only club to do it in both halves" follows the data."""
    import json
    rm = data["real_madrid"]
    page = open_page(reduced_motion="reduce")
    text = page.text_content("#rm")
    assert "luck-unit" not in text and "correlate" not in text
    others = [c for c in rm["clubs"] if c["club"] != rm["club"]]
    real = next(c for c in rm["clubs"] if c["club"] == rm["club"])
    wide = lambda c: c["first"] > 1.5 and c["second"] > 1.5  # a wide margin, in both halves
    alone = wide(real) and not any(wide(c) for c in others)
    assert alone == (f"the only one of the {len(rm['clubs'])} clubs" in page.text_content("#rm-last-note")), "the note must follow the data"
    assert alone == ("No other club did the same in both halves" in page.text_content("#rm-verdict")), "so must the verdict"
    # If a rival matches Real in both halves, the page stops saying Real is the only one.
    rival = {**others[0], "first": real["first"], "second": real["second"]}
    changed = json.dumps({**data, "real_madrid": {**rm, "clubs": [real, rival, *others[1:]]}})
    page = open_page(reduced_motion="reduce", routes={"**/data.json": lambda route: route.fulfill(body=changed, content_type="application/json")})
    assert "the only one" not in page.text_content("#rm-last-note") and "No other club did" not in page.text_content("#rm-verdict")


def test_real_madrid_dot_and_rows_explain_themselves(open_page, data):
    rm = data["real_madrid"]
    page = open_page(reduced_motion="reduce")
    page.locator("#rm summary").click()  # the analysis is folded away until asked for
    page.locator("#rm-last").scroll_into_view_if_needed()
    page.wait_for_timeout(150)  # scrolling (correctly) hides tooltips
    tip = page.locator("#tip")
    page.locator("#rm-last rect.hit").last.hover()
    second = rm["halves"][1]
    assert "on" in tip.get_attribute("class")
    assert "Last seven seasons" in tip.text_content() and f"Won {second['won']} of {second['ties']} ties" in tip.text_content()
    assert f"the model expected {second['expected']:.1f}" in tip.text_content()
    page.mouse.move(5, 300)
    page.locator("#rm-split rect.hit").first.hover()
    n = rm["normal_time"]["won_normal"]
    assert f"Won {n['actual']} ties in normal time; the model expected {n['expected']:.1f}" in tip.text_content()


def test_replays_rank_every_season_and_open_the_whats_if_bracket(open_page, data):
    page = open_page(reduced_motion="reduce")
    rows = page.locator("#replays .rp-row")
    assert rows.count() == len(data["replays"]) == len(data["brackets"])
    top = data["replays"][0]
    first = rows.first.text_content()
    assert top["season"] in first and f"Won {top['champion_chance']:.0%} of replays" in first and f"Beats {top['less_surprising']:.0%} for surprise" in first
    favourites_won = sum(r["contenders"][0]["club"] == r["champion"] for r in data["replays"])
    assert f"won in only {favourites_won} of {len(data['replays'])} seasons" in page.text_content("#replays-note")
    # Clicking a season opens it in the What-if bracket.
    last = data["replays"][-1]["season"]
    page.locator(f"#replays .rp-row[data-season='{last}']").click()
    assert page.locator("#bf-season").evaluate("s => s.selectedOptions[0].textContent") == last
    assert last in page.text_content("#bf-bracket") or page.locator("#bf-bracket .bf-pick").count() > 0


def test_without_replay_data_the_section_and_its_link_disappear(open_page, data):
    import json
    without = json.dumps({k: v for k, v in data.items() if k != "replays"})
    page = open_page(reduced_motion="reduce", routes={"**/data.json": lambda route: route.fulfill(body=without, content_type="application/json")})
    assert page.locator("#replays").is_hidden() and page.locator("nav a[href='#replays']").is_hidden()


def test_long_sections_are_folded_away_and_draw_at_full_width_when_opened(open_page):
    """The Real Madrid analysis and the every-score heatmap start closed, with the short answer left in view."""
    page = open_page(reduced_motion="reduce")
    assert page.locator("#rm").get_attribute("open") is None and page.locator("#cb-more").get_attribute("open") is None
    assert "mostly not luck" in page.text_content("#rm-lead")
    assert page.locator("#rm-verdict").is_hidden() and page.locator("#cb-heat").is_hidden()
    page.locator("#rm summary").click()
    page.locator("#cb-more summary").click()
    assert page.locator("#rm-verdict").is_visible() and page.locator("#cb-heat").is_visible()
    # Drawn while closed they would be 280 wide; opening redraws them to fit their box.
    for chart in ("#rm-split", "#rm-last", "#cb-heat"):
        box = page.locator(chart).bounding_box()["width"]
        drawn = float(page.locator(f"{chart} svg").get_attribute("width"))
        assert abs(drawn - box) <= 2 or drawn >= 280 and box < 280, (chart, drawn, box)


def test_the_prediction_ledger_waits_until_ten_matches_are_scored(open_page, data):
    import json
    def with_scored(n):
        live = {**data["live"], "predictions": n, "scored": n, "model_brier": 0.2, "book_brier": 0.19}
        body = json.dumps({**data, "live": live})
        return open_page(reduced_motion="reduce", routes={"**/data.json": lambda route: route.fulfill(body=body, content_type="application/json")})
    assert with_scored(9).locator("#ledger-block").is_hidden()
    page = with_scored(10)
    assert page.locator("#ledger-block").is_visible() and "predictions saved" in page.text_content("#ledger")


def test_without_the_analysis_the_page_keeps_its_short_explanation(open_page, data):
    import json
    without = json.dumps({**data, "real_madrid": None})
    page = open_page(reduced_motion="reduce", routes={"**/data.json": lambda route: route.fulfill(body=without, content_type="application/json")})
    assert page.locator("#rm").is_hidden()
    assert "part of Real Madrid's" in page.text_content("#rm-lead")
    assert page.locator("#rm-split circle").count() == 0 and page.locator("#rm-last circle").count() == 0


def test_the_verdict_reports_the_line_up_check(open_page, data):
    squad = data["real_madrid"]["squad"]
    rotation, managers = squad["rotation"], squad["managers"]
    page = open_page(reduced_motion="reduce")
    verdict = page.text_content("#rm-verdict")
    assert f"{rotation['real']['knockouts']:.0%} of their best eleven's value against {rotation['real']['league']:.0%}" in verdict
    assert f"the other {rotation['others']['clubs']} average {rotation['others']['gap']:+.3f} against Real's {rotation['real']['gap']:+.3f}" in verdict
    assert f"Real are {rotation['real_rank']}th of {rotation['clubs']}" in verdict
    assert f"Ancelotti's {managers['ancelotti_elsewhere']['matches']} matches elsewhere" in verdict
    assert "It isn't the line-ups either" in verdict and "There are no line-ups" not in verdict


def test_without_the_line_up_check_the_verdict_says_why_it_cannot_tell(open_page, data):
    import json
    without = json.dumps({**data, "real_madrid": {**data["real_madrid"], "squad": None}})
    page = open_page(reduced_motion="reduce", routes={"**/data.json": lambda route: route.fulfill(body=without, content_type="application/json")})
    verdict = page.text_content("#rm-verdict")
    assert "There are no line-ups, injuries or bookmaker odds" in verdict and "isn't the line-ups" not in verdict


# ---------- the season forecast ----------

def without_forecast(data):
    import json
    return json.dumps({**data, "forecast": None})


def with_forecast(data, **changes):
    import json
    return json.dumps({**data, "forecast": {**data["forecast"], **changes}})


def serve(body):
    return {"**/data.json": lambda route: route.fulfill(body=body, content_type="application/json")}


def forecast_chance(stage, p):
    """How the table writes a chance: a decimal for a small chance of winning, never 0% or 100% for what isn't."""
    if stage == "win" and 0 < p < 0.1:
        return "<0.1%" if p < 0.0005 else f"{p * 100:.1f}%"
    return shown_chance(p)


def number_in(text):
    return float(re.sub(r"[^0-9.]", "", text))


STAGES = ["top8", "top24", "last16", "quarter", "semi", "final", "win"]


def forecast_rows(page):
    return page.evaluate("""() => [...document.querySelectorAll('#fc-table tbody tr')].map((tr) => ({
      club: tr.dataset.club, name: tr.children[0].textContent, points: tr.querySelector('.fc-pts').textContent,
      cells: [...tr.querySelectorAll('.fc-cell')].map((td) => td.textContent), bars: [...tr.querySelectorAll('.fc-cell')].map((td) => td.style.getPropertyValue('--p'))}))""")


@pytest.fixture
def forecast(data):
    if not data.get("forecast"):
        pytest.skip("no forecast in the data outside the league phase")
    return data["forecast"]


def test_the_forecast_table_shows_the_saved_chances_best_first(open_page, forecast):
    page = open_page(reduced_motion="reduce")
    assert page.locator("#forecast").is_visible() and page.locator("nav a[href='#forecast']").is_visible()
    assert forecast["season"] in page.text_content("#fc-title")
    rows = forecast_rows(page)
    assert len(rows) == 12  # the top of the table; the rest are one click away
    best = sorted(forecast["clubs"], key=lambda c: -c["win"])[:12]
    assert [r["club"] for r in rows] == [c["club"] for c in best]
    for row, club in zip(rows, best):
        assert row["points"] == str(club["points"])
        for stage, text, bar in zip(STAGES, row["cells"], row["bars"]):
            assert text == forecast_chance(stage, club[stage]) or abs(number_in(text) - club[stage] * 100) <= (0.05 if stage == "win" and club[stage] < 0.1 else 0.5) + 1e-9, (club["club"], stage, text)
            assert float(bar) == pytest.approx(club[stage])  # the bar is as long as the chance
    assert [r["cells"][-1] for r in rows[:1]] == [forecast_chance("win", best[0]["win"])]


def test_the_forecast_says_where_it_stands_and_how_it_was_made(open_page, forecast):
    page = open_page(reduced_motion="reduce")
    sub = page.text_content("#fc-sub")
    assert f"{forecast['played']} of the {forecast['matches']} matches" in sub and f"the other {forecast['left']}" in sub
    assert f"{forecast['simulations']:,} times" in sub
    best = max(forecast["clubs"], key=lambda c: c["win"])
    text = page.text_content("#fc-text")
    assert f"wins in {round(best['win'] * 100)}% of the simulated seasons" in text
    top_five = sum(sorted((c["win"] for c in forecast["clubs"]), reverse=True)[:5])
    assert f"the five best clubs together win {round(top_five * 100)}%" in text
    page.click("#fc-how summary")
    how = page.text_content("#fc-how")
    assert "Wikipedia" in how and "CC BY-SA 4.0" in how and "betting advice" in how
    assert page.locator("#fc-how a[href^='https://en.wikipedia.org/wiki/']").count() == 1


def test_a_heading_sorts_the_forecast_by_that_stage(open_page, forecast):
    page = open_page(reduced_motion="reduce")
    sort_state = lambda: page.evaluate("[...document.querySelectorAll('#fc-head th')].map((th) => th.getAttribute('aria-sort'))")
    assert [s for s in sort_state() if s] == ["none"] * 6 + ["descending"]  # the win column leads
    for stage in ("top8", "semi", "win"):
        page.click(f"#fc-head [data-stage='{stage}']")
        order = [r["club"] for r in forecast_rows(page)]
        expected = sorted(forecast["clubs"], key=lambda c: (-c[stage], -c["win"], c["club"]))[:12]
        assert order == [c["club"] for c in expected], stage
        assert sort_state().count("descending") == 1 and sort_state()[2 + STAGES.index(stage)] == "descending"


def test_the_forecast_shows_every_club_on_request(open_page, forecast):
    page = open_page(reduced_motion="reduce")
    more = page.locator("#fc-more")
    assert more.text_content() == f"Show all {len(forecast['clubs'])} clubs"
    more.click()
    assert len(forecast_rows(page)) == len(forecast["clubs"]) and more.text_content() == "Show the top 12"
    page.click("#fc-head [data-stage='top8']")  # sorting keeps the whole table
    assert len(forecast_rows(page)) == len(forecast["clubs"])
    more.click()
    assert len(forecast_rows(page)) == 12


def test_a_short_forecast_has_nothing_more_to_show(open_page, data, forecast):
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, clubs=forecast["clubs"][:10])))
    assert len(forecast_rows(page)) == 10 and page.locator("#fc-more").is_hidden()


def test_a_cell_says_exactly_what_it_means(open_page, forecast):
    page = open_page(reduced_motion="reduce")
    page.evaluate(REVEAL)
    best = max(forecast["clubs"], key=lambda c: c["win"])
    cell = page.locator("#fc-table tbody tr").first.locator(".fc-win")
    cell.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    cell.hover()
    tip = page.locator("#tip").text_content()
    assert f"{best['win'] * 100:.1f}% to win the trophy" in tip and f"{best['points']} points after {best['played']} matches" in tip
    one_in = float(format(1 / best["win"], ".2g"))  # two significant figures, like every "1 in N" on the page
    assert f"(about 1 in {one_in:g})" in tip


def signed_points(v):
    """How the page writes a change in points: one decimal, a real minus sign, no sign on zero."""
    size = f"{abs(v):.1f}"
    return size if float(size) == 0 else f"{'−' if v < 0 else '+'}{size}"


def title_odds_rows(page):
    return page.evaluate("""() => [...document.querySelectorAll('#fc-hist-table tbody tr')].map((tr) =>
      ({club: tr.dataset.club, cells: [...tr.children].map((td) => td.textContent)}))""")


def test_the_title_odds_table_sets_the_first_forecast_beside_the_latest(open_page, data, forecast):
    history = forecast.get("history")
    if not history or len(history["dates"]) < 2:
        pytest.skip("not enough days of forecasts yet")
    page = open_page(reduced_motion="reduce")
    assert page.locator("#fc-history").is_visible()
    win = history["win"]
    lead = sorted(win, key=lambda c: -win[c][-1])[:6]
    rows = title_odds_rows(page)
    assert [r["club"] for r in rows] == lead  # the six likeliest winners today, best first
    for r in rows:
        first, now = win[r["club"]][0], win[r["club"]][-1]
        assert r["cells"][1:] == [forecast_chance("win", first), forecast_chance("win", now), signed_points((now - first) * 100)]
    note = page.text_content("#fc-history-note")
    move = lambda c: win[c][-1] - win[c][0]
    assert ("Not much has changed" in note) == (abs(move(max(win, key=lambda c: abs(move(c))))) < 0.05)
    led_throughout = all(max(win, key=lambda c: win[c][i]) == lead[0] for i in range(len(history["dates"])))
    assert led_throughout == (f"{rows[0]['cells'][0]} have led at every forecast" in note)


def test_the_title_odds_say_so_when_the_favourite_or_the_odds_have_changed(open_page, data, forecast):
    now = sorted(forecast["clubs"], key=lambda c: -c["win"])
    first, second = now[0]["club"], now[1]["club"]
    shifted = {"dates": ["2026-09-07", forecast["as_of"]],
               "win": {c["club"]: [0.30 if c["club"] == second else 0.01, c["win"]] for c in forecast["clubs"]}}  # the second club led at first
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, history=shifted)))
    note = page.text_content("#fc-history-note")
    rows = title_odds_rows(page)
    assert rows[0]["club"] == first and "The odds have moved" in note and "Not much has changed" not in note
    assert "started as the favourites" in note and "have led at every forecast" not in note


def test_the_title_odds_chart_waits_for_a_second_forecast(open_page, data, forecast):
    thin = {"dates": ["2026-11-05"], "win": {c["club"]: [c["win"]] for c in forecast["clubs"]}}
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, history=thin)))
    assert page.locator("#fc-history").is_hidden()


def test_clubs_with_no_history_are_marked_and_explained(open_page, data, forecast):
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, new_clubs=[forecast["clubs"][0]["club"], forecast["clubs"][1]["club"]])))
    assert page.locator("#fc-table tbody tr .fc-star").count() == 2
    note = page.text_content("#fc-new")
    assert note.startswith("* ") and "have no earlier matches" in note and " and " in note
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, new_clubs=[])))
    assert page.locator(".fc-star").count() == 0 and page.locator("#fc-new").is_hidden()


def test_a_forecast_after_the_league_phase_says_so(open_page, data, forecast):
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, left=0, played=forecast["matches"])))
    assert "league phase is over" in page.text_content("#fc-sub")
    assert "Every match" in page.text_content("#fc-how")


@pytest.mark.parametrize("phase, over, next_up", [("playoffs", "the league phase is over", "the play-offs"), ("last16", "the play-offs are over", "the last 16"),
                                                  ("quarter", "the last 16 is over", "the quarter-finals"), ("semi", "the quarter-finals are over", "the semi-finals"),
                                                  ("final", "the semi-finals are over", "the final")])
def test_the_forecast_says_which_part_of_the_season_it_is_playing_out(open_page, data, forecast, phase, over, next_up):
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, left=0, played=forecast["matches"], phase=phase)))
    sub = page.text_content("#fc-sub")
    assert over in sub and f"plays out {next_up}" in sub and "matches of the league phase" not in sub
    page.click("#fc-how summary")
    assert "every leg already played counts" in page.text_content("#fc-how")


def test_a_forecast_after_the_final_names_the_champion(open_page, data, forecast):
    clubs = [{**c, "win": 1.0 if i == 2 else 0.0} for i, c in enumerate(forecast["clubs"])]
    page = open_page(reduced_motion="reduce", routes=serve(with_forecast(data, clubs=clubs, left=0, phase="done")))
    assert "the final has been played" in page.text_content("#fc-sub")
    assert page.text_content("#fc-text").endswith("won the trophy.") and page.locator("#fc-table tbody tr").first.locator(".fc-win").text_content() == "100%"


def test_without_a_forecast_the_section_and_its_link_disappear(open_page, data):
    page = open_page(reduced_motion="reduce", routes=serve(without_forecast(data)))
    assert page.locator("#forecast").is_hidden() and page.locator("nav a[href='#forecast']").is_hidden()
    assert page.locator("#ties-list .tie").count() > 0  # the rest of the page is untouched


def test_the_forecast_explains_its_terms(open_page, forecast):
    page = open_page(reduced_motion="reduce")
    page.evaluate(REVEAL)
    terms = page.locator("#fc-sub .term")
    assert [terms.nth(i).get_attribute("data-term") for i in range(terms.count())] == ["league-phase", "simulation"]
    terms.first.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    terms.first.hover()
    assert "36 clubs each play eight" in page.locator("#tip").text_content()


@pytest.mark.parametrize("width, shown", [(375, ["Club", "Last 16", "SF", "Final", "Win"]), (320, ["Club", "Last 16", "SF", "Final", "Win"]),
                                           (768, ["Club", "Pts", "Top 8", "Top 24", "Last 16", "QF", "SF", "Final", "Win"])])
def test_the_forecast_table_keeps_what_fits_on_a_phone(open_page, forecast, width, shown):
    page = open_page(width=width, reduced_motion="reduce")
    page.evaluate(REVEAL)
    visible = page.evaluate("[...document.querySelectorAll('#fc-head th')].filter((th) => getComputedStyle(th).display !== 'none').map((th) => th.textContent)")
    assert visible == shown if width < 440 else set(shown) <= set(visible)
    box = page.evaluate("(() => { const s = document.querySelector('.fc-scroll'); return [s.scrollWidth, s.clientWidth]; })()")
    assert box[0] <= box[1], f"the table scrolls sideways at {width}px"


# ---------- the luck machine: the ball and its tie ----------

WATCH_READOUT = """document.addEventListener('DOMContentLoaded', () => {
  window.__readouts = [];
  const now = document.getElementById('machine-now'), under = document.getElementById('ms-under'), fav = document.getElementById('ms-fav');
  let last = '';
  const tick = () => {
    if (now.textContent !== last) { last = now.textContent; __readouts.push({ text: last, landed: +under.textContent + +fav.textContent }); }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
});"""


def test_the_machines_text_describes_the_ball_that_is_dropping(open_page, data, browser_name):
    only_in(browser_name, "chromium")  # the drop takes ten seconds: once is enough
    page = open_page(init_script=WATCH_READOUT)
    page.wait_for_function("document.getElementById('machine-now').textContent.startsWith('All')", timeout=60000)
    seen = [r for r in page.evaluate("__readouts") if not r["text"].startswith(("All", "Every"))]
    ties = sorted(data["ties"], key=lambda t: (t["season"], ROUND_ORDER.index(t["round"])))  # the order they are released in
    line = lambda t: (f"{t['season']} · ", f"{round((t['p_a'] if t['winner'] == t['team_a'] else 1 - t['p_a']) * 100)}% chance")
    at = 0
    for r in seen:  # every text is the next tie to be released (or a later one, if several were released within one frame)
        found = next((k for k in range(at, min(at + 40, len(ties))) if r["text"].startswith(line(ties[k])[0]) and r["text"].endswith(line(ties[k])[1])), None)
        assert found is not None, f"{r['text']} is not one of the next ties to drop"
        at = found + 1
    assert len(seen) > 0.25 * len(ties)  # and many get their moment on screen (fewer on a slow machine: several balls can drop within one frame)
    # Described as it is dropped, not as it lands: balls take over a second to fall, so when the first
    # texts appear nothing has landed yet. (Describing the landing ball put them one-to-one.)
    assert [r["landed"] for r in seen[:5]] == [0] * 5


FIND_BALLS = """() => {
  const board = document.getElementById('machine'), tip = document.getElementById('tip');
  const rect = () => board.getBoundingClientRect();
  const move = (x, y) => board.dispatchEvent(new PointerEvent('pointermove', { clientX: Math.round(rect().left + x), clientY: Math.round(rect().top + y), pointerType: 'mouse', bubbles: true }));
  const found = new Map();  // tooltip -> every point whose hover shows it; their middle is the ball's centre
  const r0 = rect();
  for (let y = 0; y < r0.height; y += 2) for (let x = 0; x < r0.width; x += 2) {
    move(x, y);
    if (!(tip.classList.contains('on') && tip.innerText.includes('chance beforehand'))) continue;
    const lines = tip.innerText.split('\\n'), key = lines[0] + ' | ' + lines[1];
    (found.get(key) || found.set(key, { pct: +lines.find((l) => l.includes('chance beforehand')).match(/(\\d+)%/)[1], points: [] }).get(key)).points.push([x, y]);
  }
  const w = board.parentElement.clientWidth, s = Math.min(56, w / 10), x0 = (w - s * 10) / 2;
  const out = { balls: found.size, wrongBin: [], wrongTie: [] };
  for (const [key, { pct, points }] of found) {
    const cx = Math.round(points.reduce((a, p) => a + p[0], 0) / points.length), cy = Math.round(points.reduce((a, p) => a + p[1], 0) / points.length);
    const bin = Math.floor((cx - x0) / s);
    if (!(bin * 10 <= pct && pct <= bin * 10 + 10)) out.wrongBin.push([key, pct, bin]);
    for (const id of ['f-season', 'f-round', 'f-club', 'f-against']) document.getElementById(id).value = '';
    board.scrollIntoView({ block: 'center', behavior: 'instant' });
    board.dispatchEvent(new MouseEvent('click', { clientX: Math.round(rect().left + cx), clientY: Math.round(rect().top + cy), bubbles: true }));
    const [head, beat] = key.split(' | '), season = head.split(', ')[0], winner = beat.split(' beat ')[0], loser = beat.split(' beat ')[1];
    const rows = [...document.querySelectorAll('#ties-list .tie')], through = [...document.querySelectorAll('#ties-list .tie .through')].map((e) => e.textContent);
    if (!(rows.length === 1 && rows[0].innerText.includes(season) && rows[0].innerText.includes(loser) && through.length === 1 && through[0] === winner)) out.wrongTie.push([key, rows.length, through]);
  }
  return out;
}"""


def test_every_ball_is_in_the_right_bin_and_clicks_to_its_own_tie(open_page, data, browser_name):
    only_in(browser_name, "chromium")  # synthetic pointer events over the whole board: once is enough
    page = open_page(reduced_motion="reduce")  # the finished board at once
    page.locator("#machine").scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    result = page.evaluate(FIND_BALLS)
    assert result["balls"] == len(data["ties"])
    assert result["wrongBin"] == [], result["wrongBin"][:3]  # the chance in the tooltip belongs where the ball sits
    assert result["wrongTie"] == [], result["wrongTie"][:3]  # a click opens exactly that tie, with its winner highlighted


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
