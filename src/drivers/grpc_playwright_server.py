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

_pw = None
_browser = None
_context: BrowserContext | None = None
_page: Page | None = None

DEBUG = str(os.environ.get('DEBUG') or '').strip().lower() in ['1', 'true', 'yes', 'on']

# Simple throttle cache for expensive extra_items scan
_last_extra_items_cache = {
    'ts': 0.0,
    'result': {'items': [], 'containerInfo': []},
}


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
            
            # Note: a11y tree doesn't have tag/class info, we'll get it from extra_items
            out.append({
                'role': role, 
                'label': label_out, 
                'selector': f"role={role}[name=\"{label_out}\"]", 
                'disabled': disabled,
                'tag': '',
                'classes': [],
                'id': '',
                'href': '',
                'type': '',
                'placeholder': ''
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
            headless_env = str(os.environ.get('HEADLESS') or '').strip().lower()
            headless_default = True
            headless_flag = headless_default if headless_env == '' else (headless_env in ['1', 'true', 'yes', 'on'])
            _context = _pw.chromium.launch_persistent_context(
                user_data_dir=str(user_dir),
                channel="chrome",
                headless=headless_flag,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            _page = _context.new_page()
            _page.goto(start_url, wait_until='load')
            # Avoid unconditional sleeps; rely on wait_until above
            return driver_pb2.InitResponse(ok=True, start_url=start_url)
        except Exception as e:
            return driver_pb2.InitResponse(ok=False, error=str(e))

    def Observe(self, request, context):
        assert _page is not None
        url = _page.url
        a11y = _page.accessibility.snapshot(interesting_only=True)
        interactables = to_interactables(a11y or {})
        # Throttled extra_items scan: reuse if called within 400ms
        extra_items_result = None
        try:
            now_ts = time.time()
            if now_ts - float(_last_extra_items_cache.get('ts') or 0.0) < 0.4:
                extra_items_result = _last_extra_items_cache.get('result')
            if not extra_items_result:
                extra_items_result = _page.evaluate(
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
                  const containerInfo = [];
                  // 1) From open containers: menu/option/button/link
                  for (const root of containers) {
                    if (!visible(root)) continue;
                    const containerRole = root.getAttribute('role') || root.tagName.toLowerCase();
                    const containerId = root.id || '';
                    const containerClasses = Array.from(root.classList || []).slice(0, 3).join('.');
                    const els = root.querySelectorAll('[role="menuitem"], [role="option"], button, a');
                    const optionCount = Array.from(els).filter(el => {
                      const role = el.getAttribute('role') || (el.tagName.toLowerCase() === 'a' ? 'link' : (el.tagName.toLowerCase() === 'button' ? 'button' : ''));
                      return role === 'option';
                    }).length;
                    containerInfo.push({
                      role: containerRole,
                      id: containerId,
                      classes: containerClasses,
                      totalElements: els.length,
                      optionCount: optionCount
                    });
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
                      const rect = el.getBoundingClientRect();
                      const bbox = { x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) };
                      const inViewport = rect.top >= 0 && rect.left >= 0 && rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) && rect.right <= (window.innerWidth || document.documentElement.clientWidth);
                      const center = { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) };
                      const style = window.getComputedStyle(el);
                      const opacity = parseFloat(style.opacity || '1');
                      const pointerEvents = style.pointerEvents || '';
                      const zIndex = style.zIndex || '';
                      const aria = {
                        selected: el.getAttribute('aria-selected'),
                        checked: el.getAttribute('aria-checked'),
                        expanded: el.getAttribute('aria-expanded'),
                        pressed: el.getAttribute('aria-pressed'),
                        current: el.getAttribute('aria-current'),
                        required: el.getAttribute('aria-required'),
                        invalid: el.getAttribute('aria-invalid'),
                        haspopup: el.getAttribute('aria-haspopup')
                      };
                      let tabindexAttr = el.getAttribute('tabindex');
                      let tabIndexNum = null;
                      if (tabindexAttr !== null && tabindexAttr !== undefined && tabindexAttr !== '') {
                        const n = parseInt(tabindexAttr, 10);
                        if (!Number.isNaN(n)) tabIndexNum = n;
                      }
                      const focus = { tabindex: tabIndexNum, focusable: ((typeof el.tabIndex === 'number' && el.tabIndex >= 0) || (tabIndexNum !== null && tabIndexNum >= 0)), contentEditable: !!el.isContentEditable };
                      const key = role + '|' + name;
                      if (candidates.has(key)) return;
                      candidates.add(key);
                      results.push({ role, name, disabled, tag, classes, id, href, type, placeholder, bbox, inViewport, center, opacity, pointerEvents, zIndex, aria, focus });
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
                        const rect = el.getBoundingClientRect();
                        const bbox = { x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) };
                        const inViewport = rect.top >= 0 && rect.left >= 0 && rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) && rect.right <= (window.innerWidth || document.documentElement.clientWidth);
                        const center = { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) };
                        const style = window.getComputedStyle(el);
                        const opacity = parseFloat(style.opacity || '1');
                        const pointerEvents = style.pointerEvents || '';
                        const zIndex = style.zIndex || '';
                        const aria = {
                          selected: el.getAttribute('aria-selected'),
                          checked: el.getAttribute('aria-checked'),
                          expanded: el.getAttribute('aria-expanded'),
                          pressed: el.getAttribute('aria-pressed'),
                          current: el.getAttribute('aria-current'),
                          required: el.getAttribute('aria-required'),
                          invalid: el.getAttribute('aria-invalid'),
                          haspopup: el.getAttribute('aria-haspopup')
                        };
                        let tabindexAttr = el.getAttribute('tabindex');
                        let tabIndexNum = null;
                        if (tabindexAttr !== null && tabindexAttr !== undefined && tabindexAttr !== '') {
                          const n = parseInt(tabindexAttr, 10);
                          if (!Number.isNaN(n)) tabIndexNum = n;
                        }
                        const focus = { tabindex: tabIndexNum, focusable: ((typeof el.tabIndex === 'number' && el.tabIndex >= 0) || (tabIndexNum !== null && tabIndexNum >= 0)), contentEditable: !!el.isContentEditable };
                        const key = role + '|' + name;
                        if (candidates.has(key)) return;
                        candidates.add(key);
                        results.push({ role, name, disabled, tag, classes, id, href, type, placeholder, bbox, inViewport, center, opacity, pointerEvents, zIndex, aria, focus });
                      });
                    } catch(e) {}
                  }
                  return { items: results, containerInfo: containerInfo };
                }
                """
                )
                _last_extra_items_cache['ts'] = now_ts
                # Ensure dict format
                if isinstance(extra_items_result, dict):
                    _last_extra_items_cache['result'] = extra_items_result
                else:
                    _last_extra_items_cache['result'] = {'items': (extra_items_result or []), 'containerInfo': []}
        except Exception:
            extra_items_result = {'items': [], 'containerInfo': []}
        
        # Extract items and container info
        if isinstance(extra_items_result, dict):
            extra_items = extra_items_result.get('items', [])
            container_info = extra_items_result.get('containerInfo', [])
        else:
            # Fallback for old format
            extra_items = extra_items_result if extra_items_result else []
            container_info = []
        
        # DEBUG: Log container info
        if DEBUG and container_info:
            print(f"[DRIVER DEBUG] Found {len(container_info)} container(s):")
            for ci in container_info:
                print(f"  - role={ci.get('role')}, id='{ci.get('id')}', classes='{ci.get('classes')}', totalElements={ci.get('totalElements')}, optionCount={ci.get('optionCount')}")
        
        # DEBUG: Log all role=option elements from a11y tree
        a11y_options = [item for item in interactables if item.get('role') == 'option']
        if DEBUG and a11y_options:
            print(f"[DRIVER DEBUG] a11y tree found {len(a11y_options)} option(s):")
            for opt in a11y_options:
                print(f"  - role={opt['role']}, label='{opt['label']}', selector='{opt['selector']}'")
        
        seen = {(item['role'], item['label']) for item in interactables}
        skipped_options = []
        added_options = []
        
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
            bbox = it.get('bbox') or {}
            in_viewport = bool(it.get('inViewport'))
            center = it.get('center') or {}
            opacity = it.get('opacity')
            pointer_events = it.get('pointerEvents') or ''
            z_index = it.get('zIndex') or ''
            aria = it.get('aria') or {}
            focus = it.get('focus') or {}
            
            if not role or not name:
                continue
            
            # Filter trap elements from extra_items as well
            if role == "textbox" and is_trap_element(_page, name):
                continue
            # Normalize keyboard-hint suffixes for menu/option names
            label_out = normalize_label(name) if role in ("menuitem", "option") else name
            key = (role, label_out)
            if key in seen:
                if role == 'option':
                    skipped_options.append({'role': role, 'name': name, 'normalized': label_out, 'reason': 'already in seen'})
                continue
            seen.add(key)
            
            if role == 'option':
                added_options.append({'role': role, 'name': name, 'normalized': label_out, 'selector': f'role={role}[name="{label_out}"]'})
            
            # Encode extra metadata as class tokens to avoid proto changes
            try:
                bx = int(bbox.get('x') or 0); by = int(bbox.get('y') or 0); bw = int(bbox.get('width') or 0); bh = int(bbox.get('height') or 0)
            except Exception:
                bx = by = bw = bh = 0
            meta_tokens = [
                f"__bbox_{bx}_{by}_{bw}_{bh}",
                f"__vp_{1 if in_viewport else 0}",
                f"__cx_{int(center.get('x') or 0)}",
                f"__cy_{int(center.get('y') or 0)}",
            ]
            if pointer_events:
                meta_tokens.append(f"__pe_{pointer_events}")
            if isinstance(opacity, (int, float)):
                try:
                    meta_tokens.append(f"__op_{round(float(opacity), 2)}")
                except Exception:
                    pass
            if z_index:
                meta_tokens.append(f"__zi_{z_index}")
            for k in ('selected','checked','expanded','pressed','current','required','invalid','haspopup'):
                v = aria.get(k)
                if v is not None and str(v) != '':
                    meta_tokens.append(f"__aria_{k}_{str(v).lower()}")
            # Focus tokens
            tabindex = focus.get('tabindex')
            if tabindex is not None:
                try:
                    meta_tokens.append(f"__tb_{int(tabindex)}")
                except Exception:
                    pass
            if 'focusable' in focus:
                meta_tokens.append(f"__fc_{1 if focus.get('focusable') else 0}")
            if focus.get('contentEditable'):
                meta_tokens.append("__ce_1")

            # Stable element key
            try:
                import hashlib as _hashlib
                ek_basis = json.dumps({
                    'tag': tag,
                    'id': elem_id,
                    'classes': (classes or [])[:6],
                    'bbox': {'x': bx, 'y': by, 'w': bw, 'h': bh},
                    'role': role,
                    'label': label_out,
                }, separators=(",", ":"), ensure_ascii=False)
                ek = _hashlib.md5(ek_basis.encode('utf-8')).hexdigest()[:12]
                meta_tokens.append(f"__ek_{ek}")
            except Exception:
                pass

            interactables.append({
                'role': role, 
                'label': label_out, 
                'selector': f'role={role}[name="{label_out}"]', 
                'disabled': disabled,
                'tag': tag,
                'classes': classes + meta_tokens,
                'id': elem_id,
                'href': href,
                'type': elem_type,
                'placeholder': placeholder
            })
        
        # DEBUG: Log all role=option elements from extra_items scan
        if DEBUG:
            if extra_items:
                extra_options_raw = [it for it in extra_items if it.get('role') == 'option']
                print(f"[DRIVER DEBUG] extra_items scan found {len(extra_options_raw)} option(s) (before normalization):")
                for opt in extra_options_raw:
                    print(f"  - role={opt.get('role')}, name='{opt.get('name')}'")
            if added_options:
                print(f"[DRIVER DEBUG] Added {len(added_options)} option(s) from extra_items:")
                for opt in added_options:
                    print(f"  - {opt['selector']} (original name: '{opt['name']}', normalized: '{opt['normalized']}')")
            if skipped_options:
                print(f"[DRIVER DEBUG] Skipped {len(skipped_options)} option(s) (deduplication):")
                for opt in skipped_options:
                    print(f"  - role={opt['role']}, name='{opt['name']}', normalized='{opt['normalized']}', reason: {opt['reason']}")
        
        # DEBUG: Log final list of all role=option elements
        final_options = [item for item in interactables if item.get('role') == 'option']
        if DEBUG and final_options:
            print(f"[DRIVER DEBUG] Final list: {len(final_options)} option(s) total:")
            for opt in final_options:
                print(f"  - {opt['selector']}")

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
                placeholder=i.get('placeholder', '')
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
                    model="gpt-4.1",
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
            if t == 'sequence':
                # Execute a short sequence of clicks without another agent round-trip
                if not request.selectors or len(request.selectors) < 2:
                    return driver_pb2.ActResponse(ok=False, error='sequence requires at least two selectors')
                for idx, sel in enumerate(request.selectors):
                    try:
                        # Reuse robust click logic by temporarily setting request.selector
                        # Handle ARIA roles specially as in click path
                        local_last_err = None
                        if isinstance(sel, str) and (sel.startswith('role=option[name="') or sel.startswith('role=menuitem[name="') or sel.startswith('role=link[name="')):
                            m = re.match(r'^role=(option|menuitem|link)\[name="(.+?)"\]$', sel)
                            role_type = m.group(1) if m else ''
                            desired_label = m.group(2) if m else ''
                            if role_type and desired_label:
                                if click_aria_element(ctx, role_type, desired_label, _page, debug=DEBUG):
                                    continue
                        # Default click
                        ctx.locator(sel).first.wait_for(state='visible', timeout=8000)
                        try:
                            ctx.locator(sel).first.scroll_into_view_if_needed(timeout=800)
                        except Exception:
                            pass
                        ctx.locator(sel).first.click(timeout=10000)
                        (_page if ctx is _page else ctx.page).wait_for_timeout(200)
                    except Exception as e:
                        return driver_pb2.ActResponse(ok=False, error=f'sequence step {idx+1} failed: {e}')
                return driver_pb2.ActResponse(ok=True)

            if t == 'click':
                last_err = None
                for sel in iter_selectors():
                    try:
                        # Robust handling for ARIA option/menuitem/link selectors (menus, listboxes, dropdowns)
                        if isinstance(sel, str) and (sel.startswith('role=option[name="') or sel.startswith('role=menuitem[name="') or sel.startswith('role=link[name="')):
                            m = re.match(r'^role=(option|menuitem|link)\[name="(.+?)"\]$', sel)
                            role_type = m.group(1) if m else ''
                            desired_label = m.group(2) if m else ''
                            
                            if DEBUG:
                                from .utils.selector_normalizer import normalize_label
                                normalized = normalize_label(desired_label)
                                print(f"[DRIVER DEBUG] Extracted from selector: role={role_type}, label='{desired_label}' (will normalize to '{normalized}' and try both)")
                            
                            if role_type and desired_label:
                                # Use utility function to handle all the complex ARIA selector logic
                                # click_aria_element will try both normalized and original label
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
                        # Short post-click settle when navigation is not expected
                        (_page if ctx is _page else ctx.page).wait_for_timeout(300)
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
                            (_page if ctx is _page else ctx.page).wait_for_timeout(300)
                            return driver_pb2.ActResponse(ok=True)
                    except Exception as e:
                        if DEBUG:
                            print(f"  [DEBUG] SmartLocate also failed: {e}")
                
                return driver_pb2.ActResponse(ok=False, error=last_err or 'all selectors failed')
            elif t == 'scroll':
                delta = request.delta or 600
                (_page if ctx is _page else ctx.page).mouse.wheel(0, delta)
                (_page if ctx is _page else ctx.page).wait_for_timeout(150)
                return driver_pb2.ActResponse(ok=True)
            elif t == 'type' and request.text:
                last_err = None
                for sel in iter_selectors():
                    try:
                        loc = ctx.locator(sel).first
                        loc.fill(str(request.text))
                        # Short pause to allow autocomplete/dropdown to populate
                        (_page if ctx is _page else ctx.page).wait_for_timeout(300)
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


