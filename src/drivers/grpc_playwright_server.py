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
from .utils import is_trap_element, normalize_label, find_aria_element, click_aria_element, extract_label_from_selector
from .utils.selector_generator import generate_best_selector, extract_short_label
from .utils import cdp_helper as cdp_helper_module
from .utils.cdp_helper import (
    get_cdp_session,
    get_backend_node_id_from_element_info,
    click_by_backend_node_id
)

_pw = None
_browser = None
_context: BrowserContext | None = None
_page: Page | None = None
_cdp_session = None  # CDP session for backend_node_id operations

DEBUG = str(os.environ.get('DEBUG') or '').strip().lower() in ['1', 'true', 'yes', 'on']
# Set DEBUG in cdp_helper module
cdp_helper_module.DEBUG = DEBUG


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
        disabled = node.get('disabled', False)  # Check disabled state from a11y tree
        if role in ["button", "textbox", "combobox", "link", "menuitem", "checkbox", "radio"]:
            if role == "textbox":
                # Check for trap elements (rich text editor helpers)
                if is_trap_element(page_ref, name):
                    return
            # Normalize keyboard-hint suffixes for menu entries (e.g., "G then S")
            label_out = normalize_label(name) if role in ("menuitem", "option") else name
            
            # Extract short label for better selectors
            short_label = extract_short_label(label_out) if len(label_out) > 30 else label_out
            
            # Try to get backend_node_id via CDP (if available)
            backend_node_id = 0
            if _cdp_session:
                try:
                    cdp_backend_id = get_backend_node_id_from_element_info(
                        _cdp_session,
                        role=role,
                        name=label_out,
                        tag='',
                        elem_id='',
                        href=''
                    )
                    if cdp_backend_id:
                        backend_node_id = cdp_backend_id
                except Exception:
                    pass
            
            # Note: a11y tree doesn't have tag/class info, we'll get it from extra_items
            # We'll generate a better selector when we have more info from extra_items
            # For now, use the short label
            out.append({
                'role': role, 
                'label': label_out,  # Keep full label for display
                'selector': f"role={role}[name*=\"{short_label}\"]",  # Use partial match with short label
                'disabled': disabled,
                'tag': '',
                'classes': [],
                'id': '',
                'href': '',
                'type': '',
                'placeholder': '',
                'backend_node_id': backend_node_id
            })
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
            
            # Initialize CDP session for backend_node_id operations
            global _cdp_session
            try:
                _cdp_session = get_cdp_session(_page)
                if _cdp_session:
                    # Enable DOM domain
                    _cdp_session.send("DOM.enable")
                    if DEBUG:
                        print("[CDP] CDP session initialized successfully")
                else:
                    if DEBUG:
                        print("[CDP] Warning: Failed to create CDP session")
            except Exception as e:
                if DEBUG:
                    print(f"[CDP] Error initializing CDP session: {e}")
                _cdp_session = None
            
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
                  function textOf(el) {
                    const aria = el.getAttribute('aria-label') || '';
                    const ph = el.getAttribute('placeholder') || '';
                    const labelledBy = el.getAttribute('aria-labelledby');
                    let labelled = '';
                    if (labelledBy) {
                      try {
                        labelled = labelledBy.split(/\\s+/).map(id => (document.getElementById(id)?.innerText || document.getElementById(id)?.textContent || '')).join(' ').trim();
                      } catch(e) {}
                    }
                    const inner = (el.innerText || el.textContent || '').trim();
                    return (aria || labelled || ph || inner).trim();
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
                  // 1) From open containers: menu/option/button/link
                  for (const root of containers) {
                    if (!visible(root)) continue;
                    const els = root.querySelectorAll('[role="menuitem"], [role="option"], button, a');
                    els.forEach(el => {
                      if (!visible(el)) return;
                      const role = el.getAttribute('role') || (el.tagName.toLowerCase() === 'a' ? 'link' : (el.tagName.toLowerCase() === 'button' ? 'button' : ''));
                      if (!role) return;
                      let name = el.getAttribute('aria-label') || el.innerText || el.textContent || '';
                      name = name.trim().replace(/\\s+/g, ' ');
                      if (!name) return;
                      const disabled = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true';
                      const tag = el.tagName.toLowerCase();
                      const classes = Array.from(el.classList || []);
                      const id = el.id || '';
                      const href = el.getAttribute('href') || '';
                      const type = el.getAttribute('type') || '';
                      const placeholder = el.getAttribute('placeholder') || '';
                      const key = role + '|' + name;
                      if (candidates.has(key)) return;
                      candidates.add(key);
                      results.push({ role, name, disabled, tag, classes, id, href, type, placeholder });
                    });
                  }
                  // 2) Inputs/textareas/contenteditable/comboboxes across the page
                  const inputSelectors = 'input, textarea, [role="textbox"], [contenteditable="true"], [role="combobox"]';
                  for (const r of roots) {
                    try {
                      r.querySelectorAll(inputSelectors).forEach(el => {
                        if (!visible(el)) return;
                        let role = el.getAttribute('role') || '';
                        const tag = el.tagName.toLowerCase();
                        const type = (el.getAttribute('type') || '').toLowerCase();
                        const classes = Array.from(el.classList || []);
                        const id = el.id || '';
                        const href = el.getAttribute('href') || '';
                        const placeholder = el.getAttribute('placeholder') || '';
                        const disabled = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true';
                        if (!role) {
                          if (tag === 'textarea' || el.hasAttribute('contenteditable')) role = 'textbox';
                          else if (tag === 'input') {
                            if (['text','search','email','url','password'].includes(type) || !type) role = 'textbox';
                          }
                        }
                        let name = textOf(el);
                        if (!name) {
                          if (role === 'combobox') name = 'Recipients';
                          else if (type === 'email') name = 'To';
                          else if (type === 'text' && /subject/i.test(id)) name = 'Subject';
                        }
                        if (!role || !name) return;
                        name = name.replace(/\\s+/g, ' ').trim();
                        const key = role + '|' + name;
                        if (candidates.has(key)) return;
                        candidates.add(key);
                        results.push({ role, name, disabled, tag, classes, id, href, type, placeholder });
                      });
                    } catch(e) {}
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
            disabled = it.get('disabled', False)
            tag = it.get('tag', '')
            classes = it.get('classes', [])
            elem_id = it.get('id', '')
            href = it.get('href', '')
            elem_type = it.get('type', '')
            placeholder = it.get('placeholder', '')
            
            if not role or not name:
                continue
            
            # Filter trap elements from extra_items as well
            if role == "textbox" and is_trap_element(_page, name):
                continue
            # Normalize keyboard-hint suffixes for menu/option names
            label_out = normalize_label(name) if role in ("menuitem", "option") else name
            
            # Generate best selector using all available info
            best_selector = generate_best_selector(
                role=role,
                label=label_out,
                tag=tag,
                elem_id=elem_id,
                href=href,
                classes=classes,
                elem_type=elem_type,
                placeholder=placeholder
            )
            
            key = (role, label_out)
            if key in seen:
                continue
            seen.add(key)
            
            # Try to get backend_node_id via CDP
            backend_node_id = 0  # 0 means not available
            if _cdp_session:
                try:
                    cdp_backend_id = get_backend_node_id_from_element_info(
                        _cdp_session,
                        role=role,
                        name=label_out,
                        tag=tag,
                        elem_id=elem_id,
                        href=href
                    )
                    if cdp_backend_id:
                        backend_node_id = cdp_backend_id
                except Exception as e:
                    if DEBUG:
                        print(f"[CDP] Could not get backend_node_id for {role}/{label_out}: {e}")
            
            interactables.append({
                'role': role, 
                'label': label_out,  # Keep full label for LLM context
                'selector': best_selector,  # Use improved selector
                'disabled': disabled,
                'tag': tag,
                'classes': classes,
                'id': elem_id,
                'href': href,
                'type': elem_type,
                'placeholder': placeholder,
                'backend_node_id': backend_node_id
            })

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
            interactables=[driver_pb2.Interactable(
                role=i['role'], 
                label=i['label'], 
                selector=i['selector'], 
                disabled=i.get('disabled', False),
                tag=i.get('tag', ''),
                classes=i.get('classes', []),
                id=i.get('id', ''),
                href=i.get('href', ''),
                type=i.get('type', ''),
                placeholder=i.get('placeholder', ''),
                backend_node_id=i.get('backend_node_id', 0)  # Include backend_node_id
            ) for i in interactables],
            errors=[str(e) for e in (error_messages or [])],
            frames=frames_info,
        )

    def SmartLocate(self, request, context):
        """Intelligently find an element using multiple strategies, optionally with LLM assistance"""
        assert _page is not None
        description = request.description
        failed_selector = request.failed_selector
        use_llm = request.use_llm
        
        if not description:
            return driver_pb2.SmartLocateResponse(ok=False, error='Description is required')
        
        strategies_tried = []
        
        # Strategy 1: Try exact text match
        try:
            if _page.get_by_text(description, exact=True).count() == 1:
                selector = f'text="{description}"'
                return driver_pb2.SmartLocateResponse(ok=True, selector=selector, strategy='exact_text')
        except Exception as e:
            strategies_tried.append(f'exact_text: {e}')
        
        # Strategy 2: Try partial text match
        try:
            if _page.get_by_text(description).count() == 1:
                selector = f'text={description}'
                return driver_pb2.SmartLocateResponse(ok=True, selector=selector, strategy='partial_text')
        except Exception as e:
            strategies_tried.append(f'partial_text: {e}')
        
        # Strategy 3: Try role + name patterns
        for role in ['button', 'link', 'option', 'menuitem', 'textbox']:
            try:
                if _page.get_by_role(role, name=description).count() == 1:
                    selector = f'role={role}[name="{description}"]'
                    return driver_pb2.SmartLocateResponse(ok=True, selector=selector, strategy=f'role_{role}')
            except Exception:
                pass
        
        # Strategy 4: Try finding by attributes (id, placeholder, aria-label)
        for attr in ['id', 'placeholder', 'aria-label']:
            try:
                if _page.locator(f'[{attr}="{description}"]').count() == 1:
                    selector = f'[{attr}="{description}"]'
                    return driver_pb2.SmartLocateResponse(ok=True, selector=selector, strategy=f'attribute_{attr}')
            except Exception:
                pass
        
        # Strategy 5: Use LLM if enabled
        if use_llm:
            try:
                from openai import OpenAI
                client = OpenAI()
                
                # Get page structure
                page_structure = _page.evaluate('''
                    () => {
                        const elements = [];
                        document.querySelectorAll('button, a, input, [role="button"], [role="link"], [role="option"], [role="menuitem"]').forEach((el, idx) => {
                            if (el.offsetParent !== null) {  // visible
                                elements.push({
                                    idx: idx,
                                    tag: el.tagName.toLowerCase(),
                                    text: (el.innerText || el.textContent || '').trim().substring(0, 100),
                                    role: el.getAttribute('role'),
                                    ariaLabel: el.getAttribute('aria-label'),
                                    id: el.id,
                                    classes: Array.from(el.classList).join(' '),
                                    href: el.getAttribute('href')
                                });
                            }
                        });
                        return elements.slice(0, 50);  // Limit to top 50
                    }
                ''')
                
                prompt = f"""You are helping locate an element on a web page.
                
Description of what to find: {description}
Failed selector (if any): {failed_selector}

Available elements on page (showing visible ones):
{json.dumps(page_structure, indent=2)}

Return the INDEX (idx field) of the element that best matches the description.
If multiple elements could match, choose the most likely one.
If no element matches well, return -1.

Respond with ONLY a number (the idx or -1)."""
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                )
                
                idx = int(response.choices[0].message.content.strip())
                if idx >= 0 and idx < len(page_structure):
                    elem = page_structure[idx]
                    # Build a robust selector
                    if elem.get('id'):
                        selector = f'#{elem["id"]}'
                    elif elem.get('role') and elem.get('ariaLabel'):
                        selector = f'role={elem["role"]}[name="{elem["ariaLabel"]}"]'
                    else:
                        # Use nth-match of tag + text
                        selector = f'{elem["tag"]}:has-text("{elem["text"][:30]}")'
                    
                    # Verify selector works
                    if _page.locator(selector).count() > 0:
                        return driver_pb2.SmartLocateResponse(ok=True, selector=selector, strategy='llm_analysis')
            except Exception as e:
                strategies_tried.append(f'llm: {e}')
        
        # All strategies failed
        error_msg = f'Could not locate element. Tried: {"; ".join(strategies_tried)}'
        return driver_pb2.SmartLocateResponse(ok=False, error=error_msg)

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
            # Relaxed handling for ARIA option/menuitem with keyboard-hint names
            if isinstance(selector, str) and (selector.startswith('role=option[name="') or selector.startswith('role=menuitem[name="')):
                m = re.match(r'^role=(option|menuitem)\[name="(.+?)"\]$', selector)
                role_type = m.group(1) if m else ''
                desired_label = m.group(2) if m else ''
                if role_type and desired_label:
                    found_loc = find_aria_element(_page, role_type, desired_label, _page, for_screenshot=True)
                    if found_loc:
                        loc = found_loc
            # Best-effort wait
            try:
                loc.wait_for(state='visible', timeout=3000)
            except Exception:
                pass
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
                # Try CDP click first if backend_node_id is available (most reliable)
                backend_node_id = request.backend_node_id if hasattr(request, 'backend_node_id') else 0
                if backend_node_id and backend_node_id > 0 and _cdp_session:
                    try:
                        if DEBUG:
                            print(f"  [CDP] Attempting click via backend_node_id: {backend_node_id}")
                        success = click_by_backend_node_id(_cdp_session, backend_node_id)
                        if success:
                            (_page if ctx is _page else ctx.page).wait_for_timeout(1000)
                            if DEBUG:
                                print(f"  [CDP] ✓ Click successful via backend_node_id")
                            return driver_pb2.ActResponse(ok=True)
                        else:
                            if DEBUG:
                                print(f"  [CDP] ⚠️  CDP click failed, falling back to selector")
                    except Exception as cdp_err:
                        if DEBUG:
                            print(f"  [CDP] ⚠️  CDP click error: {cdp_err}, falling back to selector")
                
                # Fall back to selector-based click
                last_err = None
                for sel in iter_selectors():
                    try:
                        # Robust handling for ARIA option/menuitem/link selectors (menus, listboxes, dropdowns)
                        if isinstance(sel, str) and (sel.startswith('role=option[name="') or sel.startswith('role=menuitem[name="') or sel.startswith('role=link[name="')):
                            m = re.match(r'^role=(option|menuitem|link)\[name="(.+?)"\]$', sel)
                            role_type = m.group(1) if m else ''
                            desired_label = m.group(2) if m else ''
                            
                            if role_type and desired_label:
                                # Use utility function to handle all the complex ARIA selector logic
                                if click_aria_element(ctx, role_type, desired_label, _page, debug=DEBUG):
                                    return driver_pb2.ActResponse(ok=True)
                            
                            # Fall through to default path if click failed

                        # Default path
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
                
                # All selectors failed - try smart locate as fallback
                if DEBUG:
                    print(f"  [DEBUG] All selectors failed, trying SmartLocate...")
                
                # Extract description from selector (label from role=X[name="Y"])
                description = None
                for sel in iter_selectors():
                    if isinstance(sel, str):
                        description = extract_label_from_selector(sel)
                        if description:
                            break
                
                if description:
                    try:
                        smart_req = driver_pb2.SmartLocateRequest(
                            description=description,
                            failed_selector=request.selector or '',
                            use_llm=True  # Enable LLM fallback
                        )
                        smart_resp = self.SmartLocate(smart_req, context)
                        if smart_resp.ok and smart_resp.selector:
                            if DEBUG:
                                print(f"  [DEBUG] SmartLocate found: {smart_resp.selector} (strategy: {smart_resp.strategy})")
                            # Try the smart selector
                            ctx.locator(smart_resp.selector).first.click(timeout=5000)
                            (_page if ctx is _page else ctx.page).wait_for_timeout(1000)
                            return driver_pb2.ActResponse(ok=True)
                    except Exception as e:
                        if DEBUG:
                            print(f"  [DEBUG] SmartLocate also failed: {e}")
                
                return driver_pb2.ActResponse(ok=False, error=last_err or 'all selectors failed')
            elif t == 'scroll':
                delta = request.delta or 600
                (_page if ctx is _page else ctx.page).mouse.wheel(0, delta)
                (_page if ctx is _page else ctx.page).wait_for_timeout(200)
                return driver_pb2.ActResponse(ok=True)
            elif t == 'type' and request.text:
                # For type actions, we can use backend_node_id to focus the element via CDP
                # then use Playwright's fill for better compatibility
                backend_node_id = request.backend_node_id if hasattr(request, 'backend_node_id') else 0
                if backend_node_id and backend_node_id > 0 and _cdp_session:
                    try:
                        # Try to focus element via CDP, then fill via selector
                        if DEBUG:
                            print(f"  [CDP] Focusing element via backend_node_id: {backend_node_id}")
                        # Focus via CDP
                        push_result = _cdp_session.send("DOM.pushNodesByBackendIdsToFrontend", {
                            "backendNodeIds": [backend_node_id]
                        })
                        if push_result and "nodeIds" in push_result and push_result["nodeIds"]:
                            node_id = push_result["nodeIds"][0]
                            resolve_result = _cdp_session.send("DOM.resolveNode", {"nodeId": node_id})
                            if resolve_result and "object" in resolve_result and "objectId" in resolve_result["object"]:
                                object_id = resolve_result["object"]["objectId"]
                                # Focus the element
                                _cdp_session.send("Runtime.callFunctionOn", {
                                    "objectId": object_id,
                                    "functionDeclaration": "function() { this.focus(); return true; }",
                                    "returnByValue": True
                                })
                                # Now fill via selector (more reliable than CDP fill for complex inputs)
                                for sel in iter_selectors():
                                    try:
                                        loc = ctx.locator(sel).first
                                        loc.fill(str(request.text))
                                        (_page if ctx is _page else ctx.page).wait_for_timeout(500)
                                        return driver_pb2.ActResponse(ok=True)
                                    except Exception:
                                        pass
                    except Exception as cdp_err:
                        if DEBUG:
                            print(f"  [CDP] Focus error: {cdp_err}, using selector-only")
                
                # Fall back to selector-based type
                last_err = None
                for sel in iter_selectors():
                    try:
                        loc = ctx.locator(sel).first
                        loc.fill(str(request.text))
                        # Wait longer after typing to allow autocomplete/dropdown to populate
                        (_page if ctx is _page else ctx.page).wait_for_timeout(500)
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


