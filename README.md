# Amazon Crawler (Playwright)

Features
- Search Amazon by keyword and collect the top 3 product detail page links
- Filter reviews by star rating (1–5) and scrape at least 1 page of reviews per product
- Persisted login via Playwright storage state (cookies), captured interactively

Data fields collected
- review_content
- review_rating_text
- review_date
- reviewer

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## First-time login (save cookies)

```bash
python main.py --login
```
- A Chromium window opens. Log in to your Amazon account in that window.
- After you see you are signed in, return to the terminal and press ENTER.
- The session is saved to `storage_state.json` (already ignored by .gitignore).

## Usage

1) Interactive search (returns top 3 links), choose stars and pages
```bash
python main.py --pages 2 --limit 3
# Then enter a keyword (e.g., smart watch) and a star rating (1–5 or '5星')
```

2) Use your own URLs (detail or pre-filtered review pages)
```bash
# Single product reviews URL, 4-star, 1 page
python main.py --urls "https://www.amazon.com/product-reviews/<ASIN>?filterByStar=four_star&reviewerType=all_reviews" --pages 1 --limit 1

# Detail page URL, choose star interactively
python main.py --urls "https://www.amazon.com/dp/<ASIN>" --pages 2 --limit 1
```

Outputs
- Written to `output/` as both CSV and JSON.

## How each requirement is implemented

1) Search top 3 product detail links by keyword
- File: `amazon_search.py` → `search_top_products(keyword, limit=3, headless=...)`
- Opens `https://www.amazon.com/s?k=<keyword>`, extracts anchors containing `/dp/`, returns the first 3.

2) Star-filtered review scraping with pagination; fields include content, rating, date, reviewer
- File: `amazon_reviews.py` → `scrape_reviews_for_product(product_url, star, max_pages, headless=...)`
- Navigates to the product’s “See all reviews” page or constructs it from the ASIN.
- Applies the star filter by:
  - Clicking the star filter on the page if available; or
  - Using query params (`filterByStar`, `reviewerType`, `pageNumber`, etc.).
- Parses the DOM for reviews and includes robust fallbacks for layout variants.
- If DOM parsing returns none, falls back to Amazon’s reviews AJAX endpoint (HTML) and parses it.
- Extracted fields written to CSV/JSON.

3) Persisted login via interactive cookies capture
- File: `amazon_login.py` → `interactive_login(storage_state_path, headless=...)`
- Launches Chromium, navigates to sign-in, you complete login manually, then saves `storage_state.json`.
- Subsequent runs use that storage state to remain logged in.

## Notes & recommendations
- Prefer visible browser (omit `--headless`) for higher reliability on Amazon.
- Be mindful of Amazon’s Terms of Service; use responsibly.
- Secrets: `storage_state.json` and `output/` are ignored by `.gitignore`; do not commit personal data.
