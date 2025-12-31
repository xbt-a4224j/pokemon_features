"""Scraper for PSA Population Report data.

NOTE: PSA aggressively blocks scrapers. This scraper uses very conservative
rate limiting (4 seconds between requests) and should be used sparingly.
Consider caching results and only scraping high-value cards.
"""

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
    PSA_BASE,
    PSA_DELAY,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

# High-value cards to search for PSA population data
DEFAULT_CARDS = [
    "charizard base set",
    "blastoise base set",
    "venusaur base set",
    "pikachu base set",
    "mewtwo base set",
    "gyarados base set",
    "alakazam base set",
    "machamp base set",
    "lugia neo genesis",
    "espeon neo discovery",
]


class PSAScraper:
    """Scraper for PSA Population Report data."""

    def __init__(self, cards: list[str] | None = None):
        self.cards = cards or DEFAULT_CARDS
        self.base_url = PSA_BASE
        self.source = DataSource.PSA
        self.session = requests.Session()
        self.session.headers.update({
            **HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def _fetch_page(self, url: str) -> BeautifulSoup | None:
        """Fetch and parse a page with retry logic."""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)

                # Check for maintenance page
                if "temporarily unavailable" in response.text.lower():
                    logger.warning("PSA site is under maintenance")
                    return None

                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)
                else:
                    logger.error(f"Failed to fetch {url} after {MAX_RETRIES} attempts")
                    return None

    def _parse_population_table(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Parse PSA population table from search results."""
        results = []

        # Look for population table - structure may vary
        # Common patterns: table.population-table, div.pop-report, etc.
        table = soup.find("table", class_=re.compile(r"population|pop-report|results"))

        if not table:
            # Try finding any table with grade columns
            tables = soup.find_all("table")
            for t in tables:
                headers = t.find_all("th")
                header_text = " ".join(h.get_text() for h in headers).lower()
                if "grade" in header_text or "pop" in header_text:
                    table = t
                    break

        if not table:
            logger.warning("Could not find population table")
            return results

        rows = table.find_all("tr")[1:]  # Skip header

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            try:
                card_name = cols[0].get_text(strip=True)

                # Extract grade populations - typically columns for grades 1-10
                populations = {}
                for i, col in enumerate(cols[1:], start=1):
                    text = col.get_text(strip=True).replace(",", "")
                    if text.isdigit():
                        populations[f"grade_{i}"] = int(text)

                # Calculate totals
                total_graded = sum(populations.values())
                pop_10 = populations.get("grade_10", 0)
                pop_9 = populations.get("grade_9", 0)

                results.append({
                    "card_name": card_name,
                    "psa_population_total": total_graded,
                    "psa_population_grade_10": pop_10,
                    "psa_population_grade_9": pop_9,
                    "psa_population_grade_8": populations.get("grade_8", 0),
                    "psa_population_grade_7": populations.get("grade_7", 0),
                    "psa_grade_distribution": populations,
                })
            except Exception as e:
                logger.debug(f"Error parsing row: {e}")
                continue

        return results

    def _search_card(self, card_query: str) -> list[dict[str, Any]]:
        """Search for a card and extract PSA population data."""
        # URL encode the query
        encoded_query = requests.utils.quote(card_query)
        url = f"{self.base_url}/pop/search?search={encoded_query}&category=pokemon"

        logger.info(f"Searching PSA for: {card_query}")

        soup = self._fetch_page(url)
        if not soup:
            return []

        results = self._parse_population_table(soup)

        # Add search query context to results
        for r in results:
            r["search_query"] = card_query
            r["data_source"] = self.source.value

        return results

    def scrape(self) -> pd.DataFrame:
        """Scrape PSA population data for configured cards."""
        logger.info(f"Starting PSA population scrape ({len(self.cards)} cards)")

        all_results = []

        for card in tqdm(self.cards, desc="Searching PSA"):
            results = self._search_card(card)
            all_results.extend(results)

            # Very conservative rate limiting - PSA blocks aggressively
            time.sleep(PSA_DELAY)

        logger.info(f"Found {len(all_results)} PSA population records")
        return pd.DataFrame(all_results)

    def save(self, df: pd.DataFrame) -> str:
        """Save scraped data to CSV."""
        output_path = RAW_DATA_DIR / "psa_population.csv"

        # Handle the grade distribution dict column
        if "psa_grade_distribution" in df.columns:
            df = df.drop(columns=["psa_grade_distribution"])

        df.to_csv(output_path, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} records to {output_path}")
        return str(output_path)


def main():
    """Run the scraper standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Test with just a few cards
    scraper = PSAScraper(cards=["charizard base set", "pikachu base set"])
    df = scraper.scrape()

    if len(df) > 0:
        scraper.save(df)
        print(f"\n✓ Scraped {len(df)} PSA population records")
        print(df[["card_name", "psa_population_total", "psa_population_grade_10"]].head(10))
    else:
        print("\n⚠ No data returned - PSA may be under maintenance or blocking requests")


if __name__ == "__main__":
    main()
