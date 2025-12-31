"""Scraper for PriceCharting.com Pokemon card prices."""

import logging
import re
import time
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

import sys
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from config import (
    DataSource,
    HEADERS,
    MAX_RETRIES,
    PRICECHARTING_BASE,
    PRICECHARTING_DELAY,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Popular sets for demo - add more as needed
DEFAULT_SETS = [
    "pokemon-base-set",
    "pokemon-jungle",
    "pokemon-fossil",
    "pokemon-base-set-2",
    "pokemon-team-rocket",
]


class PriceChartingScraper:
    """Scraper for PriceCharting Pokemon card prices."""

    def __init__(self, sets: list[str] | None = None, limit_per_set: int = 50):
        self.sets = sets or DEFAULT_SETS
        self.limit_per_set = limit_per_set
        self.base_url = PRICECHARTING_BASE
        self.source = DataSource.PRICECHARTING

    def _fetch_page(self, url: str) -> BeautifulSoup | None:
        """Fetch and parse a page with retry logic."""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)
                else:
                    logger.error(f"Failed to fetch {url} after {MAX_RETRIES} attempts")
                    return None

    def _parse_price(self, text: str) -> float | None:
        """Parse price string like '$3,820.21' to float."""
        if not text:
            return None
        # Remove currency symbols and commas
        cleaned = re.sub(r"[^\d.]", "", text.strip())
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _scrape_set(self, set_slug: str) -> list[dict[str, Any]]:
        """Scrape all cards from a single set."""
        url = f"{self.base_url}/console/{set_slug}"
        logger.info(f"Scraping set: {set_slug}")

        soup = self._fetch_page(url)
        if not soup:
            return []

        cards = []
        rows = soup.find_all("tr")

        for row in rows:
            # Skip header rows
            title_cell = row.find("td", class_="title")
            if not title_cell:
                continue

            # Get card link and name
            link = title_cell.find("a")
            if not link:
                continue

            card_name = link.get_text(strip=True)
            card_url = link.get("href", "")
            card_id = title_cell.get("title", "")

            # Get prices
            used_price_cell = row.find("td", class_="used_price")
            cib_price_cell = row.find("td", class_="cib_price")
            new_price_cell = row.find("td", class_="new_price")

            used_price = None
            cib_price = None
            new_price = None

            if used_price_cell:
                price_span = used_price_cell.find("span", class_="js-price")
                if price_span:
                    used_price = self._parse_price(price_span.get_text())

            if cib_price_cell:
                price_span = cib_price_cell.find("span", class_="js-price")
                if price_span:
                    cib_price = self._parse_price(price_span.get_text())

            if new_price_cell:
                price_span = new_price_cell.find("span", class_="js-price")
                if price_span:
                    new_price = self._parse_price(price_span.get_text())

            # Parse card number from name (e.g., "Charizard #4" -> 4)
            card_number = None
            number_match = re.search(r"#(\d+)", card_name)
            if number_match:
                card_number = number_match.group(1)

            # Parse variant info
            is_first_edition = "[1st Edition]" in card_name
            is_shadowless = "[Shadowless]" in card_name

            # Clean card name (remove variant tags)
            clean_name = re.sub(r"\s*\[.*?\]\s*", " ", card_name)
            clean_name = re.sub(r"\s*#\d+\s*$", "", clean_name).strip()

            cards.append({
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
                "price_ungraded": used_price,
                "price_graded": cib_price,
                "price_sealed": new_price,
            })

            if len(cards) >= self.limit_per_set:
                break

        logger.info(f"Scraped {len(cards)} cards from {set_slug}")
        return cards

    def scrape(self) -> pd.DataFrame:
        """Scrape cards from all configured sets."""
        logger.info(f"Starting PriceCharting scrape ({len(self.sets)} sets)")

        all_cards = []

        for set_slug in tqdm(self.sets, desc="Scraping sets"):
            cards = self._scrape_set(set_slug)
            all_cards.extend(cards)
            time.sleep(PRICECHARTING_DELAY)

        logger.info(f"Scraped {len(all_cards)} total cards from PriceCharting")
        return pd.DataFrame(all_cards)

    def save(self, df: pd.DataFrame) -> str:
        """Save scraped data to CSV."""
        output_path = RAW_DATA_DIR / "pricecharting_cards.csv"
        df.to_csv(output_path, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} cards to {output_path}")
        return str(output_path)


def main():
    """Run the scraper standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    scraper = PriceChartingScraper(limit_per_set=20)
    df = scraper.scrape()
    scraper.save(df)
    print(f"\n✓ Scraped {len(df)} cards from PriceCharting")
    print(df[["card_name", "set_name", "price_ungraded", "price_graded"]].head(10))


if __name__ == "__main__":
    main()
