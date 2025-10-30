import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
STORAGE_STATE_PATH = ROOT_DIR / "storage_state.json"

ASIN_PATTERNS = [
    re.compile(r"/dp/([A-Z0-9]{10})"),
    re.compile(r"/gp/product/([A-Z0-9]{10})"),
    re.compile(r"/product-reviews/([A-Z0-9]{10})"),
]


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def write_json(items: List[Dict[str, Any]], filename: str) -> Path:
    ensure_output_dir()
    path = OUTPUT_DIR / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return path


def write_csv(items: List[Dict[str, Any]], filename: str) -> Path:
    ensure_output_dir()
    path = OUTPUT_DIR / filename
    df = pd.DataFrame(items)
    df.to_csv(path, index=False)
    return path


def write_text(content: str, filename: str) -> Path:
    ensure_output_dir()
    path = OUTPUT_DIR / filename
    with path.open("w", encoding="utf-8") as f:
        f.write(content)
    return path


def normalize_star_input(star: str) -> int:
    star = star.strip()
    if star.endswith("星"):
        star = star[:-1]
    try:
        value = int(star)
    except ValueError:
        raise ValueError("星级必须为 1-5 的整数")
    if value < 1 or value > 5:
        raise ValueError("星级必须为 1-5 的整数")
    return value


def extract_host_and_asin_from_url(url: str) -> Tuple[str, Optional[str]]:
    # Replace full-width percent '％' with '%'
    url = url.replace("％", "%")
    parsed = urlparse(url)
    host = parsed.netloc or "www.amazon.com"
    asin: Optional[str] = None
    for rgx in ASIN_PATTERNS:
        m = rgx.search(url)
        if m:
            asin = m.group(1)
            break
    return host, asin


def normalize_product_url(url: str) -> str:
    host, asin = extract_host_and_asin_from_url(url)
    if asin:
        return f"https://{host}/dp/{asin}"
    # Fallback: return original with full-width percent fixed
    return url.replace("％", "%")
