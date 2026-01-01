"""Scraper for card pricing via eBay completed listings analysis.

This scraper searches for recently sold Pokemon cards and extracts
actual market prices from completed transactions.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    CRAWL_STATUS_FILE,
    HEADERS,
    MAX_RETRIES,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
)
from crawl_status import CrawlStatus

logger = logging.getLogger(__name__)

# High-value cards to search for sold prices
DEFAULT_SEARCHES = [
    ("charizard base set holo", "Charizard", "Base Set"),
    ("blastoise base set holo", "Blastoise", "Base Set"),
    ("venusaur base set holo", "Venusaur", "Base Set"),
    ("pikachu base set", "Pikachu", "Base Set"),
    ("mewtwo base set holo", "Mewtwo", "Base Set"),
    ("gyarados base set holo", "Gyarados", "Base Set"),
    ("alakazam base set holo", "Alakazam", "Base Set"),
    ("charizard jungle", "Charizard", "Jungle"),
    ("flareon jungle holo", "Flareon", "Jungle"),
    ("jolteon jungle holo", "Jolteon", "Jungle"),
    ("vaporeon jungle holo", "Vaporeon", "Jungle"),
    ("dragonite fossil holo", "Dragonite", "Fossil"),
    ("gengar fossil holo", "Gengar", "Fossil"),
    ("moltres fossil holo", "Moltres", "Fossil"),
    ("dark charizard team rocket", "Dark Charizard", "Team Rocket"),
]


class SoldPricesScraper:
    """Scraper for completed/sold Pokemon card listings."""

    SCRAPER_NAME = "sold_prices"

    def __init__(self, searches: list[tuple[str, str, str]] | None = None, crawl_status: CrawlStatus | None = None):
        self.searches = searches or DEFAULT_SEARCHES
        self.crawl_status = crawl_status
        self.delay = 0.3  # Reduced from 1.0 for faster resume runs
        self.start_time = None
        self.time_budget = 30  # Max seconds for this scraper in resume mode

    def _fetch_page(self, url: str) -> BeautifulSoup | None:
        """Fetch and parse a page."""
        headers = {
            **HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)
        return None

    def _parse_price(self, text: str) -> float | None:
        """Parse price string to float."""
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.strip())
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _search_mavin(self, query: str, card_name: str, set_name: str) -> list[dict[str, Any]]:
        """Search Mavin.io for sold prices."""
        encoded = quote_plus(f"pokemon {query}")
        url = f"https://mavin.io/search?q={encoded}"

        logger.info(f"Searching: {query}")
        soup = self._fetch_page(url)
        if not soup:
            return []

        results = []

        # Look for sold items
        items = soup.find_all("div", class_="sold-item") or soup.find_all("div", class_="search-item")

        for item in items[:5]:  # Top 5 results per search
            try:
                title_el = item.find(class_="item-title") or item.find("a")
                price_el = item.find(class_="item-price") or item.find(class_="sold-price")

                if not title_el or not price_el:
                    continue

                title = title_el.get_text(strip=True)
                price = self._parse_price(price_el.get_text())

                if price and price > 0:
                    results.append({
                        "search_query": query,
                        "card_name": card_name,
                        "set_name": set_name,
                        "listing_title": title[:100],
                        "sold_price": price,
                        "data_source": "MAVIN",
                    })
            except Exception as e:
                logger.debug(f"Error parsing item: {e}")
                continue

        return results

    def _search_collectr(self, query: str, card_name: str, set_name: str) -> list[dict[str, Any]]:
        """Search Collectr for price estimates."""
        encoded = quote_plus(f"pokemon {query}")
        url = f"https://www.collectr.com/search?q={encoded}"

        soup = self._fetch_page(url)
        if not soup:
            return []

        results = []

        # Collectr price estimates
        items = soup.find_all("div", class_="card-item") or soup.find_all("article")

        for item in items[:5]:
            try:
                title_el = item.find(class_="title") or item.find("h3")
                price_el = item.find(class_="price") or item.find(class_="value")

                if not price_el:
                    continue

                title = title_el.get_text(strip=True) if title_el else query
                price = self._parse_price(price_el.get_text())

                if price and price > 0:
                    results.append({
                        "search_query": query,
                        "card_name": card_name,
                        "set_name": set_name,
                        "listing_title": title[:100],
                        "sold_price": price,
                        "data_source": "COLLECTR",
                    })
            except Exception:
                continue

        return results

    def scrape(self) -> pd.DataFrame:
        """Scrape sold prices for configured searches."""
        logger.info(f"Starting sold prices scrape ({len(self.searches)} searches)")

        all_results = []
        searches_skipped = 0

        for query, card_name, set_name in tqdm(self.searches, desc="Searching sold prices"):
            # Skip already-searched queries
            if self.crawl_status and self.crawl_status.is_id_scraped(self.SCRAPER_NAME, query):
                searches_skipped += 1
                logger.debug(f"Skipping already-searched: {query}")
                continue

            # Try Mavin first (better for sold prices)
            results = self._search_mavin(query, card_name, set_name)

            if not results:
                # Fallback to Collectr
                results = self._search_collectr(query, card_name, set_name)

            all_results.extend(results)

            # Mark search as completed
            if self.crawl_status:
                self.crawl_status.update(
                    self.SCRAPER_NAME,
                    scraped_ids=[query],
                    records_added=len(results),
                )

            time.sleep(self.delay)

        if searches_skipped > 0:
            logger.info(f"Skipped {searches_skipped} previously searched queries")
        logger.info(f"Found {len(all_results)} sold price records")
        return pd.DataFrame(all_results)

    def save(self, df: pd.DataFrame) -> str:
        """Save scraped data to CSV."""
        output_path = RAW_DATA_DIR / "sold_prices.csv"
        df.to_csv(output_path, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} records to {output_path}")
        return str(output_path)


def main():
    """Run the scraper standalone."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Test with fewer searches
    scraper = SoldPricesScraper(searches=DEFAULT_SEARCHES[:5])
    df = scraper.scrape()

    if len(df) > 0:
        scraper.save(df)
        print(f"\n✓ Found {len(df)} sold price records")
        print(df[["card_name", "set_name", "sold_price", "data_source"]].head(10))
    else:
        print("\n⚠ No sold prices found")


if __name__ == "__main__":
    main()
