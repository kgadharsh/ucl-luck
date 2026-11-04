"""The dashboard in real browsers (Chromium, Firefox and WebKit, via Playwright).

Each test pins down something that was broken once: wrong colours after a theme change,
content off-screen on phones, tooltips that stuck, a hover zone bigger than its bar, blank
printouts, a deep link landing in the wrong place, and so on.
"""

import io
import re

import pytest
from pypdf import PdfReader

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
    assert page.locator('[data-fill="real-odds"]').first.text_content() == "11,500"


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
