from playwright.sync_api import sync_playwright
from pathlib import Path
import json
import os


def main():
    with sync_playwright() as pw:
        use_cdp = os.environ.get('USE_CDP', '0') == '1'
        if use_cdp:
            # Connect to an existing Chrome you started with --remote-debugging-port=9222
            browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
        else:
            # Persistent context uses a real Chrome profile folder; helps bypass strict OAuth checks
            user_dir = Path('chrome-user')
            user_dir.mkdir(exist_ok=True)
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(user_dir),
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            page = ctx.new_page()

        page.goto('https://linear.app', wait_until='load')
        print('Avoid Google SSO if blocked; use email/password or magic link.\nAfter login completes, press Enter here to save cookies...')
        _ = input()
        cookies = ctx.cookies()
        Path('auth').mkdir(exist_ok=True)
        Path('auth/linear-cookies.json').write_text(json.dumps(cookies, indent=2))
        print('Saved auth/linear-cookies.json')
        try:
            ctx.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()

