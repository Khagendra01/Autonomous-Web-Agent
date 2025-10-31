from __future__ import annotations
from concurrent import futures
import grpc
from playwright.sync_api import sync_playwright, Page, BrowserContext
from pathlib import Path
import os
import re
import time
import json
import sys

# Ensure generated stubs in this directory are importable as top-level modules
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import driver_pb2, driver_pb2_grpc

_pw = None
_browser = None
_context: BrowserContext | None = None
_page: Page | None = None

DEBUG = str(os.environ.get('DEBUG') or '').strip().lower() in ['1', 'true', 'yes', 'on']


def _visible_js() -> str:
    return (
        """
        (el) => {
          const style = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return (
            style &&
            style.visibility !== 'hidden' &&
            style.display !== 'none' &&
            rect.width > 0 && rect.height > 0
          );
        }
        """
    )


def to_interactables(a11y: dict) -> list[dict]:
    out: list[dict] = []
    page_ref = _page

    def walk(node: dict):
        role = node.get('role')
        name = node.get('name') or ''
        if role in ["button", "textbox", "combobox", "link", "menuitem", "checkbox", "radio"]:
            if role == "textbox" and page_ref:
                try:
                    selector = f"role={role}[name=\"{name}\"]"
                    is_trap = page_ref.evaluate(
                        """
                        () => {
                          try {
                            const matches = document.querySelectorAll('*[role="textbox"]');
                            for (const el of matches) {
                              const ariaLabel = el.getAttribute('aria-label') || el.textContent || '';
                              if (ariaLabel.trim() === '%s') {
                                if (el.hasAttribute('data-content-editable-root-tiny-selection-trap')) return true;
                                const trapParent = el.closest('[data-content-editable-root-tiny-selection-trap]');
                                if (trapParent) return true;
                              }
                            }
                            return false;
                          } catch (e) { return false; }
                        }
                        """ % name
                    )
                    if is_trap:
                        return
                except Exception:
                    pass
            out.append({'role': role, 'label': name, 'selector': f"role={role}[name=\"{name}\"]"})
        for c in node.get('children', []) or []:
            walk(c)

    walk(a11y)
    return out


class DriverService(driver_pb2_grpc.DriverServicer):
    def Init(self, request, context):
        global _pw, _browser, _context, _page
        app_name = request.app
        start_url = request.url
        if not start_url:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details('URL is required')
            return driver_pb2.InitResponse(ok=False, error='URL is required')
        try:
            if _pw is None:
                _pw = sync_playwright().start()
            user_dir = Path('chrome-user')
            user_dir.mkdir(exist_ok=True)
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
            _page.goto(start_url, wait_until='load')
            _page.wait_for_timeout(1000)
            return driver_pb2.InitResponse(ok=True, start_url=start_url)
        except Exception as e:
            return driver_pb2.InitResponse(ok=False, error=str(e))

    def Observe(self, request, context):
        assert _page is not None
        url = _page.url
        a11y = _page.accessibility.snapshot(interesting_only=True)
        interactables = to_interactables(a11y or {})
        try:
            extra_items = _page.evaluate(
                """
                () => {
                  function visible(el) {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                  }
                  const results = [];
                  function collectAll(root) {
                    const arr = [root];
                    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                    let node = walker.currentNode;
                    while (node) {
                      const el = node;
                      if (el.shadowRoot) { arr.push(el.shadowRoot); }
                      node = walker.nextNode();
                    }
                    return arr;
                  }
                  const roots = collectAll(document);
                  const containers = [];
                  for (const r of roots) {
                    try {
                      r.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"], [aria-modal="true"], [data-state="open"], div[style*="position: fixed" i]').forEach(el => containers.push(el));
                      r.querySelectorAll('[aria-expanded="true"]').forEach(el => {
                        const popupId = el.getAttribute('aria-controls');
                        if (popupId) {
                          const popup = document.getElementById(popupId);
                          if (popup) containers.push(popup);
                        }
                      });
                    } catch (e) {}
                  }
                  const candidates = new Set();
                  for (const root of containers) {
                    if (!visible(root)) continue;
                    const els = root.querySelectorAll('[role="menuitem"], [role="option"], button, a');
                    els.forEach(el => {
                      if (!visible(el)) return;
                      const role = el.getAttribute('role') || (el.tagName.toLowerCase() === 'a' ? 'link' : (el.tagName.toLowerCase() === 'button' ? 'button' : ''));
                      if (!role) return;
                      const name = (el.getAttribute('aria-label') || el.textContent || '').trim();
                      if (!name) return;
                      const key = role + '|' + name;
                      if (candidates.has(key)) return;
                      candidates.add(key);
                      results.push({ role, name });
                    });
                  }
                  return results;
                }
                """
            )
        except Exception:
            extra_items = []
        seen = {(item['role'], item['label']) for item in interactables}
        for it in extra_items or []:
            role = it.get('role')
            name = it.get('name') or ''
            if not role or not name:
                continue
            key = (role, name)
            if key in seen:
                continue
            seen.add(key)
            interactables.append({'role': role, 'label': name, 'selector': f'role={role}[name="{name}"]'})

        # errors
        error_messages = _page.evaluate(
            """
            () => {
              const errors = [];
              const errorSelectors = [ '[role="alert"]', '.error', '.error-message', '.validation-error', '[class*="error" i]', '[class*="Error"]', '[data-error]', '.text-red-500', '.text-red-600', '.text-danger', '.alert', '.alert-danger', '.alert-error', '[aria-invalid="true"]', '.form-error', '.field-error', '[class*="warning" i]' ];
              for (const selector of errorSelectors) {
                try {
                  const elements = document.querySelectorAll(selector);
                  elements.forEach(el => {
                    const text = el.textContent?.trim();
                    if (text && text.length > 0 && text.length < 500) { errors.push(text); }
                  });
                } catch(e) {}
              }
              const unique = [...new Set(errors)].filter(e => e.length > 0 && e.length < 500);
              return unique;
            }
            """
        )

        frames_info = []
        try:
            frames_info = [
                driver_pb2.FrameInfo(index=i, name=(f.name or ''), url=(f.url or ''))
                for i, f in enumerate(_page.frames)
            ]
        except Exception:
            pass

        return driver_pb2.ObserveResponse(
            url=url,
            interactables=[driver_pb2.Interactable(role=i['role'], label=i['label'], selector=i['selector']) for i in interactables],
            errors=[str(e) for e in (error_messages or [])],
            frames=frames_info,
        )

    def Screenshot(self, request, context):
        assert _page is not None
        buf = _page.screenshot(full_page=True)
        return driver_pb2.ScreenshotResponse(image_png=buf)

    def ScreenshotRegion(self, request, context):
        assert _page is not None
        selector = request.selector
        margin = int(request.margin or 24)
        if not selector:
            return driver_pb2.ScreenshotResponse(error='selector is required')
        try:
            loc = _page.locator(selector).first
            loc.wait_for(state='visible', timeout=5000)
            try:
                loc.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass
            box = loc.bounding_box(timeout=2000)
            if not box:
                return driver_pb2.ScreenshotResponse(error='failed to get bounding box')
            x = max(0, box['x'] - margin)
            y = max(0, box['y'] - margin)
            w = box['width'] + margin * 2
            h = box['height'] + margin * 2
            vp = _page.viewport_size or { 'width': int(x + w), 'height': int(y + h) }
            max_w = max(1, vp['width'] - x)
            max_h = max(1, vp['height'] - y)
            w = max(1, min(w, max_w))
            h = max(1, min(h, max_h))
            buf = _page.screenshot(clip={'x': x, 'y': y, 'width': w, 'height': h})
            return driver_pb2.ScreenshotResponse(image_png=buf)
        except Exception as e:
            return driver_pb2.ScreenshotResponse(error=str(e))

    def Act(self, request, context):
        assert _page is not None
        t = request.type
        frame_index = request.frame
        ctx = _page
        try:
            if isinstance(frame_index, int) and frame_index > 0:
                frames = _page.frames
                if 0 <= frame_index < len(frames):
                    ctx = frames[frame_index]
        except Exception:
            pass

        def iter_selectors():
            if request.selectors:
                for s in request.selectors:
                    yield s
            if request.selector:
                yield request.selector

        try:
            if t == 'click':
                last_err = None
                for sel in iter_selectors():
                    try:
                        ctx.locator(sel).first.wait_for(state='visible', timeout=10000)
                        try:
                            ctx.locator(sel).first.scroll_into_view_if_needed(timeout=1000)
                        except Exception:
                            pass
                        ctx.locator(sel).first.click(timeout=12000)
                        (_page if ctx is _page else ctx.page).wait_for_timeout(1000)
                        return driver_pb2.ActResponse(ok=True)
                    except Exception as e:
                        last_err = str(e)
                return driver_pb2.ActResponse(ok=False, error=last_err or 'all selectors failed')
            elif t == 'scroll':
                delta = request.delta or 600
                (_page if ctx is _page else ctx.page).mouse.wheel(0, delta)
                (_page if ctx is _page else ctx.page).wait_for_timeout(200)
                return driver_pb2.ActResponse(ok=True)
            elif t == 'type' and request.text:
                last_err = None
                for sel in iter_selectors():
                    try:
                        loc = ctx.locator(sel).first
                        loc.fill(str(request.text))
                        (_page if ctx is _page else ctx.page).wait_for_timeout(150)
                        return driver_pb2.ActResponse(ok=True)
                    except Exception as e:
                        last_err = str(e)
                return driver_pb2.ActResponse(ok=False, error=last_err or 'type failed')
            elif t == 'hover':
                last_err = None
                for sel in iter_selectors():
                    try:
                        ctx.locator(sel).first.wait_for(state='visible', timeout=5000)
                        ctx.locator(sel).first.hover(timeout=5000)
                        return driver_pb2.ActResponse(ok=True)
                    except Exception as e:
                        last_err = str(e)
                return driver_pb2.ActResponse(ok=False, error=last_err or 'hover failed')
            elif t == 'press':
                keys = request.keys or ''
                if not keys:
                    return driver_pb2.ActResponse(ok=False, error='keys required')
                pg = (_page if ctx is _page else ctx.page)
                pg.keyboard.press(keys)
                pg.wait_for_timeout(100)
                return driver_pb2.ActResponse(ok=True)
            elif t == 'wait_for':
                state = (request.state or 'visible')
                last_err = None
                for sel in iter_selectors():
                    try:
                        ctx.locator(sel).first.wait_for(state=state, timeout=int(request.timeout or 5000))
                        return driver_pb2.ActResponse(ok=True)
                    except Exception as e:
                        last_err = str(e)
                return driver_pb2.ActResponse(ok=False, error=last_err or 'wait_for failed')
            elif t == 'await':
                kind = (request.kind or 'networkidle').lower()
                pg = (_page if ctx is _page else ctx.page)
                if kind == 'networkidle':
                    pg.wait_for_load_state('networkidle', timeout=int(request.timeout or 15000))
                    return driver_pb2.ActResponse(ok=True)
                elif kind == 'timeout':
                    pg.wait_for_timeout(int(request.timeout or 300))
                    return driver_pb2.ActResponse(ok=True)
                else:
                    return driver_pb2.ActResponse(ok=False, error='unknown await kind')
            elif t == 'click_xy':
                x = request.x
                y = request.y
                if x is None or y is None or x == 0 and y == 0:
                    return driver_pb2.ActResponse(ok=False, error='x and y required')
                pg = (_page if ctx is _page else ctx.page)
                pg.mouse.move(float(x), float(y))
                pg.mouse.click(float(x), float(y))
                pg.wait_for_timeout(150)
                return driver_pb2.ActResponse(ok=True)
            elif t == 'assert':
                kind = (request.kind or '').lower()
                if kind == 'text_present':
                    needle = str(request.text or '')
                    content = ctx.evaluate('() => document.body.innerText')
                    if needle and needle.lower() in (content or '').lower():
                        return driver_pb2.ActResponse(ok=True)
                    return driver_pb2.ActResponse(ok=False, error='text not found')
                elif kind == 'url_contains':
                    sub = str(request.substring or '')
                    cur = (_page if ctx is _page else ctx.page).url
                    if sub and sub in cur:
                        return driver_pb2.ActResponse(ok=True)
                    return driver_pb2.ActResponse(ok=False, error='url does not contain substring')
                elif kind == 'element_visible':
                    last_err = None
                    for sel in iter_selectors():
                        try:
                            ctx.locator(sel).first.wait_for(state='visible', timeout=4000)
                            return driver_pb2.ActResponse(ok=True)
                        except Exception as e:
                            last_err = str(e)
                    return driver_pb2.ActResponse(ok=False, error=last_err or 'element not visible')
                else:
                    return driver_pb2.ActResponse(ok=False, error='unknown assert kind')
            else:
                return driver_pb2.ActResponse(ok=False, error='unknown or malformed action')
        except Exception as e:
            return driver_pb2.ActResponse(ok=False, error=str(e))


def serve(blocking: bool = True, host: str = '127.0.0.1', port: int = 50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    driver_pb2_grpc.add_DriverServicer_to_server(DriverService(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    if blocking:
        server.wait_for_termination()
    return server


if __name__ == '__main__':
    serve()


