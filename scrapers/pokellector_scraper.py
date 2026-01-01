"""Scraper for Pokellector.com card database."""

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
    DataSource,
    HEADERS,
    MAX_RETRIES,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
)
from crawl_status import CrawlStatus

logger = logging.getLogger(__name__)

# Set URLs on Pokellector (classic WotC + early ex era)
DEFAULT_SETS = [
    # Base era
    ("Base-Set-Expansion", "Base Set"),
    ("Jungle-Expansion", "Jungle"),
    ("Fossil-Expansion", "Fossil"),
    ("Base-Set-2-Expansion", "Base Set 2"),
    ("Team-Rocket-Expansion", "Team Rocket"),
    # Gym era
    ("Gym-Heroes-Expansion", "Gym Heroes"),
    ("Gym-Challenge-Expansion", "Gym Challenge"),
    # Neo era
    ("Neo-Genesis-Expansion", "Neo Genesis"),
    ("Neo-Discovery-Expansion", "Neo Discovery"),
    ("Neo-Revelation-Expansion", "Neo Revelation"),
    ("Neo-Destiny-Expansion", "Neo Destiny"),
    # Legendary/e-Card era
    ("Legendary-Collection-Expansion", "Legendary Collection"),
    ("Expedition-Base-Set-Expansion", "Expedition"),
    ("Aquapolis-Expansion", "Aquapolis"),
    ("Skyridge-Expansion", "Skyridge"),
    # Early EX era
    ("EX-Ruby-Sapphire-Expansion", "EX Ruby & Sapphire"),
    ("EX-Sandstorm-Expansion", "EX Sandstorm"),
    ("EX-Dragon-Expansion", "EX Dragon"),
    ("EX-Team-Magma-vs-Team-Aqua-Expansion", "EX Team Magma vs Team Aqua"),
    ("EX-Hidden-Legends-Expansion", "EX Hidden Legends"),
    ("EX-FireRed-LeafGreen-Expansion", "EX FireRed & LeafGreen"),
]


class PokellectorScraper:
    """Scraper for Pokellector card database."""

    SCRAPER_NAME = "pokellector"

    def __init__(self, sets: list[tuple[str, str]] | None = None, limit_per_set: int = 50, crawl_status: CrawlStatus | None = None):
        self.sets = sets or DEFAULT_SETS
        self.limit_per_set = limit_per_set
        self.base_url = "https://www.pokellector.com"
        self.source = DataSource.POKEMON_TCG_API  # Metadata source
        self.crawl_status = crawl_status
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
        sets_skipped = 0

        for set_slug, set_name in tqdm(self.sets, desc="Scraping Pokellector"):
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
