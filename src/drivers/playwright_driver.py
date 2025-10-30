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
    start_url = data.get('url')
    cookies_path = data.get('cookiesPath')
    
    print(f"[DEBUG] App: {app_name}")
    print(f"[DEBUG] URL: {start_url}")
    print(f"[DEBUG] Received cookiesPath: {cookies_path}")
    print(f"[DEBUG] File exists: {os.path.exists(cookies_path) if cookies_path else 'N/A'}")
    
    if not start_url:
        return jsonify({'ok': False, 'error': 'URL is required'}), 400
    
    if _pw is None:
        _pw = sync_playwright().start()
    
    # Use persistent context (same as record_cookies.py) to preserve all browser state
    from pathlib import Path
    user_dir = Path('chrome-user')
    user_dir.mkdir(exist_ok=True)
    
    print(f"[DEBUG] Using persistent context with user_data_dir: {user_dir}")
    _context = _pw.chromium.launch_persistent_context(
        user_data_dir=str(user_dir),
        channel="chrome",
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    _page = _context.new_page()
    
    print(f"[DEBUG] Navigating to {start_url}...")
    _page.goto(start_url, wait_until='load')
    _page.wait_for_timeout(1000)
    
    print(f"[DEBUG] Final URL: {_page.url}")
    title = _page.title()
    print(f"[DEBUG] Page title: {title}")
    
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
    
    # Capture error messages, alerts, and validation messages
    error_messages = _page.evaluate("""
      () => {
        const errors = [];
        
        // Method 1: Check common error selectors
        const errorSelectors = [
          '[role="alert"]',
          '.error', '.error-message', '.validation-error',
          '[class*="error" i]', '[class*="Error"]',
          '[data-error]',
          '.text-red-500', '.text-red-600', '.text-danger',
          '.alert', '.alert-danger', '.alert-error',
          '[aria-invalid="true"]',
          '.form-error', '.field-error',
          '[class*="warning" i]',
          'span[style*="color: rgb(255"]', 'span[style*="color: red"]',
          'div[style*="color: rgb(255"]', 'div[style*="color: red"]'
        ];
        
        for (const selector of errorSelectors) {
          try {
            const elements = document.querySelectorAll(selector);
            elements.forEach(el => {
              const text = el.textContent?.trim();
              if (text && text.length > 0 && text.length < 500) {
                errors.push(text);
              }
            });
          } catch(e) {}
        }
        
        // Method 2: Look for text near invalid inputs
        const invalidInputs = document.querySelectorAll('input[aria-invalid="true"], input.error');
        invalidInputs.forEach(input => {
          const parent = input.closest('div');
          if (parent) {
            // Check siblings and children for error messages
            const errorTexts = parent.querySelectorAll('span, div, p');
            errorTexts.forEach(el => {
              const text = el.textContent?.trim();
              const style = window.getComputedStyle(el);
              // Check if text is red or looks like an error
              if (text && (
                style.color.includes('255, 0') || 
                style.color.includes('red') ||
                text.toLowerCase().includes('already taken') ||
                text.toLowerCase().includes('invalid') ||
                text.toLowerCase().includes('required') ||
                text.toLowerCase().includes('error')
              )) {
                errors.push(text);
              }
            });
          }
        });
        
        // Method 3: Search all page text for common error keywords
        const allText = document.querySelectorAll('span, div, p, label');
        allText.forEach(el => {
          const text = el.textContent?.trim();
          const style = window.getComputedStyle(el);
          // Check for red colored text with error keywords
          if (text && text.length < 500 && text.length > 5 &&
              (style.color.includes('255, 0') || style.color.includes('rgb(255') || style.color.includes('red')) &&
              (text.toLowerCase().includes('taken') || 
               text.toLowerCase().includes('already exists') ||
               text.toLowerCase().includes('invalid') ||
               text.toLowerCase().includes('error') ||
               text.toLowerCase().includes('failed'))) {
            errors.push(text);
          }
        });
        
        // Remove duplicates and filter out empty/too long messages
        const unique = [...new Set(errors)].filter(e => e.length > 0 && e.length < 500);
        return unique;
      }
    """)
    
    return jsonify({ 
        'url': url, 
        'a11y': a11y, 
        'interactables': interactables, 
        'hint': hint,
        'errors': error_messages
    })


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
    app.run(host='127.0.0.1', port=3999, threaded=False)


if __name__ == '__main__':
    main()

