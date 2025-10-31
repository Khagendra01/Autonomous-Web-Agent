from __future__ import annotations
from flask import Flask, request, jsonify, Response
from playwright.sync_api import sync_playwright, Page, BrowserContext
import re
import json
import os
import time
from pathlib import Path


app = Flask(__name__)

_pw = None
_browser = None
_context: BrowserContext | None = None
_page: Page | None = None

# Debug mode: set DEBUG=1 to save element crops and extra logs during actions
DEBUG = str(os.environ.get('DEBUG') or '').strip().lower() in ['1', 'true', 'yes', 'on']

def _debug_save_locator(locator, prefix: str) -> None:
	if not DEBUG:
		return
	try:
		Path('captures/debug').mkdir(parents=True, exist_ok=True)
		ts = time.strftime('%Y%m%d-%H%M%S')
		path = f"captures/debug/{prefix}-{ts}.png"
		locator.screenshot(path=path)
		print(f"[DEBUG] Saved locator screenshot: {path}")
	except Exception as e:
		print(f"[DEBUG] Failed to save locator screenshot: {e}")


def to_interactables(a11y: dict) -> list[dict]:
	"""Convert accessibility tree to interactables, filtering out trap spans."""
	out: list[dict] = []
	page_ref = _page  # Capture page reference for validation

	def walk(node: dict):
		role = node.get('role')
		name = node.get('name') or ''
		if role in ["button", "textbox", "combobox", "link", "menuitem", "checkbox", "radio"]:
			# For textbox elements, validate the selector doesn't match a trap span
			if role == "textbox" and page_ref:
				try:
					# Check if this selector would match a trap span
					selector = f"role={role}[name=\"{name}\"]"
					# Use evaluate to check if the matched element is a trap
					is_trap = page_ref.evaluate(f"""
						() => {{
							try {{
								const matches = document.querySelectorAll('*[role="textbox"]');
								for (const el of matches) {{
									const ariaLabel = el.getAttribute('aria-label') || el.textContent || '';
									if (ariaLabel.trim() === '{name}') {{
										// Check if this is a trap span or inside one
										if (el.hasAttribute('data-content-editable-root-tiny-selection-trap')) {{
											return true;
										}}
										const trapParent = el.closest('[data-content-editable-root-tiny-selection-trap]');
										if (trapParent) {{
											return true;
										}}
									}}
								}}
								return false;
							}} catch (e) {{
								return false;
							}}
						}}
					""")
					if is_trap:
						# Skip this trap span - we'll add the real contenteditable via discovery
						return
				except Exception:
					# If validation fails, include it anyway (better than missing elements)
					pass
			
			out.append({
				'role': role,
				'label': name,
				'selector': f"role={role}[name=\"{name}\"]",
			})
		for c in node.get('children', []) or []:
			walk(c)

	walk(a11y)
	return out


def _dismiss_overlays(page: Page) -> None:
	"""Best-effort attempt to dismiss common overlays/backdrops/popovers."""
	try:
		# Click common backdrop elements if present
		backdrop_selectors = [
			"[data-animated-popover-backdrop=\"true\"]",
			".modal-backdrop, .MuiBackdrop-root, .ant-drawer-mask, .ant-modal-mask",
			"div[style*=\"pointer-events: auto\"][style*=\"opacity\"]",
		]
		for sel in backdrop_selectors:
			loc = page.locator(sel).first
			if loc.count() > 0 and loc.is_visible():
				try:
					loc.click(force=True, timeout=500)
					page.wait_for_timeout(150)
					break
				except Exception:
					pass
		# Press Escape to close menus/popovers
		page.keyboard.press("Escape")
		page.wait_for_timeout(100)
	except Exception:
		pass


def _robust_click(ctx, selector: str) -> None:
    """Attempt a robust click with fallbacks if intercepted by overlays.

    Special handling: when targeting ARIA option/menuitem entries, ensure the
    parent popup/listbox is open, then match by case-insensitive text.
    """
    # Special path for ARIA option/menuitem clicks generated like: role=option[name="..."]
    if selector.startswith('role=option[name="') or selector.startswith('role=menuitem[name="'):
        # Extract the desired label
        m = re.match(r'^role=(option|menuitem)\[name="(.+?)"\]$', selector)
        desired_label = m.group(2) if m else ''

        # Ensure a popup container is visible; try to open if needed
        try:
            container = ctx.locator('[role="listbox"], [role="menu"], [data-state="open"], [aria-modal="true"]').first
            if container.count() == 0 or not container.is_visible():
                # Try to open an active combobox if present
                try:
                    combo = ctx.locator('[role="combobox"]').filter(has=ctx.locator('[aria-expanded="false"]')).first
                    if combo and (combo.count() > 0):
                        combo.click(timeout=800)
                except Exception:
                    pass
                # Try common keyboard openers
                try:
                    (ctx.page.keyboard if hasattr(ctx, 'page') else ctx.keyboard).press('Alt+ArrowDown')
                except Exception:
                    pass
                page.wait_for_timeout(200)
            # Wait for any container to be visible
            ctx.locator('[role="listbox"], [role="menu"], [data-state="open"], [aria-modal="true"]').first.wait_for(state='visible', timeout=8000)
        except Exception:
            pass

        # Attempt exact, then partial, then regex case-insensitive matches
        candidates = [
            ctx.get_by_role('option', name=desired_label).first,
            ctx.get_by_role('menuitem', name=desired_label).first,
            ctx.locator('[role="option"]', has_text=desired_label).first,
            ctx.locator('[role="menuitem"]', has_text=desired_label).first,
        ]
        try:
            regex = re.compile(re.escape(desired_label), re.IGNORECASE)
            candidates.extend([
                ctx.locator('[role="option"]').filter(has_text=regex).first,
                ctx.locator('[role="menuitem"]').filter(has_text=regex).first,
            ])
        except Exception:
            pass

        # If nothing visible, try typing to filter in focused textbox/combobox
        clicked = False
        for cand in candidates:
            try:
                if cand and cand.count() > 0:
                    try:
                        cand.scroll_into_view_if_needed(timeout=1000)
                    except Exception:
                        pass
                    cand.wait_for(state='visible', timeout=8000)
                    cand.click(timeout=5000)
                    (ctx.page if hasattr(ctx, 'page') else ctx).wait_for_timeout(200)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked and desired_label:
            # Try to filter options by typing the desired label
            try:
                active = ctx.locator('[role="combobox"][aria-expanded="true"], input[role="combobox"], input[aria-autocomplete]')
                el = active.first if active.count() > 0 else None
                if el:
                    try:
                        el.fill(desired_label)
                    except Exception:
                        el.click(timeout=800)
                        (ctx.page.keyboard if hasattr(ctx, 'page') else ctx.keyboard).type(desired_label)
                    (ctx.page if hasattr(ctx, 'page') else ctx).wait_for_timeout(300)
                    # Retry selecting the first matching option
                    opt = ctx.locator('[role="option"]').filter(has_text=re.compile(re.escape(desired_label), re.IGNORECASE)).first
                    opt.wait_for(state='visible', timeout=5000)
                    opt.click(timeout=3000)
                    (ctx.page if hasattr(ctx, 'page') else ctx).wait_for_timeout(200)
                    clicked = True
            except Exception:
                pass

        if clicked:
            # Wait briefly for UI state to reflect the selection (e.g., assignee label updates)
            try:
                pattern = re.compile(re.escape(desired_label), re.IGNORECASE) if desired_label else None
                if pattern:
                    ctx.locator('[role="button"], [aria-label], [role], button, a, span, div, input').filter(has_text=pattern).first.wait_for(state='visible', timeout=2000)
            except Exception:
                pass
            return
        # Fall through to generic path if above failed

    locator = ctx.locator(selector).first
    locator.wait_for(state='visible', timeout=10000)
    try:
        try:
            locator.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass
        _debug_save_locator(locator, f"before-click-{re.sub('[^a-zA-Z0-9_-]+','_',selector)[:60]}")
        locator.click(timeout=12000)
        (ctx.page if hasattr(ctx, 'page') else ctx).wait_for_timeout(200)
        return
    except Exception as e:
        message = str(e)
        # If pointer events are intercepted or similar, try fallbacks
        if 'intercepts pointer events' in message or 'element receives pointer-events' in message or 'Timeout' in message:
            # 1) Dismiss overlays and retry normal click
            _dismiss_overlays(ctx.page if hasattr(ctx, 'page') else ctx)
            try:
                _debug_save_locator(locator, f"retry-click-{re.sub('[^a-zA-Z0-9_-]+','_',selector)[:60]}")
                locator.click(timeout=3000)
                (ctx.page if hasattr(ctx, 'page') else ctx).wait_for_timeout(150)
                return
            except Exception:
                pass
            # 2) Force click (may bypass hit testing)
            try:
                locator.click(force=True, timeout=2000)
                (ctx.page if hasattr(ctx, 'page') else ctx).wait_for_timeout(150)
                return
            except Exception:
                pass
            # 3) JS click
            try:
                ctx.evaluate("el => el.click()", locator.element_handle(timeout=2000))
                (ctx.page if hasattr(ctx, 'page') else ctx).wait_for_timeout(150)
                return
            except Exception:
                pass
            # 4) Click center of bounding box with the mouse
            try:
                box = locator.bounding_box(timeout=2000)
                if box:
                    x = box['x'] + box['width'] / 2
                    y = box['y'] + box['height'] / 2
                    pg = (ctx.page if hasattr(ctx, 'page') else ctx)
                    pg.mouse.move(x, y)
                    pg.mouse.down()
                    pg.mouse.up()
                    pg.wait_for_timeout(150)
                    return
            except Exception:
                pass
        # Re-raise original error if all fallbacks failed
        raise



def _robust_type(ctx, selector: str, text: str) -> None:
	pg = (ctx.page if hasattr(ctx, 'page') else ctx)
	print(f"[DEBUG TYPE] Starting type with selector: {selector}, text: {text}")
	
	# 1) Try target selector directly (don't abort if not visible)
	loc = None
	try:
		loc = ctx.locator(selector).first
		
		_debug_save_locator(loc, f"before-type-{re.sub('[^a-zA-Z0-9_-]+','_',selector)[:60]}")
		
		# CRITICAL FIX: Validate selector doesn't resolve to trap span
		# If it does, find and use the real contenteditable parent
		try:
			el_handle = loc.element_handle(timeout=500)
			if el_handle:
				# Get detailed info about what element we matched
				el_info = ctx.evaluate("""
				  (el) => {
				    if (!el) return null;
				    return {
				      tagName: el.tagName,
				      hasTrapAttr: el.hasAttribute('data-content-editable-root-tiny-selection-trap'),
				      contenteditable: el.getAttribute('contenteditable'),
				      role: el.getAttribute('role'),
				      placeholder: el.getAttribute('placeholder'),
				      ariaLabel: el.getAttribute('aria-label'),
				      textContent: (el.textContent || '').slice(0, 50),
				      hasTrapParent: !!el.closest('[data-content-editable-root-tiny-selection-trap]')
				    };
				  }
				""", el_handle)
				print(f"[DEBUG TYPE] Resolved element info: {json.dumps(el_info, indent=2)}")
				
				is_trap_result = ctx.evaluate("""
				  (el) => {
				    if (!el) return false;
				    // Direct trap check
				    if (el.hasAttribute('data-content-editable-root-tiny-selection-trap')) return true;
				    // Inside trap check
				    if (el.closest('[data-content-editable-root-tiny-selection-trap]')) return true;
				    return false;
				  }
				""", el_handle)
				
				print(f"[DEBUG TYPE] Is trap? {is_trap_result}")
				
				if is_trap_result:
					print(f"[DEBUG TYPE] TRAP DETECTED! Finding real contenteditable...")
					# Find the real contenteditable parent
					ce_info = ctx.evaluate("""
					  (el) => {
						  const trap = el.hasAttribute('data-content-editable-root-tiny-selection-trap') 
						    ? el 
						    : el.closest('[data-content-editable-root-tiny-selection-trap]');
						  if (!trap) return null;
						  const ce = trap.closest('[contenteditable=\"true\"]:not([data-content-editable-void])');
						  if (!ce) return null;
						  return { type: 'ce', tagName: ce.tagName };
						}
					""", el_handle)
					
					print(f"[DEBUG TYPE] CE info: {json.dumps(ce_info)}")
					
					if ce_info and ce_info.get('type') == 'ce':
						# Find the specific contenteditable parent
						try:
							ce_handle = ctx.evaluate_handle("el => el.closest('[contenteditable=\"true\"]:not([data-content-editable-void])')", el_handle)
							if ce_handle:
								loc = ctx.locator('[contenteditable=\"true\"]').filter(has=ce_handle).first
								print(f"[DEBUG TYPE] ✓ Normalized trap to parent contenteditable")
							else:
								loc = ctx.locator('[contenteditable=\"true\"]:not([data-content-editable-void])').first
								print(f"[DEBUG TYPE] ✓ Using fallback contenteditable selector")
						except Exception as e2:
							loc = ctx.locator('[contenteditable=\"true\"]:not([data-content-editable-void])').first
							print(f"[DEBUG TYPE] ✓ Exception fallback: {e2}")
				else:
					print(f"[DEBUG TYPE] Not a trap, using original selector")
		except Exception as e:
			print(f"[DEBUG TYPE] Trap validation failed: {e}")
			import traceback
			traceback.print_exc()
			pass
		
		try:
			# Prefer fill when possible
			loc.fill(str(text))
			pg.wait_for_timeout(150)
			return
		except Exception:
			pass
		try:
			# Focus and type as fallback
			try:
				loc.scroll_into_view_if_needed(timeout=500)
			except Exception:
				pass
			loc.click(timeout=1500)
			pg.wait_for_timeout(100)
			
			# CRITICAL: After clicking, verify focus is on real contenteditable, not trap
			# This must happen before typing
			try:
				active_info = ctx.evaluate("""
				  () => {
				    const active = document.activeElement;
				    if (!active) return { active: null };
				    return {
				      tagName: active.tagName,
				      hasTrapAttr: active.hasAttribute('data-content-editable-root-tiny-selection-trap'),
				      contenteditable: active.getAttribute('contenteditable'),
				      role: active.getAttribute('role'),
				      placeholder: active.getAttribute('placeholder')
				    };
				  }
				""")
				print(f"[DEBUG TYPE] Active element after click: {json.dumps(active_info)}")
				
				fixed = ctx.evaluate("""
				  () => {
				    const active = document.activeElement;
				    if (!active) return false;
				    // Check if focus is on trap
				    const isTrap = active.hasAttribute('data-content-editable-root-tiny-selection-trap');
				    const trapParent = active.closest('[data-content-editable-root-tiny-selection-trap]');
				    if (isTrap || trapParent) {
				      // Find real contenteditable parent
				      const trapEl = isTrap ? active : trapParent;
				      const ce = trapEl.closest('[contenteditable="true"]:not([data-content-editable-void])');
				      if (ce) {
				        // Prefer Notion H1 title
				        const h1 = ce.querySelector('h1[contenteditable="true"]') || ce.closest('h1[contenteditable="true"]');
				        if (h1 && h1.focus) {
				          h1.focus();
				          return true;
				        }
				        if (ce.focus) {
				          ce.focus();
				          return true;
				        }
				      }
				    }
				    // Verify active element is a real editable
				    const isReal = active.getAttribute('contenteditable') === 'true' || 
				                   active.tagName === 'INPUT' || 
				                   active.tagName === 'TEXTAREA';
				    return isReal;
				  }
				""")
				if fixed:
					print(f"[DEBUG TYPE] ✓ Focus redirected successfully")
					pg.wait_for_timeout(100)
				else:
					print(f"[DEBUG TYPE] Focus fix returned false")

				# Removed app-specific handoff logic
			except Exception as e:
				print(f"[DEBUG TYPE] Focus fix failed: {e}")
				import traceback
				traceback.print_exc()
				pass
			
			# Select-all then type to ensure we replace any placeholder/title content
			try:
				pg.keyboard.press('Control+a')
				pg.wait_for_timeout(50)
			except Exception:
				pass
			pg.keyboard.type(str(text))
			pg.wait_for_timeout(150)
			return
		except Exception:
			pass
	except Exception:
		loc = None

	# 2) Try any visible contenteditable element
	try:
		editable = ctx.locator('[contenteditable="true"]').filter(has_text=re.compile(r'.*', re.S)).first
		if editable.count() == 0:
			editable = ctx.locator('[contenteditable="true"]').first
		editable.wait_for(state='visible', timeout=3000)
		editable.click(timeout=1000)
		pg.wait_for_timeout(100)
		pg.keyboard.type(str(text))
		pg.wait_for_timeout(200)
		return
	except Exception:
		pass

	# 3) Last resort: type at caret in document body
	try:
		ctx.locator('body').first.click(timeout=1000)
		pg.wait_for_timeout(100)
		pg.keyboard.type(str(text))
		pg.wait_for_timeout(200)
		return
	except Exception:
		pass

	raise RuntimeError('Failed to type text using generic strategies')


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
# Augment interactables with menu/popover/dialog items that may not appear in the a11y snapshot yet
	extra_items = _page.evaluate("""
  () => {
    function visible(el) {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return (
        style &&
        style.visibility !== 'hidden' &&
        style.display !== 'none' &&
        rect.width > 0 && rect.height > 0
      );
    }
    const results = [];

    // Helper: collect nodes from document and open shadow roots
    function collectAll(root) {
      const arr = [root];
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
      let node = walker.currentNode;
      while (node) {
        const el = node;
        // Include open shadow roots
        if (el.shadowRoot) {
          arr.push(el.shadowRoot);
        }
        node = walker.nextNode();
      }
      return arr;
    }

    const roots = collectAll(document);
    const containers = [];
    for (const r of roots) {
      try {
        r.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"], [aria-modal="true"], [data-state="open"], div[style*="position: fixed" i]').forEach(el => containers.push(el));
        // Also consider expanded popover triggers as containers
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
""")

# Merge extras, dedupe by role+label
	seen = { (item['role'], item['label']) for item in interactables }
	for it in extra_items or []:
		role = it.get('role')
		name = it.get('name') or ''
		if not role or not name:
			continue
		key = (role, name)
		if key in seen:
			continue
		seen.add(key)
		interactables.append({
			'role': role,
			'label': name,
			'selector': f'role={role}[name="{name}"]',
		})

	# Discover visible contenteditable editors and add as interactables (generic)
	# PRIORITY: Find real contenteditables FIRST, explicitly avoiding trap spans
	try:
		ce_items = _page.evaluate("""
		  () => {
		    function visible(el) {
		      const style = window.getComputedStyle(el);
		      const rect = el.getBoundingClientRect();
		      return (
		        style &&
		        style.visibility !== 'hidden' &&
		        style.display !== 'none' &&
		        rect.width > 0 && rect.height > 0
		      );
		    }
		    function isTrap(el) {
		      return el.hasAttribute('data-content-editable-root-tiny-selection-trap') ||
		             el.closest('[data-content-editable-root-tiny-selection-trap]') !== null;
		    }
		    const results = [];
		    const seen = new Set();
		    // Direct contenteditable elements (exclude traps explicitly)
		    document.querySelectorAll('[contenteditable="true"]').forEach(el => {
		      if (!visible(el)) return;
		      if (isTrap(el)) return;
		      if (el.hasAttribute('data-content-editable-void')) return;
		      const placeholder = el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
		      const name = placeholder || 'Text editor';
		      const key = 'ce|' + name;
		      if (seen.has(key)) return;
		      seen.add(key);
		      
		      // Use the most specific selector possible
		      let selector = '[contenteditable="true"]';
		      if (el.hasAttribute('role') && el.getAttribute('role') === 'textbox') {
		        selector = '[contenteditable="true"][role="textbox"]';
		      }
		      
		      results.push({ 
		        role: 'textbox', 
		        name: name, 
		        selector: selector,
		        priority: 2
		      });
		    });
		    
		    // Sort by priority (lower number = higher priority)
		    results.sort((a, b) => (a.priority || 99) - (b.priority || 99));
		    return results.map(r => ({ role: r.role, name: r.name, selector: r.selector }));
		  }
		""") or []

		seen_ce = { (item['role'], item['label']) for item in interactables }
		for it in ce_items:
			role = it.get('role')
			name = it.get('name') or ''
			selector_str = it.get('selector') or '[contenteditable="true"]'
			if not role or not name:
				continue
			key = (role, name)
			if key in seen_ce:
				continue
			seen_ce.add(key)
			interactables.append({
				'role': role,
				'label': name,
				'selector': selector_str,
			})
			print(f"[DEBUG OBSERVE] Added contenteditable: role={role}, name={name}, selector={selector_str}")
	except Exception as e:
		print(f"[DEBUG OBSERVE] Contenteditable discovery failed: {e}")
		import traceback
		traceback.print_exc()
		pass

    # Removed app-specific injections to keep behavior fully dynamic




	# Removed heuristic hint extraction - LLM makes all decisions
	hint = ''

	# Expose basic frames info for LLM (index, name, url)
	try:
		frames_info = [
			{
				'index': i,
				'name': (f.name or ''),
				'url': (f.url or ''),
			}
			for i, f in enumerate(_page.frames)
		]
	except Exception:
		frames_info = []

	# Focused element snapshot (helps LLM reason about where typing will go)
	try:
		focused = _page.evaluate("""
		  () => {
		    const el = document.activeElement;
		    if (!el) return null;
		    const role = el.getAttribute('role') || '';
		    const name = (el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim();
		    const tag = el.tagName?.toLowerCase() || '';
		    const editable = el.getAttribute('contenteditable') || '';
		    let text = '';
		    try { text = (el.innerText || '').slice(0, 200); } catch (e) {}
		    return { role, name, tag, editable, text };
		  }
		""")
	except Exception:
		focused = None

	# Removed app-specific diagnostics

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
		'errors': error_messages,
		'frames': frames_info,
		'focused': focused
	})


@app.get('/screenshot')
def screenshot_route():
	assert _page is not None
	buf = _page.screenshot(full_page=True)
	return Response(buf, mimetype='image/png')


@app.post('/screenshot_region')
def screenshot_region_route():
    assert _page is not None
    data = request.get_json(force=True) or {}
    selector = data.get('selector')
    margin = int(data.get('margin') or 24)
    if not selector:
        return jsonify({'ok': False, 'error': 'selector is required'}), 400

    try:
        loc = _page.locator(selector).first
        # Ensure element is present/visible and scrolled into view
        loc.wait_for(state='visible', timeout=5000)
        try:
            loc.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass

        box = loc.bounding_box(timeout=2000)
        if not box:
            return jsonify({'ok': False, 'error': 'failed to get bounding box'}), 400

        # Inflate by margin and clamp
        x = max(0, box['x'] - margin)
        y = max(0, box['y'] - margin)
        w = box['width'] + margin * 2
        h = box['height'] + margin * 2

        # Clamp width/height to viewport size
        vp = _page.viewport_size or { 'width': int(x + w), 'height': int(y + h) }
        max_w = max(1, vp['width'] - x)
        max_h = max(1, vp['height'] - y)
        w = max(1, min(w, max_w))
        h = max(1, min(h, max_h))

        buf = _page.screenshot(clip={
            'x': x,
            'y': y,
            'width': w,
            'height': h,
        })
        return Response(buf, mimetype='image/png')
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.post('/act')
def act_route():
	assert _page is not None
	data = request.get_json(force=True) or {}
	try:
		t = data.get('type')
		# Optional: target a specific frame by index
		frame_index = data.get('frame')
		ctx = _page
		try:
			if isinstance(frame_index, int):
				frames = _page.frames
				if 0 <= frame_index < len(frames):
					ctx = frames[frame_index]
		except Exception:
			pass

		# Helper: get candidate selectors (string or list)
		def iter_selectors(d):
			sel = d.get('selector')
			sels = d.get('selectors')
			if sels and isinstance(sels, list):
				for s in sels:
					yield s
			elif isinstance(sel, list):
				for s in sel:
					yield s
			elif isinstance(sel, str):
				yield sel

		if t == 'click':
			last_err = None
			for sel in iter_selectors(data):
				try:
					_robust_click(ctx, sel)
					(_page if ctx is _page else ctx.page).wait_for_timeout(1000)
					return jsonify({ 'ok': True })
				except Exception as e:
					last_err = str(e)
			return jsonify({ 'ok': False, 'error': last_err or 'all selectors failed' }), 500
		elif t == 'scroll':
			delta = data.get('delta', 600)
			(_page if ctx is _page else ctx.page).mouse.wheel(0, delta)
			(_page if ctx is _page else ctx.page).wait_for_timeout(200)
			return jsonify({ 'ok': True })
		elif t == 'type' and data.get('text') is not None:
			text = str(data.get('text'))
			last_err = None
			for sel in iter_selectors(data):
				try:
					_robust_type(ctx, sel, text)
					return jsonify({ 'ok': True })
				except Exception as e:
					last_err = str(e)
			return jsonify({ 'ok': False, 'error': last_err or 'type failed' }), 500
		elif t == 'hover':
			last_err = None
			for sel in iter_selectors(data):
				try:
					ctx.locator(sel).first.wait_for(state='visible', timeout=5000)
					ctx.locator(sel).first.hover(timeout=5000)
					return jsonify({ 'ok': True })
				except Exception as e:
					last_err = str(e)
			return jsonify({ 'ok': False, 'error': last_err or 'hover failed' }), 500
		elif t == 'press':
			keys = str(data.get('keys') or '')
			if not keys:
				return jsonify({ 'ok': False, 'error': 'keys required' }), 400
			pg = (_page if ctx is _page else ctx.page)
			pg.keyboard.press(keys)
			pg.wait_for_timeout(100)
			return jsonify({ 'ok': True })
		elif t == 'wait_for':
			state = (data.get('state') or 'visible')
			last_err = None
			for sel in iter_selectors(data):
				try:
					ctx.locator(sel).first.wait_for(state=state, timeout=int(data.get('timeout') or 5000))
					return jsonify({ 'ok': True })
				except Exception as e:
					last_err = str(e)
			return jsonify({ 'ok': False, 'error': last_err or 'wait_for failed' }), 500
		elif t == 'await':
			kind = (data.get('kind') or 'networkidle').lower()
			pg = (_page if ctx is _page else ctx.page)
			if kind == 'networkidle':
				pg.wait_for_load_state('networkidle', timeout=int(data.get('timeout') or 15000))
				return jsonify({ 'ok': True })
			elif kind == 'timeout':
				pg.wait_for_timeout(int(data.get('ms') or 300))
				return jsonify({ 'ok': True })
			else:
				return jsonify({ 'ok': False, 'error': 'unknown await kind' }), 400
		elif t == 'click_xy':
			x = data.get('x')
			y = data.get('y')
			if x is None or y is None:
				return jsonify({ 'ok': False, 'error': 'x and y required' }), 400
			pg = (_page if ctx is _page else ctx.page)
			pg.mouse.move(float(x), float(y))
			pg.mouse.click(float(x), float(y))
			pg.wait_for_timeout(150)
			return jsonify({ 'ok': True })
		elif t == 'assert':
			kind = (data.get('kind') or '').lower()
			if kind == 'text_present':
				needle = str(data.get('text') or '')
				content = ctx.evaluate('() => document.body.innerText')
				if needle and needle.lower() in (content or '').lower():
					return jsonify({ 'ok': True })
				return jsonify({ 'ok': False, 'error': 'text not found' }), 400
			elif kind == 'url_contains':
				sub = str(data.get('substring') or '')
				cur = (_page if ctx is _page else ctx.page).url
				if sub and sub in cur:
					return jsonify({ 'ok': True })
				return jsonify({ 'ok': False, 'error': 'url does not contain substring' }), 400
			elif kind == 'element_visible':
				last_err = None
				for sel in iter_selectors(data):
					try:
						ctx.locator(sel).first.wait_for(state='visible', timeout=4000)
						return jsonify({ 'ok': True })
					except Exception as e:
						last_err = str(e)
				return jsonify({ 'ok': False, 'error': last_err or 'element not visible' }), 400
			else:
				return jsonify({ 'ok': False, 'error': 'unknown assert kind' }), 400
		else:
			return jsonify({ 'ok': False, 'error': 'unknown or malformed action' }), 400
	except Exception as e:
		print(f"[ACT ERROR] Type: {data.get('type')}, Selector: {data.get('selector')}, Error: {str(e)}")
		return jsonify({ 'ok': False, 'error': str(e) }), 500


def main():
	app.run(host='127.0.0.1', port=3999, threaded=False)


if __name__ == '__main__':
	main()

