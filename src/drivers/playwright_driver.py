from __future__ import annotations
from flask import Flask, request, jsonify, Response
from playwright.sync_api import sync_playwright, Page, BrowserContext
import re
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


def _robust_click(page: Page, selector: str) -> None:
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
            container = page.locator('[role="listbox"], [role="menu"], [data-state="open"], [aria-modal="true"]').first
            if container.count() == 0 or not container.is_visible():
                # Try to open an active combobox if present
                try:
                    combo = page.locator('[role="combobox"]').filter(has=page.locator('[aria-expanded="false"]')).first
                    if combo and (combo.count() > 0):
                        combo.click(timeout=800)
                except Exception:
                    pass
                # Try common keyboard openers
                try:
                    page.keyboard.press('Alt+ArrowDown')
                except Exception:
                    pass
                page.wait_for_timeout(200)
            # Wait for any container to be visible
            page.locator('[role="listbox"], [role="menu"], [data-state="open"], [aria-modal="true"]').first.wait_for(state='visible', timeout=8000)
        except Exception:
            pass

        # Attempt exact, then partial, then regex case-insensitive matches
        candidates = [
            page.get_by_role('option', name=desired_label).first,
            page.get_by_role('menuitem', name=desired_label).first,
            page.locator('[role="option"]', has_text=desired_label).first,
            page.locator('[role="menuitem"]', has_text=desired_label).first,
        ]
        try:
            regex = re.compile(re.escape(desired_label), re.IGNORECASE)
            candidates.extend([
                page.locator('[role="option"]').filter(has_text=regex).first,
                page.locator('[role="menuitem"]').filter(has_text=regex).first,
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
                    page.wait_for_timeout(200)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked and desired_label:
            # Try to filter options by typing the desired label
            try:
                active = page.locator('[role="combobox"][aria-expanded="true"], input[role="combobox"], input[aria-autocomplete]')
                el = active.first if active.count() > 0 else None
                if el:
                    try:
                        el.fill(desired_label)
                    except Exception:
                        el.click(timeout=800)
                        page.keyboard.type(desired_label)
                    page.wait_for_timeout(300)
                    # Retry selecting the first matching option
                    opt = page.locator('[role="option"]').filter(has_text=re.compile(re.escape(desired_label), re.IGNORECASE)).first
                    opt.wait_for(state='visible', timeout=5000)
                    opt.click(timeout=3000)
                    page.wait_for_timeout(200)
                    clicked = True
            except Exception:
                pass

        if clicked:
            # Wait briefly for UI state to reflect the selection (e.g., assignee label updates)
            try:
                pattern = re.compile(re.escape(desired_label), re.IGNORECASE) if desired_label else None
                if pattern:
                    page.locator('[role="button"], [aria-label], [role], button, a, span, div, input').filter(has_text=pattern).first.wait_for(state='visible', timeout=2000)
            except Exception:
                pass
            return
        # Fall through to generic path if above failed

    locator = page.locator(selector).first
    locator.wait_for(state='visible', timeout=10000)
    try:
        try:
            locator.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass
        locator.click(timeout=12000)
        page.wait_for_timeout(200)
        return
    except Exception as e:
        message = str(e)
        # If pointer events are intercepted or similar, try fallbacks
        if 'intercepts pointer events' in message or 'element receives pointer-events' in message or 'Timeout' in message:
            # 1) Dismiss overlays and retry normal click
            _dismiss_overlays(page)
            try:
                locator.click(timeout=3000)
                page.wait_for_timeout(150)
                return
            except Exception:
                pass
            # 2) Force click (may bypass hit testing)
            try:
                locator.click(force=True, timeout=2000)
                page.wait_for_timeout(150)
                return
            except Exception:
                pass
            # 3) JS click
            try:
                page.evaluate("el => el.click()", locator.element_handle(timeout=2000))
                page.wait_for_timeout(150)
                return
            except Exception:
                pass
            # 4) Click center of bounding box with the mouse
            try:
                box = locator.bounding_box(timeout=2000)
                if box:
                    x = box['x'] + box['width'] / 2
                    y = box['y'] + box['height'] / 2
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.mouse.up()
                    page.wait_for_timeout(150)
                    return
            except Exception:
                pass
        # Re-raise original error if all fallbacks failed
        raise



def _robust_type(page: Page, selector: str, text: str) -> None:
	loc = page.locator(selector).first
	loc.wait_for(state='visible', timeout=5000)
	# Try direct fill first
	try:
		loc.fill(str(text))
		page.wait_for_timeout(200)
		return
	except Exception:
		pass

	# Click to focus/expand (e.g., YouTube comment box)
	try:
		loc.click(timeout=1500)
		page.wait_for_timeout(150)
	except Exception:
		try:
			_robust_click(page, selector)
			page.wait_for_timeout(150)
		except Exception:
			pass

	# Prefer a visible contenteditable textbox (YouTube uses this)
	editable = page.locator('[contenteditable="true"][role="textbox"]').first
	if editable.count() == 0:
		editable = page.locator('#contenteditable-root[contenteditable="true"]').first

	if editable.count() > 0:
		editable.wait_for(state='visible', timeout=3000)
		try:
			editable.fill(str(text))
			page.wait_for_timeout(200)
			return
		except Exception:
			editable.click(timeout=1000)
			page.keyboard.type(str(text))
			page.wait_for_timeout(200)
			return

	# Last resort: type after focusing original
	try:
		loc.click(timeout=1000)
		page.keyboard.type(str(text))
		page.wait_for_timeout(200)
		return
	except Exception:
		pass

	raise RuntimeError("Failed to type into target or any discovered editor")


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
    const containers = [
      ...document.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"], [aria-modal="true"], [data-state="open"]'),
    ];
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
		if t == 'click' and data.get('selector'):
			# Robust click that handles overlays/backdrops
			_robust_click(_page, data['selector'])
			_page.wait_for_timeout(700)
		elif t == 'scroll':
			delta = data.get('delta', 600)
			_page.mouse.wheel(0, delta)
			_page.wait_for_timeout(200)
		elif t == 'type' and data.get('selector') and data.get('text') is not None:
			_robust_type(_page, data['selector'], str(data['text']))
			# Special handling for UberEats address entry: select first autocomplete option, then search
			try:
				selector_str = str(data.get('selector') or '')
				if 'Enter delivery address' in selector_str:
					selected = False
					# Try clicking the first suggestion from the listbox
					try:
						lb = _page.locator('[role="listbox"]').first
						lb.wait_for(state='visible', timeout=8000)
						opt = _page.locator('[role="option"]').first
						opt.wait_for(state='visible', timeout=4000)
						opt.click(timeout=5000)
						_page.wait_for_load_state('networkidle', timeout=15000)
						selected = True
					except Exception:
						pass
					# Fallback: ArrowDown + Enter to select first suggestion
					if not selected:
						try:
							_page.keyboard.press('ArrowDown')
							_page.wait_for_timeout(200)
							_page.keyboard.press('Enter')
							_page.wait_for_load_state('networkidle', timeout=15000)
							selected = True
						except Exception:
							pass
					# Best-effort: find a search box and query for chicken wings
					try:
						try:
							search = _page.get_by_role('searchbox')
						except Exception:
							search = None
						if not search or (hasattr(search, 'count') and search.count() == 0):
							search = _page.locator('input[placeholder*="Search" i], input[type="search"]').first
						if hasattr(search, 'count') and search.count() == 0:
							raise Exception('No visible search box')
						search.wait_for(state='visible', timeout=6000)
						try:
							search.fill('chicken wings')
						except Exception:
							search.click(timeout=1500)
							_page.keyboard.type('chicken wings')
						_page.keyboard.press('Enter')
						_page.wait_for_load_state('networkidle', timeout=15000)
					except Exception:
						pass
			except Exception:
				pass
		return jsonify({ 'ok': True })
	except Exception as e:
		print(f"[ACT ERROR] Type: {data.get('type')}, Selector: {data.get('selector')}, Error: {str(e)}")
		return jsonify({ 'ok': False, 'error': str(e) }), 500


def main():
	app.run(host='127.0.0.1', port=3999, threaded=False)


if __name__ == '__main__':
	main()

