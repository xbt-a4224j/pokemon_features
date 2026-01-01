"""Scraper for Pokemon TCG API (pokemontcg.io)."""

import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tqdm import tqdm

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    CRAWL_STATUS_FILE,
    DEMO_CARD_LIMIT,
    DataSource,
    HEADERS,
    MAX_RETRIES,
    POKEMON_API_BASE,
    POKEMON_API_DELAY,
    POKEMON_TCG_API_KEY,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
)
from crawl_status import CrawlStatus

logger = logging.getLogger(__name__)


class PokemonTCGScraper:
    """Scraper for Pokemon TCG API."""

    SCRAPER_NAME = "pokemon_tcg"

    def __init__(self, limit: int = DEMO_CARD_LIMIT, crawl_status: CrawlStatus | None = None):
        self.limit = limit
        self.base_url = f"{POKEMON_API_BASE}/cards"
        self.source = DataSource.POKEMON_TCG_API
        self.headers = {**HEADERS}
        self.crawl_status = crawl_status
        if POKEMON_TCG_API_KEY:
            self.headers["X-Api-Key"] = POKEMON_TCG_API_KEY

    def _fetch_page(self, page: int, page_size: int = 50) -> dict[str, Any] | None:
        """Fetch a single page of cards with retry logic."""
        params = {"page": page, "pageSize": page_size}

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    self.base_url,
                    params=params,
                    headers=self.headers,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)  # Exponential backoff
                else:
                    logger.error(f"Failed to fetch page {page} after {MAX_RETRIES} attempts")
                    return None

    def _parse_card(self, card: dict[str, Any]) -> dict[str, Any]:
        """Parse a single card into flat structure."""
        tcgplayer = card.get("tcgplayer", {}) or {}
        prices = tcgplayer.get("prices", {}) or {}

        # Get first available price type (normal, holofoil, etc.)
        price_data = {}
        for price_type in ["normal", "holofoil", "reverseHolofoil", "1stEditionHolofoil"]:
            if price_type in prices:
                price_data = prices[price_type]
                break

        set_data = card.get("set", {}) or {}

        return {
            "id": card.get("id"),
            "data_source": self.source.value,
            "name": card.get("name"),
            "supertype": card.get("supertype"),
            "subtypes": ",".join(card.get("subtypes", []) or []),
            "hp": card.get("hp"),
            "types": ",".join(card.get("types", []) or []),
            "evolvesFrom": card.get("evolvesFrom"),
            "set_id": set_data.get("id"),
            "set_name": set_data.get("name"),
            "set_series": set_data.get("series"),
            "set_release_date": set_data.get("releaseDate"),
            "number": card.get("number"),
            "artist": card.get("artist"),
            "rarity": card.get("rarity"),
            "nationalPokedexNumbers": ",".join(
                str(n) for n in (card.get("nationalPokedexNumbers", []) or [])
            ),
            "tcgplayer_url": tcgplayer.get("url"),
            "tcgplayer_price_low": price_data.get("low"),
            "tcgplayer_price_mid": price_data.get("mid"),
            "tcgplayer_price_high": price_data.get("high"),
            "tcgplayer_price_market": price_data.get("market"),
            "tcgplayer_updated_at": tcgplayer.get("updatedAt"),
            "image_small": card.get("images", {}).get("small"),
            "image_large": card.get("images", {}).get("large"),
        }

    def scrape(self) -> pd.DataFrame:
        """Scrape cards from Pokemon TCG API."""
        logger.info(f"Starting Pokemon TCG API scrape (limit: {self.limit})")

        cards = []
        page_size = min(50, self.limit)
        skipped = 0
        new_card_ids = []

        # Resume from last page if we have crawl status
        start_page = 1
        if self.crawl_status:
            start_page = max(1, self.crawl_status.get_resume_page(self.SCRAPER_NAME))
            if start_page > 1:
                logger.info(f"Resuming from page {start_page}")

        page = start_page

        with tqdm(total=self.limit, desc="Fetching cards") as pbar:
            while len(cards) < self.limit:
                data = self._fetch_page(page, page_size)
                if not data or not data.get("data"):
                    logger.warning(f"No data returned for page {page}")
                    break

                for card in data["data"]:
                    if len(cards) >= self.limit:
                        break

                    card_id = card.get("id")

                    # Skip already-scraped cards
                    if self.crawl_status and card_id and self.crawl_status.is_id_scraped(self.SCRAPER_NAME, card_id):
                        skipped += 1
                        continue

                    parsed = self._parse_card(card)
                    cards.append(parsed)
                    if card_id:
                        new_card_ids.append(card_id)
                    pbar.update(1)

                # Update crawl status after each page
                if self.crawl_status:
                    self.crawl_status.update(
                        self.SCRAPER_NAME,
                        last_page=page,
                        scraped_ids=new_card_ids,
                    )
                    new_card_ids = []

                # Check if we've reached the end
                total_count = data.get("totalCount", 0)
                if page * page_size >= total_count:
                    break

                page += 1
                time.sleep(POKEMON_API_DELAY)

        # Final status update
        if self.crawl_status and cards:
            self.crawl_status.update(
                self.SCRAPER_NAME,
                records_added=len(cards),
                last_record_id=cards[-1].get("id") if cards else None,
            )

        if skipped > 0:
            logger.info(f"Skipped {skipped} previously scraped cards")
        logger.info(f"Scraped {len(cards)} new cards from Pokemon TCG API")
        return pd.DataFrame(cards)

    def save(self, df: pd.DataFrame) -> str:
        """Save scraped data to CSV."""
        output_path = RAW_DATA_DIR / "pokemon_tcg_cards.csv"
        df.to_csv(output_path, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} cards to {output_path}")
        return str(output_path)


def main():
    """Run the scraper standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    scraper = PokemonTCGScraper()
    df = scraper.scrape()
    scraper.save(df)
    print(f"\n✓ Scraped {len(df)} cards")


if __name__ == "__main__":
    main()
