from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright


AMAZON_SIGNIN_URL = "https://www.amazon.com/ap/signin"


def interactive_login(storage_state_path: Path, headless: bool = False) -> None:
    storage_state_path = Path(storage_state_path)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"]) 
        context = browser.new_context()
        page = context.new_page()
        page.goto(AMAZON_SIGNIN_URL, wait_until="domcontentloaded")

        print("A Chromium window has opened. Please complete Amazon login there.")
        print("After you are signed in, return here and press ENTER to save session.")
        try:
            input()
        except KeyboardInterrupt:
            print("Login aborted by user.")
            browser.close()
            return

        # Attempt to verify sign-in by checking nav account element
        try:
            page.goto("https://www.amazon.com/", wait_until="domcontentloaded")
            # The presence of account nav line often indicates login
            _ = page.locator("#nav-link-accountList-nav-line-1").first
        except Exception:
            pass

        context.storage_state(path=str(storage_state_path))
        print(f"Saved session to {storage_state_path}")
        browser.close()
