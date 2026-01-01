"""End-to-end tests for the pipeline."""

import pytest
from pathlib import Path

import pandas as pd

from crawl_status import CrawlStatus


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for test outputs."""
    raw = tmp_path / "raw_data"
    normalized = tmp_path / "normalized"
    feature_store = tmp_path / "feature_store"
    logs = tmp_path / "logs"

    for d in [raw, normalized, feature_store, logs]:
        d.mkdir()

    return {
        "raw": raw,
        "normalized": normalized,
        "feature_store": feature_store,
        "logs": logs,
        "status_file": tmp_path / "status.json",
    }


@pytest.fixture
def mock_scrape_data():
    """Generate fake scraped data."""
    def make_cards(start, count):
        return pd.DataFrame([
            {
                "pricecharting_id": f"pc_{i}",
                "data_source": "PRICECHARTING",
                "card_name": f"Pokemon {i}",
                "full_name": f"Pokemon {i} #{i}",
                "set_slug": "pokemon-base-set",
                "set_name": "Base Set",
                "card_number": str(i),
                "card_url": f"https://example.com/{i}",
                "is_first_edition": False,
                "is_shadowless": False,
                "price_ungraded": 10.0 + i,
                "price_graded": 50.0 + i,
                "price_sealed": None,
            }
            for i in range(start, start + count)
        ])
    return make_cards


class TestPipelineEndToEnd:
    """End-to-end pipeline tests."""

    def test_resume_increments_offset(self, temp_dirs, mock_scrape_data):
        """Resume mode should increment offset after each run."""
        cs = CrawlStatus(temp_dirs["status_file"])

        # First run
        cs.set_offset("pricecharting", 0)
        mock_scrape_data(0, 50).to_csv(temp_dirs["raw"] / "pricecharting_cards.csv", index=False)
        cs.set_offset("pricecharting", 50)

        # Second run
        existing = pd.read_csv(temp_dirs["raw"] / "pricecharting_cards.csv")
        new_data = mock_scrape_data(50, 50)
        combined = pd.concat([existing, new_data], ignore_index=True)
        combined.to_csv(temp_dirs["raw"] / "pricecharting_cards.csv", index=False)
        cs.set_offset("pricecharting", 100)

        assert cs.get_offset("pricecharting") == 100
        assert len(pd.read_csv(temp_dirs["raw"] / "pricecharting_cards.csv")) == 100

    def test_data_grows_with_appends(self, temp_dirs, mock_scrape_data):
        """Raw data file should grow as we append."""
        # First batch
        mock_scrape_data(0, 20).to_csv(temp_dirs["raw"] / "pricecharting_cards.csv", index=False)
        count1 = len(pd.read_csv(temp_dirs["raw"] / "pricecharting_cards.csv"))

        # Add more data
        existing = pd.read_csv(temp_dirs["raw"] / "pricecharting_cards.csv")
        new_data = mock_scrape_data(20, 20)
        combined = pd.concat([existing, new_data], ignore_index=True)
        combined.to_csv(temp_dirs["raw"] / "pricecharting_cards.csv", index=False)
        count2 = len(pd.read_csv(temp_dirs["raw"] / "pricecharting_cards.csv"))

        assert count2 == 40
        assert count2 > count1


class TestPipelineResumeLogic:
    """Tests for resume-specific behavior."""

    def test_offset_zero_starts_fresh(self, temp_dirs):
        cs = CrawlStatus(temp_dirs["status_file"])
        assert cs.get_offset("pricecharting") == 0

    def test_offset_preserved_across_loads(self, temp_dirs):
        cs = CrawlStatus(temp_dirs["status_file"])
        cs.set_offset("pricecharting", 500)

        cs2 = CrawlStatus(temp_dirs["status_file"])
        assert cs2.get_offset("pricecharting") == 500

    def test_clear_resets_offset(self, temp_dirs):
        cs = CrawlStatus(temp_dirs["status_file"])
        cs.set_offset("pricecharting", 500)
        cs.clear("pricecharting")

        assert cs.get_offset("pricecharting") == 0
