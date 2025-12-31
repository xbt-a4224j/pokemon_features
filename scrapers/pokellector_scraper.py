"""Scraper for Pokellector.com card database."""

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
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Set URLs on Pokellector
DEFAULT_SETS = [
    ("Base-Set-Expansion", "Base Set"),
    ("Jungle-Expansion", "Jungle"),
    ("Fossil-Expansion", "Fossil"),
    ("Base-Set-2-Expansion", "Base Set 2"),
    ("Team-Rocket-Expansion", "Team Rocket"),
]


class PokellectorScraper:
    """Scraper for Pokellector card database."""

    def __init__(self, sets: list[tuple[str, str]] | None = None, limit_per_set: int = 50):
        self.sets = sets or DEFAULT_SETS
        self.limit_per_set = limit_per_set
        self.base_url = "https://www.pokellector.com"
        self.source = DataSource.POKEMON_TCG_API  # Metadata source
        self.delay = 0.5  # Be polite

    def _fetch_page(self, url: str) -> BeautifulSoup | None:
        """Fetch and parse a page."""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)
        return None

    def _scrape_set(self, set_slug: str, set_name: str) -> list[dict[str, Any]]:
        """Scrape cards from a single set."""
        url = f"{self.base_url}/{set_slug}/"
        logger.info(f"Scraping: {set_name}")

        soup = self._fetch_page(url)
        if not soup:
            return []

        cards = []
        card_divs = soup.find_all("div", class_="card")

        for div in card_divs[:self.limit_per_set]:
            try:
                # Get card image and name from plaque
                plaque = div.find("div", class_="plaque")
                if not plaque:
                    continue

                plaque_text = plaque.get_text(strip=True)
                # Parse "#4 - Charizard" format
                match = re.match(r"#(\d+)\s*-\s*(.+)", plaque_text)
                if not match:
                    continue

                card_number = match.group(1)
                card_name = match.group(2)

                # Get image URL
                img = div.find("img")
                image_url = None
                if img:
                    image_url = img.get("data-src") or img.get("src")
                    if image_url:
                        # Convert thumb to full size
                        image_url = image_url.replace(".thumb.png", ".png")

                # Get link for more details
                link = div.find_parent("a")
                card_url = None
                if link:
                    card_url = self.base_url + link.get("href", "")

                cards.append({
                    "card_id": f"{set_slug}-{card_number}",
                    "data_source": "POKELLECTOR",
                    "card_name": card_name,
                    "card_number": card_number,
                    "set_name": set_name,
                    "set_slug": set_slug,
                    "image_url": image_url,
                    "card_url": card_url,
                })
            except Exception as e:
                logger.debug(f"Error parsing card: {e}")
                continue

        logger.info(f"Found {len(cards)} cards in {set_name}")
        return cards

    def scrape(self) -> pd.DataFrame:
        """Scrape cards from all configured sets."""
        logger.info(f"Starting Pokellector scrape ({len(self.sets)} sets)")

        all_cards = []

        for set_slug, set_name in tqdm(self.sets, desc="Scraping Pokellector"):
            cards = self._scrape_set(set_slug, set_name)
            all_cards.extend(cards)
            time.sleep(self.delay)

        logger.info(f"Scraped {len(all_cards)} cards from Pokellector")
        return pd.DataFrame(all_cards)

    def save(self, df: pd.DataFrame) -> str:
        """Save scraped data to CSV."""
        output_path = RAW_DATA_DIR / "pokellector_cards.csv"
        df.to_csv(output_path, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} cards to {output_path}")
        return str(output_path)


def main():
    """Run the scraper standalone."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    scraper = PokellectorScraper(limit_per_set=20)
    df = scraper.scrape()
    scraper.save(df)
    print(f"\n✓ Scraped {len(df)} cards from Pokellector")
    print(df[["card_name", "set_name", "card_number"]].head(10))


if __name__ == "__main__":
    main()
