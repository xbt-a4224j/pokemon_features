"""Base scraper with shared functionality.

All scrapers extend BaseScraper and implement:
- SCRAPER_NAME: str - unique identifier for crawl status
- OUTPUT_FILE: str - CSV filename in raw_data/
- _scrape_batch() - fetch and parse one batch of cards

The base class provides:
- HTTP fetching with retry logic
- Offset-based resume (via CrawlStatus)
- Save with append + deduplication
"""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import HEADERS, MAX_RETRIES, RAW_DATA_DIR, REQUEST_TIMEOUT
from crawl_status import CrawlStatus

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all card scrapers.

    Subclasses must define:
        SCRAPER_NAME: Unique identifier for tracking progress
        OUTPUT_FILE: Filename for raw data CSV
        _scrape_batch(): Implementation of actual scraping logic
    """

    SCRAPER_NAME: str = ""
    OUTPUT_FILE: str = ""

    def __init__(self, limit: int = 100, crawl_status: CrawlStatus | None = None):
        self.limit = limit
        self.crawl_status = crawl_status

    def fetch_html(self, url: str) -> BeautifulSoup | None:
        """Fetch URL and return parsed HTML. Retries on failure."""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        logger.error(f"Failed to fetch {url}")
        return None

    def fetch_json(self, url: str, headers: dict | None = None) -> dict | None:
        """Fetch URL and return JSON. Retries on failure."""
        req_headers = {**HEADERS, **(headers or {})}
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, headers=req_headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        logger.error(f"Failed to fetch {url}")
        return None

    def get_offset(self) -> int:
        """Get current offset from crawl status."""
        if self.crawl_status:
            return self.crawl_status.get_offset(self.SCRAPER_NAME)
        return 0

    def set_offset(self, offset: int) -> None:
        """Update offset in crawl status."""
        if self.crawl_status:
            self.crawl_status.set_offset(self.SCRAPER_NAME, offset)

    @abstractmethod
    def _scrape_batch(self, offset: int, limit: int) -> list[dict[str, Any]]:
        """Scrape a batch of cards starting from offset.

        Args:
            offset: Number of cards to skip
            limit: Maximum cards to return

        Returns:
            List of card dicts with standardized keys
        """
        pass

    def scrape(self) -> pd.DataFrame:
        """Scrape cards using offset-based pagination.

        Resumes from last offset, fetches up to self.limit cards.
        """
        offset = self.get_offset()
        logger.info(f"Starting {self.SCRAPER_NAME} scrape (offset={offset}, limit={self.limit})")

        cards = self._scrape_batch(offset, self.limit)

        if cards and self.crawl_status:
            self.set_offset(offset + len(cards))
            logger.info(f"Updated offset: {offset} → {offset + len(cards)}")

        logger.info(f"Scraped {len(cards)} cards")
        return pd.DataFrame(cards)

    def save(self, df: pd.DataFrame) -> str:
        """Save scraped data to CSV, appending to existing and deduplicating."""
        output_path = RAW_DATA_DIR / self.OUTPUT_FILE

        if output_path.exists():
            existing = pd.read_csv(output_path)
            df = pd.concat([existing, df], ignore_index=True)
            # Deduplicate by first column (assumed to be ID)
            id_col = df.columns[0]
            df = df.drop_duplicates(subset=[id_col], keep="last")

        df.to_csv(output_path, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} cards to {output_path}")
        return str(output_path)
