"""Tests for PriceChartingScraper offset-based resume."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from crawl_status import CrawlStatus
from scrapers.pricecharting_scraper import PriceChartingScraper


@pytest.fixture
def temp_status_file(tmp_path):
    return tmp_path / "test_status.json"


@pytest.fixture
def mock_cards():
    """Generate fake card data for testing."""
    return [
        {
            "pricecharting_id": f"card_{i}",
            "data_source": "PRICECHARTING",
            "card_name": f"Pokemon {i}",
            "full_name": f"Pokemon {i} #1",
            "set_slug": "pokemon-base-set",
            "set_name": "Base Set",
            "card_number": str(i),
            "card_url": f"https://example.com/card_{i}",
            "is_first_edition": False,
            "is_shadowless": False,
            "price_ungraded": 10.0 + i,
            "price_graded": 50.0 + i,
            "price_sealed": None,
        }
        for i in range(200)
    ]


class TestPriceChartingScraperOffset:
    """Tests for offset-based pagination."""

    def test_scraper_starts_at_offset_zero(self, temp_status_file, mock_cards):
        cs = CrawlStatus(temp_status_file)
        scraper = PriceChartingScraper(limit=10, crawl_status=cs)

        with patch.object(scraper, "_scrape_set", return_value=mock_cards[:50]):
            df = scraper.scrape()

        assert len(df) == 10
        assert df.iloc[0]["card_name"] == "Pokemon 0"

    def test_scraper_resumes_from_offset(self, temp_status_file, mock_cards):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 50)

        scraper = PriceChartingScraper(limit=10, crawl_status=cs)

        with patch.object(scraper, "_scrape_set", return_value=mock_cards):
            df = scraper.scrape()

        assert len(df) == 10
        assert df.iloc[0]["card_name"] == "Pokemon 50"

    def test_scraper_updates_offset_after_scrape(self, temp_status_file, mock_cards):
        cs = CrawlStatus(temp_status_file)
        scraper = PriceChartingScraper(limit=25, crawl_status=cs)

        with patch.object(scraper, "_scrape_set", return_value=mock_cards[:50]):
            scraper.scrape()

        assert cs.get_offset("pricecharting") == 25

    def test_scraper_accumulates_offset(self, temp_status_file, mock_cards):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 100)

        scraper = PriceChartingScraper(limit=50, crawl_status=cs)

        with patch.object(scraper, "_scrape_set", return_value=mock_cards):
            scraper.scrape()

        assert cs.get_offset("pricecharting") == 150

    def test_scraper_without_crawl_status(self, mock_cards):
        scraper = PriceChartingScraper(limit=10, crawl_status=None)

        with patch.object(scraper, "_scrape_set", return_value=mock_cards[:50]):
            df = scraper.scrape()

        assert len(df) == 10

    def test_scraper_respects_limit(self, temp_status_file, mock_cards):
        cs = CrawlStatus(temp_status_file)
        scraper = PriceChartingScraper(limit=5, crawl_status=cs)

        with patch.object(scraper, "_scrape_set", return_value=mock_cards):
            df = scraper.scrape()

        assert len(df) == 5


class TestPriceChartingScraperSave:
    """Tests for save/append behavior."""

    def test_save_creates_file(self, tmp_path, mock_cards):
        scraper = PriceChartingScraper(limit=10)
        df = pd.DataFrame(mock_cards[:5])

        with patch("scrapers.base.RAW_DATA_DIR", tmp_path):
            output = scraper.save(df)

        assert Path(output).exists()
        saved = pd.read_csv(output)
        assert len(saved) == 5

    def test_save_appends_to_existing(self, tmp_path, mock_cards):
        scraper = PriceChartingScraper(limit=10)

        with patch("scrapers.base.RAW_DATA_DIR", tmp_path):
            scraper.save(pd.DataFrame(mock_cards[:5]))
            scraper.save(pd.DataFrame(mock_cards[5:10]))

            output_path = tmp_path / "pricecharting_cards.csv"
            saved = pd.read_csv(output_path)

        assert len(saved) == 10

    def test_save_deduplicates_by_id(self, tmp_path, mock_cards):
        scraper = PriceChartingScraper(limit=10)

        with patch("scrapers.base.RAW_DATA_DIR", tmp_path):
            scraper.save(pd.DataFrame(mock_cards[:5]))
            scraper.save(pd.DataFrame(mock_cards[:5]))  # Same cards again

            output_path = tmp_path / "pricecharting_cards.csv"
            saved = pd.read_csv(output_path)

        assert len(saved) == 5
