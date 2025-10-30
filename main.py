import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from utils import STORAGE_STATE_PATH, write_csv, write_json, normalize_star_input, normalize_product_url
from amazon_login import interactive_login
from amazon_search import search_top_products
from amazon_reviews import scrape_reviews_for_product


def run_login(headless: bool) -> None:
    interactive_login(storage_state_path=STORAGE_STATE_PATH, headless=headless)


def _normalize_if_needed(url: str) -> str:
    u = url.strip()
    if "product-reviews/" in u:
        return u  # keep review page URL as-is (retains filters)
    return normalize_product_url(u)


def run_scrape_interactive(headless: bool, urls_arg: str | None = None, pages: int = 2, limit: int = 3) -> None:
    product_links: List[str] = []
    if urls_arg:
        product_links = [_normalize_if_needed(u) for u in urls_arg.split(",") if u.strip()]
    else:
        keyword = input("请输入产品关键词 (留空以直接粘贴链接): ").strip()
        if not keyword:
            raw_urls = input("请输入产品详情页链接(逗号分隔): ").strip()
            product_links = [_normalize_if_needed(u) for u in raw_urls.split(",") if u.strip()]
        else:
            print(f"正在搜索: {keyword} ...")
            product_links = search_top_products(keyword, limit=limit, headless=headless)
            product_links = [normalize_product_url(u) for u in product_links]

    if not product_links:
        print("未获取到产品链接。")
        return

    product_links = product_links[:limit]

    print("产品链接(标准化):")
    for i, link in enumerate(product_links, 1):
        print(f"{i}. {link}")

    star_raw = input("请输入评论星级(1-5，例如 5 或 5星): ").strip()
    star = normalize_star_input(star_raw)

    all_rows: List[Dict] = []
    for idx, link in enumerate(product_links, 1):
        print(f"抓取第 {idx} 个产品的评论(星级 {star})，页数: {pages} ...")
        rows = scrape_reviews_for_product(link, star=star, max_pages=pages, headless=headless)
        print(f"第 {idx} 个产品抓取到 {len(rows)} 条评论")
        for r in rows:
            r["product_index"] = idx
            r["product_url"] = link
        all_rows.extend(rows)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"amazon_reviews_{star}star_{timestamp}"
    json_path = write_json(all_rows, base_name + ".json")
    csv_path = write_csv(all_rows, base_name + ".csv")
    print(f"保存完成: {json_path}\n{csv_path}\n共保存 {len(all_rows)} 条评论")


def main():
    parser = argparse.ArgumentParser(description="Amazon crawler: login, search, reviews")
    parser.add_argument("--login", action="store_true", help="Interactive login and save storage state")
    parser.add_argument("--headless", action="store_true", help="Run browser headless (default off)")
    parser.add_argument("--urls", type=str, default=None, help="Comma-separated product detail or review URLs to scrape directly")
    parser.add_argument("--pages", type=int, default=2, help="Number of review pages per product")
    parser.add_argument("--limit", type=int, default=3, help="Max number of products to scrape")
    args = parser.parse_args()

    if args.login:
        run_login(headless=args.headless)
    else:
        if not STORAGE_STATE_PATH.exists():
            print("尚未登录。将先打开登录流程。")
            run_login(headless=args.headless)
        run_scrape_interactive(headless=args.headless, urls_arg=args.urls, pages=args.pages, limit=args.limit)


if __name__ == "__main__":
    main()
