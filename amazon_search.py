from typing import List
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from utils import STORAGE_STATE_PATH


AMAZON_SEARCH_URL = "https://www.amazon.com/s?k={query}"


def search_top_products(keyword: str, limit: int = 3, headless: bool = False) -> List[str]:
    query_url = AMAZON_SEARCH_URL.format(query=quote(keyword))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"]) 
        context = browser.new_context(
            storage_state=str(STORAGE_STATE_PATH) if STORAGE_STATE_PATH.exists() else None,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            locale="en-US",
            geolocation=None,
        )
        page = context.new_page()
        page.goto(query_url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector('div.s-main-slot div[data-component-type="s-search-result"]', timeout=10000)
        except Exception:
            pass

        loc = page.locator('div.s-main-slot div[data-component-type="s-search-result"]')
        max_check = min(loc.count(), 40)
        links: List[str] = []
        seen = set()

        for i in range(max_check):
            item = loc.nth(i)
            # Prefer detail page anchors that contain /dp/
            a = item.locator('h2 a.a-link-normal').first
            if a.count() == 0:
                a = item.locator('a.a-link-normal.s-no-outline').first
            if a.count() == 0:
                continue
            href = a.get_attribute("href")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.amazon.com" + href
            # Filter to product detail pages containing /dp/
            if "/dp/" not in href:
                continue
            if href in seen:
                continue
            seen.add(href)
            links.append(href)
            if len(links) >= limit:
                break

        browser.close()
        return links
