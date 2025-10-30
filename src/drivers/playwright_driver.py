from __future__ import annotations
from flask import Flask, request, jsonify, Response
from playwright.sync_api import sync_playwright, Page, BrowserContext
import json
import os


app = Flask(__name__)

_pw = None
_browser = None
_context: BrowserContext | None = None
_page: Page | None = None


def to_interactables(a11y: dict) -> list[dict]:
    out: list[dict] = []

    def walk(node: dict):
        role = node.get('role')
        name = node.get('name') or ''
        if role in ["button", "textbox", "combobox", "link", "menuitem", "checkbox", "radio"]:
            out.append({
                'role': role,
                'label': name,
                'selector': f"role={role}[name=\"{name}\"]",
            })
        for c in node.get('children', []) or []:
            walk(c)

    walk(a11y)
    return out


@app.post('/init')
def init_route():
    global _pw, _browser, _context, _page
    data = request.get_json(force=True)
    app_name = data.get('app')
    cookies_path = data.get('cookiesPath')
    if _pw is None:
        _pw = sync_playwright().start()
        # Launch the system Chrome to satisfy strict OAuth checks
        _browser = _pw.chromium.launch(channel="chrome", headless=False)
    _context = _browser.new_context()
    if cookies_path and os.path.exists(cookies_path):
        cookies = json.loads(open(cookies_path, 'r', encoding='utf-8').read())
        _context.add_cookies(cookies)
    _page = _context.new_page()
    start_url = 'https://linear.app/' if app_name == 'linear' else 'https://www.notion.so/'
    _page.goto(start_url, wait_until='load')
    return jsonify({ 'ok': True, 'startURL': start_url })


@app.post('/observe')
def observe_route():
    assert _page is not None
    url = _page.url
    a11y = _page.accessibility.snapshot(interesting_only=True)
    interactables = to_interactables(a11y or {})
    hint = _page.evaluate("""
      () => {
        const btns = Array.from(document.querySelectorAll('button')).map(b => b.innerText.toLowerCase());
        return btns.find(t => /create|new|filter|add/.test(t)) || '';
      }
    """)
    return jsonify({ 'url': url, 'a11y': a11y, 'interactables': interactables, 'hint': hint })


@app.get('/screenshot')
def screenshot_route():
    assert _page is not None
    buf = _page.screenshot(full_page=True)
    return Response(buf, mimetype='image/png')


@app.post('/act')
def act_route():
    assert _page is not None
    data = request.get_json(force=True) or {}
    try:
        t = data.get('type')
        if t == 'click' and data.get('selector'):
            _page.locator(data['selector']).first.click()
            _page.wait_for_timeout(400)
        elif t == 'scroll':
            delta = data.get('delta', 600)
            _page.mouse.wheel(0, delta)
            _page.wait_for_timeout(200)
        elif t == 'type' and data.get('selector') and data.get('text') is not None:
            _page.locator(data['selector']).fill(str(data['text']))
            _page.wait_for_timeout(200)
        return jsonify({ 'ok': True })
    except Exception as e:
        return jsonify({ 'ok': False, 'error': str(e) }), 500


def main():
    app.run(host='127.0.0.1', port=3999)


if __name__ == '__main__':
    main()

