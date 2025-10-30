from playwright.sync_api import sync_playwright
import json, os

COOKIES_PATH = "auth/linear_cookies.json"
os.makedirs("auth", exist_ok=True)
os.makedirs("dataset/step1", exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()

    # 🔐 Load cookies if present
    if os.path.exists(COOKIES_PATH):
        cookies = json.load(open(COOKIES_PATH))
        context.add_cookies(cookies)
        print("✅ Cookies loaded")

    page = context.new_page()
    page.goto("https://linear.app/", wait_until="load")
    print("🌐 Opened:", page.url)

    # If cookies not saved yet → let user log in manually
    if not os.path.exists(COOKIES_PATH):
        input("👉 Log in, then press Enter here...")
        cookies = context.cookies()
        json.dump(cookies, open(COOKIES_PATH, "w"), indent=2)
        print("💾 Saved cookies to", COOKIES_PATH)

    # 📸 Screenshot
    out = "dataset/step1/001_home.png"
    page.screenshot(path=out, full_page=True)
    print("🖼️ Saved screenshot:", out)

    browser.close()
