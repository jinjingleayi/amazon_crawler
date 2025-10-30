from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from utils import STORAGE_STATE_PATH, write_text


STAR_MAP = {
    5: "five_star",
    4: "four_star",
    3: "three_star",
    2: "two_star",
    1: "one_star",
}


ASIN_REGEXES = [
    re.compile(r"/dp/([A-Z0-9]{10})"),
    re.compile(r"/product-reviews/([A-Z0-9]{10})"),
]


def _extract_host_and_asin(url: str) -> Tuple[str, Optional[str]]:
    parsed = urlparse(url)
    asin: Optional[str] = None
    for rgx in ASIN_REGEXES:
        m = rgx.search(url)
        if m:
            asin = m.group(1)
            break
    host = parsed.netloc or "www.amazon.com"
    return host, asin


def _reviews_url_from_asin(host: str, asin: str) -> str:
    return f"https://{host}/product-reviews/{asin}"


def _get_reviews_link(page, product_url: str) -> Optional[str]:
    page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
    _dismiss_overlays(page)
    link = page.locator('a[data-hook="see-all-reviews-link-foot"]').first
    if link.count() == 0:
        link = page.locator('a[data-hook="see-all-reviews-link"]').first
    if link.count() > 0:
        href = link.get_attribute("href")
        if href:
            return ("https://" + urlparse(product_url).netloc + href) if href.startswith("/") else href

    host, asin = _extract_host_and_asin(product_url)
    if asin:
        return _reviews_url_from_asin(host, asin)
    return None


def _apply_star_filter_query(base_reviews_url: str, star: int, page_number: int = 1, all_stars: bool = False) -> str:
    parsed = urlparse(base_reviews_url)
    qs = parse_qs(parsed.query)
    qs["reviewerType"] = ["all_reviews"]
    qs["pageNumber"] = [str(page_number)]
    qs["sortBy"] = ["recent"]
    qs["language"] = ["en_US"]
    if all_stars:
        qs["filterByStar"] = ["all_stars"]
    else:
        qs["filterByStar"] = [STAR_MAP.get(star, "all_stars")]
    new_query = urlencode({k: v[0] for k, v in qs.items()})
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _click_star_filter_if_present(page, star: int) -> bool:
    hook = f'a[href*="filterByStar={STAR_MAP.get(star, "all_stars")}"]'
    filter_link = page.locator(hook).first
    if filter_link.count() > 0:
        try:
            filter_link.click()
            page.wait_for_selector('div[data-hook="review"], #cm_cr-review_list', timeout=15000)
            return True
        except Exception:
            return False
    alt = page.locator(f'a[data-hook="cr-filter-stars-{star}"]').first
    if alt.count() > 0:
        try:
            alt.click()
            page.wait_for_selector('div[data-hook="review"], #cm_cr-review_list', timeout=15000)
            return True
        except Exception:
            return False
    return False


def _page_has_captcha_or_block(page) -> bool:
    text = page.inner_text("body")
    flags = [
        "Enter the characters you see below",
        "To discuss automated access to Amazon data",
        "sorry we just need to make sure you're not a robot",
        "CBI_ROBOT_MITIGATION",
    ]
    return any(flag.lower() in text.lower() for flag in flags)


def _page_says_no_reviews(page) -> bool:
    text = page.inner_text("body")
    flags = [
        "There are no reviews that match the current selection",
        "No customer reviews",
    ]
    return any(flag.lower() in text.lower() for flag in flags)


def _expand_truncated_reviews(page) -> None:
    buttons = page.locator('span[data-action="columnbalancing-showfullreview"] a, a[data-hook="review-title"] + span a')
    count = buttons.count()
    for i in range(count):
        try:
            buttons.nth(i).click(timeout=500)
        except Exception:
            continue


def _dismiss_overlays(page) -> None:
    for sel in [
        '#sp-cc-accept',
        'input#sp-cc-accept',
        'input[name="accept"]',
    ]:
        btn = page.locator(sel)
        if btn.count() > 0:
            try:
                btn.click(timeout=500)
                time.sleep(0.2)
            except Exception:
                pass
    for sel in [
        'input[name="glowDoneButton"]',
        'button[name="glowDoneButton"]',
        '#a-popover-1 button[name="glowDoneButton"]',
    ]:
        btn = page.locator(sel)
        if btn.count() > 0:
            try:
                btn.click(timeout=500)
                time.sleep(0.2)
            except Exception:
                pass


def _parse_reviews_on_page(page) -> List[Dict]:
    results: List[Dict] = []
    try:
        page.wait_for_selector('#cm_cr-review_list, div[data-hook="review"], span[data-hook="review-body"]', timeout=30000)
    except Exception:
        return results

    _expand_truncated_reviews(page)

    review_items = page.locator('div[data-hook="review"]')
    if review_items.count() == 0:
        review_items = page.locator('#cm_cr-review_list div.review')

    def _extract_date_text_from_node(n):
        # Prefer explicit selector
        loc = n.locator('span[data-hook="review-date"]')
        if loc.count() > 0:
            return loc.nth(0).inner_text()
        loc = n.locator('.review-date')
        if loc.count() > 0:
            return loc.nth(0).inner_text()
        # Fallback: nearest preceding date inside review subtree
        try:
            loc = n.locator('xpath=.//preceding::span[@data-hook="review-date"][1] | .//preceding::span[contains(@class, "review-date")][1]').first
            if loc and loc.count() > 0:
                return loc.inner_text()
        except Exception:
            pass
        # Fallback regex
        try:
            text = n.inner_text()
            m = re.search(r'(Reviewed[^\n]* on [^\n]+)|(\b\d{4}[-/年].{0,8}?\d{1,2}[-/月].{0,8}?\d{1,2}日?\b)', text)
            return m.group(0) if m else ""
        except Exception:
            return ""

    def _extract_author_from_node(n):
        # Prefer explicit selector
        loc = n.locator('.a-profile-content .a-profile-name')
        if loc.count() > 0:
            return loc.nth(0).inner_text()
        for sel in ['span.a-profile-name', 'span[data-hook="review-author"]', 'a[data-hook="review-author"]']:
            loc = n.locator(sel)
            if loc.count() > 0:
                return loc.nth(0).inner_text()
        # Fallback: nearest preceding profile name
        try:
            loc = n.locator('xpath=.//preceding::span[contains(@class, "a-profile-name")][1] | .//preceding::a[@data-hook="review-author"][1]').first
            if loc and loc.count() > 0:
                return loc.inner_text()
        except Exception:
            pass
        return ""

    if review_items.count() > 0:
        count = review_items.count()
        for i in range(count):
            node = review_items.nth(i)
            body_locator = node.locator('span[data-hook="review-body"] span')
            if body_locator.count() == 0:
                body_locator = node.locator('span[data-hook="review-body"]')
            if body_locator.count() == 0:
                body_locator = node.locator('.review-text-content span')
            content = body_locator.all_text_contents()
            content_text = "\n".join([t.strip() for t in content if t and t.strip()])

            rating_locator = node.locator('i[data-hook="review-star-rating"] span')
            if rating_locator.count() == 0:
                rating_locator = node.locator('i[data-hook="cmps-review-star-rating"] span')
            if rating_locator.count() == 0:
                rating_locator = node.locator('span.a-icon-alt')
            rating_text = rating_locator.nth(0).inner_text() if rating_locator.count() > 0 else ""

            nickname = _extract_author_from_node(node)
            date_text = _extract_date_text_from_node(node)

            if not (content_text or rating_text or nickname or date_text):
                continue

            results.append({
                "review_content": content_text,
                "review_rating_text": rating_text,
                "review_date": date_text,
                "reviewer": nickname,
            })
        if results:
            return results

    # Fallback: scan standalone bodies on the page
    bodies = page.locator('span[data-hook="review-body"]')
    for i in range(bodies.count()):
        body_node = bodies.nth(i)
        content_list = body_node.all_text_contents()
        content_text = "\n".join([t.strip() for t in content_list if t and t.strip()])
        rating_text = ""
        date_text = ""
        nickname = ""
        try:
            anc = body_node.locator('xpath=ancestor::div[contains(@data-hook, "review")] | xpath=ancestor::div[contains(@class, "review")]').first
            if anc and anc.count() > 0:
                rt = anc.locator('i//span[contains(@class, "a-icon-alt")]').first
                if rt.count() == 0:
                    rt = anc.locator('i[data-hook="review-star-rating"] span, i[data-hook="cmps-review-star-rating"] span').first
                if rt and rt.count() > 0:
                    rating_text = rt.inner_text()
                # Prefer explicit selectors
                name_loc = anc.locator('.a-profile-content .a-profile-name')
                if name_loc.count() == 0:
                    name_loc = anc.locator('span.a-profile-name, a[data-hook="review-author"], span[data-hook="review-author"]')
                if name_loc and name_loc.count() > 0:
                    nickname = name_loc.nth(0).inner_text()
                date_loc = anc.locator('span[data-hook="review-date"], .review-date')
                if date_loc and date_loc.count() > 0:
                    date_text = date_loc.nth(0).inner_text()
                else:
                    date_text = _extract_date_text_from_node(anc)
        except Exception:
            pass
        if content_text:
            results.append({
                "review_content": content_text,
                "review_rating_text": rating_text,
                "review_date": date_text,
                "reviewer": nickname,
            })
    return results


def _parse_reviews_from_ajax_html(html_text: str) -> List[Dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    results: List[Dict] = []
    review_items = soup.select('div[data-hook="review"], #cm_cr-review_list div.review, div.a-section.review')

    def _extract_date_text(node):
        el = node.select_one('span[data-hook="review-date"], .review-date')
        if el:
            return el.get_text(strip=True)
        # Fallback: nearest preceding date
        prev = node.find_previous(lambda t: t.name == 'span' and (t.get('data-hook') == 'review-date' or 'review-date' in t.get('class', [])))
        if prev:
            return prev.get_text(strip=True)
        # Regex fallback
        text = node.get_text("\n", strip=True)
        m = re.search(r'(Reviewed[^\n]* on [^\n]+)|(\b\d{4}[-/年].{0,8}?\d{1,2}[-/月].{0,8}?\d{1,2}日?\b)', text)
        return m.group(0) if m else ""

    def _extract_author(node):
        # Prefer explicit selector
        el = node.select_one('.a-profile-content .a-profile-name')
        if el:
            return el.get_text(strip=True)
        for sel in ['span.a-profile-name', 'span[data-hook="review-author"]', 'a[data-hook="review-author"]']:
            el = node.select_one(sel)
            if el:
                return el.get_text(strip=True)
        # Fallback: nearest preceding profile name
        prev = node.find_previous(lambda t: (t.name in ['span', 'a']) and ('a-profile-name' in t.get('class', []) or t.get('data-hook') == 'review-author'))
        if prev:
            return prev.get_text(strip=True)
        return ""

    for node in review_items:
        body_texts = [t.get_text(strip=True) for t in node.select('span[data-hook="review-body"] span, span[data-hook="review-body"], .review-text-content span')]
        content_text = "\n".join([t for t in body_texts if t])
        rating_el = node.select_one('i[data-hook="review-star-rating"] span, i[data-hook="cmps-review-star-rating"] span, span.a-icon-alt')
        rating_text = rating_el.get_text(strip=True) if rating_el else ""
        nickname = _extract_author(node)
        date_text = _extract_date_text(node)
        if not (content_text or rating_text or nickname or date_text):
            continue
        results.append({
            "review_content": content_text,
            "review_rating_text": rating_text,
            "review_date": date_text,
            "reviewer": nickname,
        })

    if results:
        return results

    # Fallback: scan standalone bodies when container markup differs
    for body in soup.select('span[data-hook="review-body"]'):
        content_text = body.get_text("\n", strip=True)
        anc = body.find_parent(lambda tag: (getattr(tag, 'name', None) == 'div' and 'review' in ' '.join(tag.get('class', []))) or (tag and tag.has_attr('data-hook') and 'review' in tag['data-hook']))
        rating_text = ""
        date_text = ""
        nickname = ""
        search_base = anc if anc else body
        rt = search_base.select_one('i[data-hook="review-star-rating"] span, i[data-hook="cmps-review-star-rating"] span, span.a-icon-alt')
        rating_text = rt.get_text(strip=True) if rt else ""
        dt = search_base.select_one('span[data-hook="review-date"], .review-date')
        if dt:
            date_text = dt.get_text(strip=True)
        else:
            prev_dt = search_base.find_previous(lambda t: t.name == 'span' and (t.get('data-hook') == 'review-date' or 'review-date' in t.get('class', [])))
            if prev_dt:
                date_text = prev_dt.get_text(strip=True)
        au = search_base.select_one('.a-profile-content .a-profile-name, span.a-profile-name, span[data-hook="review-author"], a[data-hook="review-author"]')
        nickname = au.get_text(strip=True) if au else (search_base.find_previous(lambda t: (t.name in ['span','a']) and ('a-profile-name' in t.get('class', []) or t.get('data-hook') == 'review-author')).get_text(strip=True) if search_base.find_previous(lambda t: (t.name in ['span','a']) and ('a-profile-name' in t.get('class', []) or t.get('data-hook') == 'review-author')) else "")
        if content_text:
            results.append({
                "review_content": content_text,
                "review_rating_text": rating_text,
                "review_date": date_text,
                "reviewer": nickname,
            })
    return results


def _parse_reviews_from_page_html(html_text: str) -> List[Dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    results: List[Dict] = []
    review_items = soup.select('div[data-hook="review"], #cm_cr-review_list div.review, div.a-section.review')

    def _extract_date_text(node):
        el = node.select_one('span[data-hook="review-date"], .review-date')
        if el:
            return el.get_text(strip=True)
        prev = node.find_previous(lambda t: t.name == 'span' and (t.get('data-hook') == 'review-date' or 'review-date' in t.get('class', [])))
        if prev:
            return prev.get_text(strip=True)
        text = node.get_text("\n", strip=True)
        m = re.search(r'(Reviewed[^\n]* on [^\n]+)|(\b\d{4}[-/年].{0,8}?\d{1,2}[-/月].{0,8}?\d{1,2}日?\b)', text)
        return m.group(0) if m else ""

    def _extract_author(node):
        el = node.select_one('.a-profile-content .a-profile-name')
        if el:
            return el.get_text(strip=True)
        for sel in ['span.a-profile-name', 'span[data-hook="review-author"]', 'a[data-hook="review-author"]']:
            el = node.select_one(sel)
            if el:
                return el.get_text(strip=True)
        prev = node.find_previous(lambda t: (t.name in ['span','a']) and ('a-profile-name' in t.get('class', []) or t.get('data-hook') == 'review-author'))
        if prev:
            return prev.get_text(strip=True)
        return ""

    for node in review_items:
        body_texts = [t.get_text(strip=True) for t in node.select('span[data-hook="review-body"] span, span[data-hook="review-body"], .review-text-content span')]
        content_text = "\n".join([t for t in body_texts if t])
        rating_el = node.select_one('i[data-hook="review-star-rating"] span, i[data-hook="cmps-review-star-rating"] span, span.a-icon-alt')
        rating_text = rating_el.get_text(strip=True) if rating_el else ""
        nickname = _extract_author(node)
        date_text = _extract_date_text(node)
        if not (content_text or rating_text or nickname or date_text):
            continue
        results.append({
            "review_content": content_text,
            "review_rating_text": rating_text,
            "review_date": date_text,
            "reviewer": nickname,
        })

    if results:
        return results

    # Fallback to body-only
    for body in soup.select('span[data-hook="review-body"]'):
        content_text = body.get_text("\n", strip=True)
        anc = body.find_parent(lambda tag: (getattr(tag, 'name', None) == 'div' and 'review' in ' '.join(tag.get('class', []))) or (tag and tag.has_attr('data-hook') and 'review' in tag['data-hook']))
        rating_text = ""
        date_text = ""
        nickname = ""
        search_base = anc if anc else body
        rt = search_base.select_one('i[data-hook="review-star-rating"] span, i[data-hook="cmps-review-star-rating"] span, span.a-icon-alt')
        rating_text = rt.get_text(strip=True) if rt else ""
        dt = search_base.select_one('span[data-hook="review-date"], .review-date')
        if dt:
            date_text = dt.get_text(strip=True)
        else:
            prev_dt = search_base.find_previous(lambda t: t.name == 'span' and (t.get('data-hook') == 'review-date' or 'review-date' in t.get('class', [])))
            if prev_dt:
                date_text = prev_dt.get_text(strip=True)
        au = search_base.select_one('.a-profile-content .a-profile-name, span.a-profile-name, span[data-hook="review-author"], a[data-hook="review-author"]')
        if au:
            nickname = au.get_text(strip=True)
        else:
            prev_au = search_base.find_previous(lambda t: (t.name in ['span','a']) and ('a-profile-name' in t.get('class', []) or t.get('data-hook') == 'review-author'))
            nickname = prev_au.get_text(strip=True) if prev_au else ""
        if content_text:
            results.append({
                "review_content": content_text,
                "review_rating_text": rating_text,
                "review_date": date_text,
                "reviewer": nickname,
            })
    return results


def _slow_scroll(page, steps: int = 8, wait: float = 0.6) -> None:
    for _ in range(steps):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight / 2)")
        time.sleep(wait)


def _get_csrf_from_cookies(context) -> Optional[str]:
    try:
        cookies = context.cookies()
        for c in cookies:
            if c.get("name") == "anti-csrftoken-a2z" and c.get("value"):
                return c.get("value")
    except Exception:
        pass
    return None


def _fetch_reviews_via_ajax(context, host: str, asin: str, star: int, page_number: int) -> List[Dict]:
    form = {
        "asin": asin,
        "pageNumber": str(page_number),
        "reviewerType": "all_reviews",
        "filterByStar": STAR_MAP.get(star, "all_stars"),
        "sortBy": "recent",
        "formatType": "current_format",
        "mediaType": "",
        "scope": "reviewsAjax1",
    }
    url = f"https://{host}/hz/reviews-render/ajax/reviews/get/ref=cm_cr_arp_d_viewopt_srt"

    headers = {
        "x-requested-with": "XMLHttpRequest",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "accept": "*/*",
        "origin": f"https://{host}",
        "referer": f"https://{host}/product-reviews/{asin}",
    }
    csrf = _get_csrf_from_cookies(context)
    if csrf:
        headers["anti-csrftoken-a2z"] = csrf

    resp = context.request.post(url, form=form, headers=headers, timeout=60000)
    status = resp.status
    text = resp.text()
    # Persist raw response for debugging
    write_text(f"STATUS={status}\n\n" + text, f"debug_ajax_reviews_p{page_number}.html")

    # Amazon often returns a JSON with html fragments; try to parse it
    html_text = text
    try:
        data = json.loads(text)
        html_text = data.get("reviewsHtml") or data.get("html") or text
    except Exception:
        pass

    return _parse_reviews_from_ajax_html(html_text)


def scrape_reviews_for_product(product_url: str, star: int, max_pages: int = 2, headless: bool = False) -> List[Dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"]) 
        context = browser.new_context(
            storage_state=str(STORAGE_STATE_PATH) if STORAGE_STATE_PATH.exists() else None,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            locale="en-US",
            extra_http_headers={"accept-language": "en-US,en;q=0.9"},
            timezone_id="America/Los_Angeles",
            viewport={"width": 1300, "height": 900},
        )
        context.set_default_timeout(40000)
        context.set_default_navigation_timeout(60000)
        page = context.new_page()

        base_reviews_url = _get_reviews_link(page, product_url)
        host, asin = _extract_host_and_asin(product_url)
        if not base_reviews_url or not asin:
            browser.close()
            return []

        all_reviews: List[Dict] = []
        page.goto(base_reviews_url, wait_until="domcontentloaded", timeout=60000)
        _dismiss_overlays(page)
        _slow_scroll(page)

        clicked = _click_star_filter_if_present(page, star)

        for page_idx in range(1, max_pages + 1):
            if not clicked or page_idx > 1:
                url = _apply_star_filter_query(base_reviews_url, star, page_number=page_idx)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            _dismiss_overlays(page)
            _slow_scroll(page)

            chunk = _parse_reviews_on_page(page)
            if not chunk:
                # AJAX fallback
                ajax_chunk = _fetch_reviews_via_ajax(context, host, asin, star, page_idx)
                chunk = ajax_chunk
            # Final fallback: parse full page HTML with BeautifulSoup to ensure author/date
            if chunk and all((not r.get('reviewer') or not r.get('review_date')) for r in chunk):
                html = page.content()
                bs_chunk = _parse_reviews_from_page_html(html)
                if bs_chunk:
                    # Prefer filling missing fields by aligning by order
                    for i in range(min(len(chunk), len(bs_chunk))):
                        if not chunk[i].get('reviewer'):
                            chunk[i]['reviewer'] = bs_chunk[i].get('reviewer', '')
                        if not chunk[i].get('review_date'):
                            chunk[i]['review_date'] = bs_chunk[i].get('review_date', '')
            all_reviews.extend(chunk)

            next_link = page.locator('li.a-last a')
            if next_link.count() == 0:
                break

        browser.close()
        return all_reviews
