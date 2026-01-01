"""Tests for CrawlStatus offset tracking."""

import json
import pytest
from pathlib import Path

from crawl_status import CrawlStatus, ScraperStatus


@pytest.fixture
def temp_status_file(tmp_path):
    """Create a temporary status file path."""
    return tmp_path / "test_status.json"


class TestScraperStatus:
    """Tests for ScraperStatus dataclass."""

    def test_default_values(self):
        status = ScraperStatus()
        assert status.offset == 0
        assert status.total_records == 0
        assert status.last_run is None

    def test_to_dict(self):
        status = ScraperStatus(offset=100, total_records=100)
        data = status.to_dict()
        assert data["offset"] == 100
        assert data["total_records"] == 100

    def test_from_dict(self):
        data = {"offset": 50, "total_records": 50, "last_run": "2024-01-01"}
        status = ScraperStatus.from_dict(data)
        assert status.offset == 50
        assert status.total_records == 50

    def test_from_dict_missing_offset_defaults_to_zero(self):
        data = {"total_records": 100}
        status = ScraperStatus.from_dict(data)
        assert status.offset == 0


class TestCrawlStatus:
    """Tests for CrawlStatus manager."""

    def test_get_offset_new_scraper(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        assert cs.get_offset("new_scraper") == 0

    def test_set_offset(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 100)
        assert cs.get_offset("pricecharting") == 100

    def test_offset_persists_to_file(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 150)

        # Load fresh instance
        cs2 = CrawlStatus(temp_status_file)
        assert cs2.get_offset("pricecharting") == 150

    def test_set_offset_syncs_total_records(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 200)
        status = cs.get("pricecharting")
        assert status.total_records == 200

    def test_clear_single_scraper(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 100)
        cs.set_offset("other", 50)

        cs.clear("pricecharting")

        assert cs.get_offset("pricecharting") == 0
        assert cs.get_offset("other") == 50

    def test_clear_all(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 100)
        cs.set_offset("other", 50)

        cs.clear()

        assert cs.get_offset("pricecharting") == 0
        assert cs.get_offset("other") == 0

    def test_load_corrupted_file_starts_fresh(self, temp_status_file):
        temp_status_file.write_text("not valid json")
        cs = CrawlStatus(temp_status_file)
        assert cs.get_offset("pricecharting") == 0

    def test_summary_empty(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        assert "No previous crawl data" in cs.summary()

    def test_summary_with_data(self, temp_status_file):
        cs = CrawlStatus(temp_status_file)
        cs.set_offset("pricecharting", 100)
        summary = cs.summary()
        assert "pricecharting" in summary
        assert "100" in summary
