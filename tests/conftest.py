"""Shared setup for the test suite.

Pipeline and data tests import the code in src/ directly. Browser tests serve site/ on a
free local port and drive it with Playwright; pytest-playwright adds the --browser option
(chromium, firefox, webkit) and the `browser` fixture.
"""

import functools
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

needs_raw_data = pytest.mark.skipif(not (ROOT / "data" / "raw" / "leagues").exists(),
                                    reason="needs data/raw: run scripts/download_data.py first")


needs_transfermarkt = pytest.mark.skipif(not (ROOT / "data" / "raw" / "transfermarkt" / "game_lineups.csv.gz").exists(),
                                         reason="needs data/raw/transfermarkt: run scripts/download_data.py --transfermarkt first")


@pytest.fixture(scope="session")
def data():
    return json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def site_url():
    handler = functools.partial(_QuietHandler, directory=str(ROOT / "site"))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.fixture
def open_page(browser, site_url):
    """open_page(path="", width=1280, **context options) -> a page with the data drawn.

    Every page fails its test on any JavaScript error or console error, while the test is running. Once the test
    is over and the browser is being closed, a request still in flight is aborted and the page logs that
    (it reports the failed data.json fetch with console.error): that says nothing about the page, so errors
    that arrive after this point are not counted. This showed up as a one-off Firefox error in CI."""
    contexts, errors, closing = [], [], []

    def opener(path="", width=1280, height=900, wait=True, allow_errors=False, routes=None, init_script=None, **options):
        context = browser.new_context(viewport={"width": width, "height": height}, **options)
        contexts.append(context)
        page = context.new_page()
        if not allow_errors:
            page.on("pageerror", lambda error: None if closing else errors.append(f"page error: {error}"))
            # A web font still downloading when a test ends is aborted as the browser closes, and Firefox logs
            # that as an error. It says nothing about the page, so it isn't one of the errors a test fails on.
            page.on("console", lambda msg: errors.append(f"console {msg.type}: {msg.text}")
                    if msg.type == "error" and "downloadable font" not in msg.text and not closing else None)
        for pattern, handler in (routes or {}).items():
            page.route(pattern, handler)
        if init_script:  # runs in the page before any of its own scripts
            page.add_init_script(init_script)
        page.goto(site_url + path)
        if wait:
            page.wait_for_function("document.querySelectorAll('.strip-bar').length > 0", timeout=15000)
        return page

    yield opener
    closing.append(True)  # from here on, an aborted request is not a page error
    for context in contexts:
        context.close()
    assert not errors, "\n".join(errors)
