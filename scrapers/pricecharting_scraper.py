"""Scraper for PriceCharting.com Pokemon card prices.

Uses offset-based pagination across all sets:
- Crawl 1: cards 0-100
- Crawl 2: cards 101-200
- etc.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from tqdm import tqdm

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

from config import CRAWL_STATUS_FILE, DataSource, PRICECHARTING_BASE, PRICECHARTING_DELAY
from crawl_status import CrawlStatus
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Pokemon TCG sets on PriceCharting (ordered by release)
ALL_SETS = [
    "pokemon-base-set",
    "pokemon-jungle",
    "pokemon-fossil",
    "pokemon-base-set-2",
    "pokemon-team-rocket",
    "pokemon-gym-heroes",
    "pokemon-gym-challenge",
    "pokemon-neo-genesis",
    "pokemon-neo-discovery",
    "pokemon-neo-revelation",
    "pokemon-neo-destiny",
    "pokemon-legendary-collection",
    "pokemon-expedition",
    "pokemon-aquapolis",
    "pokemon-skyridge",
    "pokemon-ex-ruby-sapphire",
    "pokemon-ex-sandstorm",
    "pokemon-ex-dragon",
    "pokemon-ex-team-magma-vs-team-aqua",
    "pokemon-ex-hidden-legends",
    "pokemon-ex-firered-leafgreen",
    "pokemon-ex-team-rocket-returns",
    "pokemon-ex-deoxys",
    "pokemon-ex-emerald",
    "pokemon-ex-unseen-forces",
    "pokemon-ex-delta-species",
    "pokemon-ex-legend-maker",
    "pokemon-ex-holon-phantoms",
    "pokemon-ex-crystal-guardians",
    "pokemon-ex-dragon-frontiers",
    "pokemon-ex-power-keepers",
]


class PriceChartingScraper(BaseScraper):
    """Scraper for PriceCharting Pokemon card prices."""

    SCRAPER_NAME = "pricecharting"
    OUTPUT_FILE = "pricecharting_cards.csv"

    def __init__(self, limit: int = 100, crawl_status: CrawlStatus | None = None):
        super().__init__(limit=limit, crawl_status=crawl_status)
        self.base_url = PRICECHARTING_BASE
        self.source = DataSource.PRICECHARTING

    def _parse_price(self, text: str) -> float | None:
        """Parse price string like '$3,820.21' to float."""
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.strip())
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _parse_card_row(self, row, set_slug: str) -> dict[str, Any] | None:
        """Parse a single table row into a card dict."""
        title_cell = row.find("td", class_="title")
        if not title_cell:
            return None

        link = title_cell.find("a")
        if not link:
            return None

        card_name = link.get_text(strip=True)
        card_url = link.get("href", "")
        card_id = title_cell.get("title", "")

        # Parse prices
        prices = {}
        for cell_class, key in [("used_price", "ungraded"), ("cib_price", "graded"), ("new_price", "sealed")]:
            cell = row.find("td", class_=cell_class)
            if cell:
                price_span = cell.find("span", class_="js-price")
                if price_span:
                    prices[key] = self._parse_price(price_span.get_text())

        # Parse card number from name
        card_number = None
        if match := re.search(r"#(\d+)", card_name):
            card_number = match.group(1)

        # Parse variants
        is_first_edition = "[1st Edition]" in card_name
        is_shadowless = "[Shadowless]" in card_name

        # Clean name
        clean_name = re.sub(r"\s*\[.*?\]\s*", " ", card_name)
        clean_name = re.sub(r"\s*#\d+\s*$", "", clean_name).strip()

        return {
            "pricecharting_id": card_id,
            "data_source": self.source.value,
            "card_name": clean_name,
            "full_name": card_name,
            "set_slug": set_slug,
            "set_name": set_slug.replace("pokemon-", "").replace("-", " ").title(),
            "card_number": card_number,
            "card_url": f"{self.base_url}{card_url}" if card_url else None,
            "is_first_edition": is_first_edition,
            "is_shadowless": is_shadowless,
            "price_ungraded": prices.get("ungraded"),
            "price_graded": prices.get("graded"),
            "price_sealed": prices.get("sealed"),
        }

    def _scrape_set(self, set_slug: str) -> list[dict[str, Any]]:
        """Scrape all cards from a single set."""
        url = f"{self.base_url}/console/{set_slug}"
        soup = self.fetch_html(url)
        if not soup:
            return []

        cards = []
        for row in soup.find_all("tr"):
            if card := self._parse_card_row(row, set_slug):
                cards.append(card)
        return cards

    def _scrape_batch(self, offset: int, limit: int) -> list[dict[str, Any]]:
        """Scrape cards across all sets, starting from offset."""
        cards = []
        cards_seen = 0

        for set_slug in tqdm(ALL_SETS, desc="Scraping"):
            if len(cards) >= limit:
                break

            set_cards = self._scrape_set(set_slug)

            for card in set_cards:
                if len(cards) >= limit:
                    break
                if cards_seen < offset:
                    cards_seen += 1
                    continue
                cards.append(card)
                cards_seen += 1

            time.sleep(PRICECHARTING_DELAY)

        return cards


def main():
    """Run the scraper standalone."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    crawl_status = CrawlStatus(CRAWL_STATUS_FILE)
    scraper = PriceChartingScraper(limit=100, crawl_status=crawl_status)
    df = scraper.scrape()

    if len(df) > 0:
        scraper.save(df)
        print(f"\n✓ Scraped {len(df)} cards")
        print(df[["card_name", "set_name", "price_ungraded"]].head(10))
    else:
        print("\nNo new cards to scrape")


if __name__ == "__main__":
    main()
