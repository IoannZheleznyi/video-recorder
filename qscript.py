"""qscript.py - browser automation scenario recorded to a .webm video.

Public API
----------
PATH_TO_VIDEO_FOLDER      global: folder where videos are saved
CaptureVideo_Magento(...) runs the sample scenario, returns the absolute path
                          of the recorded .webm file (or None on failure)
ShowCallout(...)          shows a yellow text callout over the page

Playwright's video does not capture the OS cursor, so the cursor, the yellow
highlight, the click ripple and the callout are all injected into the page
with context.add_init_script() (they survive page navigations).
"""
import math
import os
import random
import re
import time
from typing import Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

PATH_TO_VIDEO_FOLDER = "./video"

VIEWPORT = {"width": 1280, "height": 720}
HEADLESS = os.environ.get("HEADLESS", "0").strip().lower() in ("1", "true", "yes")
RESULTS_TIMEOUT_S = 60
CHALLENGE_TIMEOUT_S = 180

SEL_SEARCH_BOX = 'textarea[name="q"]'
SEL_SEARCH_BUTTON = 'form button[type="submit"]'
SEL_SEARCH_BUTTON_SCOPED = 'form:has(textarea[name="q"]) button[type="submit"]'
SEL_FIRST_RESULT = (
    'a[data-testid="result-title-a"], article[data-testid="result"] h2 a'
)

_state = {"page": None, "x": 0.0, "y": 0.0, "headless": False}

INIT_SCRIPT = r"""
(() => {
  if (window.__qcInstalled) return;
  window.__qcInstalled = true;

  const SVG_NS = 'http://www.w3.org/2000/svg';
  let x = -100, y = -100;
  try {
    const saved = sessionStorage.getItem('__qc_pos');
    if (saved) { const p = JSON.parse(saved); x = p.x; y = p.y; }
  } catch (e) {}

  let root = null, halo = null, arrow = null;

  function place() {
    if (!root) return;
    halo.style.transform = 'translate(' + (x - 32) + 'px,' + (y - 32) + 'px)';
    // the tip of the arrow is at (2,2) inside the 32x32 svg
    arrow.style.transform = 'translate(' + (x - 2) + 'px,' + (y - 2) + 'px)';
  }

  function build() {
    root = document.createElement('div');
    root.id = '__qc_root';
    root.style.cssText =
      'position:fixed;left:0;top:0;width:100vw;height:100vh;margin:0;padding:0;' +
      'border:0;overflow:hidden;background:none;pointer-events:none;z-index:2147483647;';

    // yellow semi-transparent highlight, radius 32px, centered on the pointer
    halo = document.createElement('div');
    halo.style.cssText =
      'position:absolute;left:0;top:0;width:64px;height:64px;border-radius:50%;' +
      'background:rgba(255,221,0,0.35);pointer-events:none;will-change:transform;';

    // white arrow with a black outline, ~32x32
    arrow = document.createElementNS(SVG_NS, 'svg');
    arrow.setAttribute('width', '32');
    arrow.setAttribute('height', '32');
    arrow.setAttribute('viewBox', '0 0 32 32');
    arrow.style.cssText =
      'position:absolute;left:0;top:0;overflow:visible;pointer-events:none;will-change:transform;';
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', 'M2 2 L2 25 L8 19.5 L12 29 L16.5 27 L12.5 17.8 L20.5 17.8 Z');
    path.setAttribute('fill', '#ffffff');
    path.setAttribute('stroke', '#000000');
    path.setAttribute('stroke-width', '1.6');
    path.setAttribute('stroke-linejoin', 'round');
    arrow.appendChild(path);

    root.appendChild(halo);   // behind
    root.appendChild(arrow);  // on top
    place();
  }

  function attach() {
    const host = document.documentElement;
    if (!host) return false;
    if (!root) build();
    if (!root.isConnected) host.appendChild(root);
    return true;
  }

  if (!attach()) {
    const mo = new MutationObserver(() => { if (attach()) mo.disconnect(); });
    mo.observe(document, { childList: true });
  }
  setInterval(attach, 500);  // re-attach if the page removed our nodes

  window.addEventListener('mousemove', (e) => {
    x = e.clientX; y = e.clientY;
    place();
    try { sessionStorage.setItem('__qc_pos', JSON.stringify({ x: x, y: y })); } catch (err) {}
  }, true);

  // click ripple: grows from the click point to ~cursor width and fades out
  function ripple(cx, cy) {
    if (!attach()) return;
    const r = document.createElement('div');
    r.style.cssText =
      'position:absolute;left:' + (cx - 20) + 'px;top:' + (cy - 20) + 'px;' +
      'width:40px;height:40px;box-sizing:border-box;border-radius:50%;' +
      'border:3px solid rgba(255,120,0,0.95);background:rgba(255,200,0,0.30);' +
      'pointer-events:none;';
    root.insertBefore(r, arrow);  // under the arrow
    const anim = r.animate(
      [{ transform: 'scale(0.1)', opacity: 1 }, { transform: 'scale(1)', opacity: 0 }],
      { duration: 650, easing: 'ease-out' }
    );
    anim.onfinish = () => r.remove();
  }
  window.addEventListener('mousedown', (e) => ripple(e.clientX, e.clientY), true);

  // callout: auto-sized rectangle with text, fades in / out
  window.__qcCallout = (text, bg, color, fadeMs, holdMs) => {
    if (!attach()) return;
    const old = document.getElementById('__qc_callout');
    if (old) old.remove();
    const c = document.createElement('div');
    c.id = '__qc_callout';
    c.textContent = text;
    c.style.cssText =
      'position:absolute;left:50%;bottom:40px;transform:translateX(-50%);' +
      'width:max-content;max-width:80%;box-sizing:border-box;padding:12px 20px;' +
      'border:2px solid #000;border-radius:6px;font:16pt/1.3 Arial,Helvetica,sans-serif;' +
      'text-align:center;opacity:0;pointer-events:none;';
    c.style.background = bg;
    c.style.color = color;
    c.style.transition = 'opacity ' + fadeMs + 'ms ease';
    root.appendChild(c);
    void c.offsetWidth;  // force reflow so the transition starts
    c.style.opacity = '1';
    setTimeout(() => {
      c.style.opacity = '0';
      setTimeout(() => c.remove(), fadeMs + 50);
    }, fadeMs + holdMs);
  };
})();
"""


def ShowCallout(text, bgColor="#FFE600", textColor="#000000", fade=True,
                hold=1.5, page=None):
    """Show a callout (yellow rectangle, black 16pt text) over the page.

    fade: True -> 2 s fade-in and fade-out, False -> no fade,
          a number -> fade duration in milliseconds.
    hold: seconds the callout stays fully visible.
    The call does not block; the callout removes itself.
    """
    page = page or _state["page"]
    if page is None:
        return
    if fade is True:
        fade_ms = 2000
    elif not fade:
        fade_ms = 0
    else:
        fade_ms = int(fade)
    try:
        page.evaluate(
            "([t, b, c, f, h]) => window.__qcCallout && window.__qcCallout(t, b, c, f, h)",
            [str(text), bgColor, textColor, fade_ms, int(hold * 1000)],
        )
    except PlaywrightError:
        pass


def _ease(t):
    """Ease-in-out cubic."""
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


def _glide(page, tx, ty):
    """Move the mouse to (tx, ty) smoothly along a slightly curved path."""
    sx, sy = _state["x"], _state["y"]
    dist = math.hypot(tx - sx, ty - sy)
    if dist < 1:
        return
    duration = min(1.5, max(0.6, dist / 700.0))

    nx, ny = -(ty - sy) / dist, (tx - sx) / dist
    offset = dist * random.uniform(-0.15, 0.15)
    cx = (sx + tx) / 2 + nx * offset
    cy = (sy + ty) / 2 + ny * offset

    start = time.perf_counter()
    while True:
        u = (time.perf_counter() - start) / duration
        if u >= 1:
            break
        t = _ease(u)
        px = (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t * t * tx
        py = (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t * t * ty
        page.mouse.move(px, py)
        _state["x"], _state["y"] = px, py
        time.sleep(0.008)
    page.mouse.move(tx, ty)
    _state["x"], _state["y"] = tx, ty


def _stable_box(locator, tries=20):
    """Bounding box of the element once it stops moving (animations, layout shifts)."""
    previous = None
    box = None
    for _ in range(tries):
        box = locator.bounding_box()
        if box and previous and all(
            abs(box[k] - previous[k]) < 1 for k in ("x", "y", "width", "height")
        ):
            return box
        previous = box
        time.sleep(0.1)
    if not box:
        raise RuntimeError("element has no bounding box")
    return box


def _target_point(locator):
    """A random point inside the element (kept near its left part for wide ones)."""
    locator.scroll_into_view_if_needed(timeout=5000)
    box = _stable_box(locator)
    dx = min(box["width"] * 0.5, random.uniform(30, 120))
    return box["x"] + dx, box["y"] + box["height"] / 2


def _point_hits(locator, x, y):
    """True if the element (or one of its children) is under the point (x, y)."""
    try:
        return bool(locator.evaluate(
            "(el, p) => { const t = document.elementFromPoint(p[0], p[1]);"
            " return !!t && (t === el || el.contains(t)); }",
            [x, y],
        ))
    except PlaywrightError:
        return False


def _move_and_click(page, locator):
    """Glide to the element and click it with the real mouse.

    The layout can shift while the cursor is moving (suggestions, banners,
    fonts loading), so the position is checked with elementFromPoint and the
    cursor is re-aimed until it really is over the element.
    """
    for _ in range(4):
        tx, ty = _target_point(locator)
        _glide(page, tx, ty)
        time.sleep(0.25)
        if _point_hits(locator, _state["x"], _state["y"]):
            break
    page.mouse.down()
    time.sleep(0.09)
    page.mouse.up()


def _search_button(page, timeout_s=10):
    """The visible submit button of the form that contains the search box."""
    deadline = time.monotonic() + timeout_s
    while True:
        for selector in (SEL_SEARCH_BUTTON_SCOPED, SEL_SEARCH_BUTTON):
            items = page.locator(selector)
            for i in range(items.count()):
                item = items.nth(i)
                if item.is_visible():
                    return item
        if time.monotonic() >= deadline:
            return page.locator(SEL_SEARCH_BUTTON).first
        time.sleep(0.3)


def _raise_if_blocked(page):
    """Fail fast when DuckDuckGo answers with its bot-protection error page."""
    try:
        url = page.url
    except PlaywrightError:
        return
    if "static-pages" in url and "error" in url:
        raise RuntimeError(
            "DuckDuckGo blocked the request as automated traffic (%s). "
            "Try again later or from another network." % url
        )


def _search_submitted(page, wait_s):
    """True once the search was submitted (URL has a query or results are shown)."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        _raise_if_blocked(page)
        try:
            if "q=" in page.url or page.locator(SEL_FIRST_RESULT).count() > 0:
                return True
        except PlaywrightError:
            pass
        page.wait_for_timeout(300)
    return False


def _submit_search(page):
    """Click the search button; fall back to other ways if the click missed."""
    button = _search_button(page)
    _move_and_click(page, button)
    if _search_submitted(page, 6):
        return

    print("[qscript] the click did not submit the search, retrying")
    try:
        button.click(timeout=5000)
    except (PlaywrightTimeout, PlaywrightError):
        pass
    if _search_submitted(page, 6):
        return

    print("[qscript] still not submitted, pressing Enter")
    page.locator(SEL_SEARCH_BOX).first.focus()
    page.keyboard.press("Enter")


def _type_like_human(page, text):
    """Type symbol by symbol with random, human-like delays."""
    for ch in text:
        page.keyboard.type(ch)
        delay = random.uniform(0.06, 0.18)
        if ch == " ":
            delay += random.uniform(0.05, 0.15)
        time.sleep(delay)


def _challenge_visible(page):
    """True if DuckDuckGo shows its bot check (CAPTCHA) instead of results."""
    try:
        return bool(page.evaluate(
            "() => !!document.querySelector('.anomaly-modal__modal, form[action*=\"anomaly\"]')"
            " || /bots use DuckDuckGo too|select all squares/i.test("
            "document.body ? document.body.innerText : '')"
        ))
    except PlaywrightError:
        return False


def _wait_for_results(page, timeout_s=RESULTS_TIMEOUT_S):
    """Poll until the first result is visible.

    The search causes a full page navigation, so the JS context of the old page
    is destroyed; errors raised during that moment are swallowed and we retry.
    If DuckDuckGo shows a bot check, a visible browser window waits for the
    person to solve it; headless mode fails with a clear message.
    """
    deadline = time.monotonic() + timeout_s
    warned = False
    while time.monotonic() < deadline:
        _raise_if_blocked(page)
        try:
            page.locator(SEL_FIRST_RESULT).first.wait_for(state="visible", timeout=2000)
            return
        except (PlaywrightTimeout, PlaywrightError):
            pass
        if _challenge_visible(page):
            if _state["headless"]:
                raise RuntimeError(
                    "DuckDuckGo shows a bot check (CAPTCHA) instead of results. "
                    "Run without HEADLESS=1 and solve it in the window, or try later / "
                    "from another network."
                )
            if not warned:
                print("[qscript] DuckDuckGo shows a bot check - solve it in the browser "
                      "window, waiting up to %d s" % CHALLENGE_TIMEOUT_S)
                deadline = max(deadline, time.monotonic() + CHALLENGE_TIMEOUT_S)
                warned = True
        page.wait_for_timeout(300)
    raise RuntimeError("search results did not appear within %d s" % timeout_s)


def _safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name or "").strip(" .")
    return name or "video"


def _launch_browser(p):
    """Start Chromium: with a window by default, headless if HEADLESS=1 or no display."""
    channel = os.environ.get("BROWSER_CHANNEL") or None
    attempts = []
    if not HEADLESS:
        attempts.append((False, channel))
    attempts.append((True, channel or "chromium"))
    attempts.append((True, None))
    last_error = None
    for headless, ch in attempts:
        kwargs = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if ch:
            kwargs["channel"] = ch
        try:
            browser = p.chromium.launch(**kwargs)
        except PlaywrightError as exc:
            last_error = exc
            print("[qscript] cannot start the browser (headless=%s, channel=%s): %s"
                  % (headless, ch, str(exc).splitlines()[0]))
            continue
        _state["headless"] = headless
        return browser
    raise last_error


def _locale(language, country):
    language, country = (language or "").strip(), (country or "").strip()
    if re.fullmatch(r"[A-Za-z]{2}", language):
        if re.fullmatch(r"[A-Za-z]{2}", country):
            return "%s-%s" % (language.lower(), country.upper())
        return language.lower()
    return "en-US"


def _scenario(page, url, company_name, postcode, city, street, house_no):
    page.goto(url, wait_until="domcontentloaded")
    page.locator(SEL_SEARCH_BOX).first.wait_for(state="visible", timeout=30000)

    _state["x"], _state["y"] = 120.0, 120.0
    page.mouse.move(120, 120)
    time.sleep(0.8)

    address = ", ".join(p for p in (
        ("%s %s" % (street, house_no)).strip(),
        ("%s %s" % (postcode, city)).strip(),
    ) if p)
    ShowCallout("%s: %s" % (company_name, address) if address else company_name)

    _move_and_click(page, page.locator(SEL_SEARCH_BOX).first)
    time.sleep(0.5)

    query = "Magento developer in %s" % city if city else "Magento developer"
    _type_like_human(page, query)
    time.sleep(0.6)

    _submit_search(page)

    _wait_for_results(page)
    page.mouse.move(_state["x"], _state["y"])
    time.sleep(1.0)
    ShowCallout("Opening the first result", hold=1.0)

    _move_and_click(page, page.locator(SEL_FIRST_RESULT).first)
    try:
        page.wait_for_load_state("load", timeout=20000)
    except (PlaywrightTimeout, PlaywrightError):
        pass
    time.sleep(1.0)
    page.mouse.move(_state["x"], _state["y"])
    ShowCallout("Done", hold=1.0)
    time.sleep(4.5)


def CaptureVideo_Magento(
    url,
    company_name,
    language,
    country,
    postcode,
    city,
    street,
    house_no,
):
    """Record the scenario to <PATH_TO_VIDEO_FOLDER>/<company_name>.webm.

    All parameters are strings from the CSV row.
    Returns the absolute path to the .webm file, or None on failure.
    """
    page = None
    ok = False
    video_src = None
    try:
        folder = os.path.abspath(PATH_TO_VIDEO_FOLDER)
        os.makedirs(folder, exist_ok=True)
        _state.update(page=None, x=0.0, y=0.0)

        with sync_playwright() as p:
            browser = _launch_browser(p)
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=folder,
                record_video_size=VIEWPORT,
                locale=_locale(language, country),
            )
            try:
                context.add_init_script(INIT_SCRIPT)
                page = context.new_page()
                page.set_default_timeout(30000)
                _state["page"] = page
                _scenario(page, url, company_name, postcode, city, street, house_no)
                ok = True
            except Exception as exc:
                print("[qscript] scenario failed for %r: %s" % (company_name, exc))
                if page is not None:
                    try:
                        shot = os.path.join(
                            folder, "debug_%s.png" % _safe_filename(company_name))
                        page.screenshot(path=shot)
                        print("[qscript] page: %s | %s" % (page.url, page.title()))
                        print("[qscript] page text: %s"
                              % " ".join(page.inner_text("body").split())[:300])
                        print("[qscript] debug screenshot: %s" % shot)
                    except Exception:
                        pass
            finally:
                video = page.video if page is not None else None
                context.close()
                browser.close()
                if video is not None:
                    video_src = video.path()
                _state["page"] = None

        if not video_src or not os.path.exists(str(video_src)):
            return None
        if not ok:
            try:
                os.remove(str(video_src))
            except OSError:
                pass
            return None

        dest = os.path.join(folder, _safe_filename(company_name) + ".webm")
        os.replace(str(video_src), dest)
        return os.path.abspath(dest)
    except Exception as exc:
        print("[qscript] error: %s" % exc)
        return None