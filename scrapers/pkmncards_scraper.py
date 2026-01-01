"""Scraper for PKMNCards.com card database."""

import logging
import re
import time
from pathlib import Path
from typing import Any

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

# Classic Pokemon TCG sets (WotC + early ex era)
DEFAULT_SETS = [
    # Base era
    ("base-set", "Base Set"),
    ("jungle", "Jungle"),
    ("fossil", "Fossil"),
    ("base-set-2", "Base Set 2"),
    ("team-rocket", "Team Rocket"),
    # Gym era
    ("gym-heroes", "Gym Heroes"),
    ("gym-challenge", "Gym Challenge"),
    # Neo era
    ("neo-genesis", "Neo Genesis"),
    ("neo-discovery", "Neo Discovery"),
    ("neo-revelation", "Neo Revelation"),
    ("neo-destiny", "Neo Destiny"),
    # Legendary/e-Card era
    ("legendary-collection", "Legendary Collection"),
    ("expedition-base-set", "Expedition"),
    ("aquapolis", "Aquapolis"),
    ("skyridge", "Skyridge"),
    # Early EX era
    ("ex-ruby-sapphire", "EX Ruby & Sapphire"),
    ("ex-sandstorm", "EX Sandstorm"),
    ("ex-dragon", "EX Dragon"),
    ("ex-team-magma-vs-team-aqua", "EX Team Magma vs Team Aqua"),
    ("ex-hidden-legends", "EX Hidden Legends"),
    ("ex-firered-leafgreen", "EX FireRed & LeafGreen"),
]


class PKMNCardsScraper:
    """Scraper for PKMNCards card database with high-quality images."""

    SCRAPER_NAME = "pkmncards"

    def __init__(self, sets: list[tuple[str, str]] | None = None, limit_per_set: int = 50, crawl_status: CrawlStatus | None = None):
        self.sets = sets or DEFAULT_SETS
        self.limit_per_set = limit_per_set
        self.base_url = "https://pkmncards.com"
        self.crawl_status = crawl_status
        self.delay = 0.5

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
        url = f"{self.base_url}/set/{set_slug}/"
        logger.info(f"Scraping: {set_name}")

        soup = self._fetch_page(url)
        if not soup:
            return []

        cards = []
        articles = soup.find_all("article", class_="type-pkmn_card")

        for article in articles[:self.limit_per_set]:
            try:
                link = article.find("a", class_="card-image-link")
                if not link:
                    continue

                # Parse title like "Charizard · Base Set (BS) #4"
                title = link.get("title", "")
                match = re.match(r"(.+?)\s*·\s*(.+?)\s*\((\w+)\)\s*#(\d+)", title)
                if not match:
                    continue

                card_name = match.group(1).strip()
                set_full = match.group(2).strip()
                set_code = match.group(3).strip()
                card_number = match.group(4).strip()

                # Get image
                img = article.find("img", class_="card-image")
                image_url = None
                if img:
                    image_url = img.get("src")

                card_url = link.get("href")

                cards.append({
                    "card_id": f"{set_code.lower()}-{card_number}",
                    "data_source": "PKMNCARDS",
                    "card_name": card_name,
                    "card_number": card_number,
                    "set_name": set_name,
                    "set_code": set_code,
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
        logger.info(f"Starting PKMNCards scrape ({len(self.sets)} sets)")

        all_cards = []
        sets_skipped = 0

        for set_slug, set_name in tqdm(self.sets, desc="Scraping PKMNCards"):
            # Skip already-completed sets
            if self.crawl_status and self.crawl_status.is_set_completed(self.SCRAPER_NAME, set_slug):
                sets_skipped += 1
                logger.debug(f"Skipping already-scraped set: {set_name}")
                continue

            cards = self._scrape_set(set_slug, set_name)
            all_cards.extend(cards)

            # Mark set as completed
            if self.crawl_status and cards:
                self.crawl_status.update(
                    self.SCRAPER_NAME,
                    completed_set=set_slug,
                    records_added=len(cards),
                )

            time.sleep(self.delay)

        if sets_skipped > 0:
            logger.info(f"Skipped {sets_skipped} previously scraped sets")
        logger.info(f"Scraped {len(all_cards)} cards from PKMNCards")
        return pd.DataFrame(all_cards)

    def save(self, df: pd.DataFrame) -> str:
        """Save scraped data to CSV."""
        output_path = RAW_DATA_DIR / "pkmncards_cards.csv"
        df.to_csv(output_path, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} cards to {output_path}")
        return str(output_path)


def main():
    """Run the scraper standalone."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    scraper = PKMNCardsScraper(limit_per_set=20)
    df = scraper.scrape()
    scraper.save(df)
    print(f"\n✓ Scraped {len(df)} cards from PKMNCards")
    print(df[["card_name", "set_name", "card_number"]].head(10))


if __name__ == "__main__":
    main()
