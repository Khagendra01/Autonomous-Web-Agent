from playwright.sync_api import sync_playwright
from pathlib import Path
import json
import os
import argparse


def main():
    parser = argparse.ArgumentParser(
        description='Record authentication cookies for any website',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python -m scripts.record_cookies                                    # Default: Linear
  python -m scripts.record_cookies --app github --url https://github.com
  python -m scripts.record_cookies --app gmail --url https://mail.google.com
  python -m scripts.record_cookies --app notion --url https://notion.so
        '''
    )
    parser.add_argument('--app', type=str, default='linear', 
                       help='App name (used for cookie file name, e.g., "github", "gmail")')
    parser.add_argument('--url', type=str, default='https://linear.app',
                       help='Website URL to record cookies from')
    
    args = parser.parse_args()
    
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

        print(f'Opening {args.url}...')
        page.goto(args.url, wait_until='load')
        print(f'\nComplete your login for {args.app}.')
        print('Tip: Avoid Google SSO if blocked; use email/password or magic link.')
        print('\nAfter login completes, press Enter here to save cookies...')
        _ = input()
        
        cookies = ctx.cookies()
        Path('auth').mkdir(exist_ok=True)
        cookie_file = Path(f'auth/{args.app}-cookies.json')
        cookie_file.write_text(json.dumps(cookies, indent=2))
        print(f'✓ Saved {cookie_file}')
        
        try:
            ctx.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()

