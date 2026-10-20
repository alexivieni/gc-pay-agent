"""Download public Government of Canada collective agreements for the knowledge base.

Saves only the agreement itself (text and pay tables), without the site's
menus and footer, as one clean HTML file per agreement in ./docs.

    pip install requests beautifulsoup4
    python get_agreements.py

If canada.ca won't respond to the script, save the pages from your browser
instead (Ctrl+S, "Webpage, HTML only") into a folder called raw/, named
pa.html, ec.html and it.html, and run the script again. It uses saved pages
when they're there.
"""

import pathlib
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.canada.ca/en/treasury-board-secretariat/topics/pay/collective-agreements/{}.html"

# Add more groups here (e.g. "ct", "sh", "fb"); see the full list at
# https://www.canada.ca/en/treasury-board-secretariat/topics/pay/collective-agreements.html
AGREEMENTS = {
    "pa": "Program and Administrative Services (PA)",
    "ec": "Economics and Social Science Services (EC)",
    "it": "Information Technology (IT)",
}

OUT_DIR = pathlib.Path("docs")
RAW_DIR = pathlib.Path("raw")  # optional: pages you saved from your browser

# Standard browser headers; canada.ca can stall requests that look automated
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}
ATTEMPTS = 3

# Parts of the canada.ca page that aren't the agreement
JUNK = ["script", "style", "nav", "form", "button", "noscript"]
JUNK_SELECTORS = ".pagedetails, #wb-info, .gc-subway"


def get_page(code: str) -> str | None:
    """The page's HTML: a copy saved in raw/ if there is one, otherwise downloaded."""
    saved = RAW_DIR / f"{code}.html"
    if saved.exists():
        print(f"  using saved page {saved}")
        return saved.read_text(encoding="utf-8", errors="replace")

    url = BASE_URL.format(code)
    for attempt in range(1, ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=(15, 90))
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as err:
            print(f"  attempt {attempt} of {ATTEMPTS} failed ({err.__class__.__name__})")
            if attempt < ATTEMPTS:
                time.sleep(5 * attempt)
    return None


def clean_and_save(code: str, name: str, page: str) -> None:
    soup = BeautifulSoup(page, "html.parser")
    content = soup.find("main") or soup.body
    for tag in content.find_all(JUNK):
        tag.decompose()
    for tag in content.select(JUNK_SELECTORS):
        tag.decompose()

    url = BASE_URL.format(code)
    html = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{name} collective agreement</title>\n"
        f"<meta name=\"source\" content=\"{url}\">\n"
        f"</head>\n<body>\n{content}\n</body>\n</html>\n"
    )
    path = OUT_DIR / f"{code}-collective-agreement.html"
    path.write_text(html, encoding="utf-8")

    chars = len(content.get_text(" ", strip=True))
    tables = len(content.find_all("table"))
    print(f"  {chars:,} characters, {tables} tables -> {path}")


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    failed = []
    for code, name in AGREEMENTS.items():
        print(name)
        page = get_page(code)
        if page is None:
            failed.append(code)
            continue
        clean_and_save(code, name, page)

    if failed:
        print("\nCouldn't download: " + ", ".join(c.upper() for c in failed))
        print(f"Save these pages from your browser into {RAW_DIR.resolve()} (Ctrl+S, 'Webpage, HTML only'):")
        for code in failed:
            print(f"  {BASE_URL.format(code)}  ->  {RAW_DIR / (code + '.html')}")
        print("Then run this script again.")
        sys.exit(1)

    print(f"\nDone. Agreements saved in {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
