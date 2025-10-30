from playwright.sync_api import sync_playwright
from pathlib import Path
import json


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto('https://linear.app', wait_until='load')
        print('Log in manually, then press Enter here to save cookies...')
        _ = input()
        cookies = ctx.cookies()
        Path('auth').mkdir(exist_ok=True)
        Path('auth/linear-cookies.json').write_text(json.dumps(cookies, indent=2))
        print('Saved auth/linear-cookies.json')
        browser.close()


if __name__ == '__main__':
    main()

