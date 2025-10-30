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
	"""Attempt a robust click with fallbacks if intercepted by overlays."""
	locator = page.locator(selector).first
	locator.wait_for(state='visible', timeout=5000)
	try:
		locator.click(timeout=10000)
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
			# Robust click that handles overlays/backdrops
			_robust_click(_page, data['selector'])
			_page.wait_for_timeout(400)
		elif t == 'scroll':
			delta = data.get('delta', 600)
			_page.mouse.wheel(0, delta)
			_page.wait_for_timeout(200)
		elif t == 'type' and data.get('selector') and data.get('text') is not None:
			locator = _page.locator(data['selector'])
			locator.wait_for(state='visible', timeout=5000)
			locator.fill(str(data['text']))
			_page.wait_for_timeout(200)
		return jsonify({ 'ok': True })
	except Exception as e:
		print(f"[ACT ERROR] Type: {data.get('type')}, Selector: {data.get('selector')}, Error: {str(e)}")
		return jsonify({ 'ok': False, 'error': str(e) }), 500


def main():
	app.run(host='127.0.0.1', port=3999, threaded=False)


if __name__ == '__main__':
	main()

