"""Crawl status tracking for incremental scraping.

Uses offset-based pagination: each scraper tracks how many records
it has scraped so far. Resume picks up where it left off.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScraperStatus:
    """Status for a single scraper.

    Primary fields:
        offset: How many records have been scraped (cursor position)
        total_records: Same as offset, kept in sync
        last_run: ISO timestamp of last scrape

    Legacy fields (kept for backward compatibility with old status files):
        last_record_id, last_page, completed_sets, scraped_ids
    """
    last_run: str | None = None
    total_records: int = 0
    offset: int = 0
    # Legacy fields - not actively used but kept for file compatibility
    last_record_id: str | None = None
    last_page: int = 0
    completed_sets: list[str] = field(default_factory=list)
    scraped_ids: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_run": self.last_run,
            "total_records": self.total_records,
            "offset": self.offset,
            "last_record_id": self.last_record_id,
            "last_page": self.last_page,
            "completed_sets": self.completed_sets,
            "scraped_ids": list(self.scraped_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScraperStatus":
        return cls(
            last_run=data.get("last_run"),
            total_records=data.get("total_records", 0),
            offset=data.get("offset", 0),
            last_record_id=data.get("last_record_id"),
            last_page=data.get("last_page", 0),
            completed_sets=data.get("completed_sets", []),
            scraped_ids=set(data.get("scraped_ids", [])),
        )


class CrawlStatus:
    """Manages crawl status for all scrapers."""

    def __init__(self, status_file: Path):
        self.status_file = status_file
        self._data: dict[str, ScraperStatus] = {}
        self._load()

    def _load(self) -> None:
        """Load status from file."""
        if self.status_file.exists():
            try:
                with open(self.status_file) as f:
                    raw = json.load(f)
                self._data = {
                    name: ScraperStatus.from_dict(status)
                    for name, status in raw.get("scrapers", {}).items()
                }
                logger.info(f"Loaded crawl status for {len(self._data)} scrapers")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load crawl status: {e}")
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        """Save status to file."""
        data = {
            "last_updated": datetime.now().isoformat(),
            "scrapers": {
                name: status.to_dict()
                for name, status in self._data.items()
            },
        }
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.status_file, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved crawl status to {self.status_file}")

    def get(self, scraper_name: str) -> ScraperStatus:
        """Get status for a scraper, creating if needed."""
        if scraper_name not in self._data:
            self._data[scraper_name] = ScraperStatus()
        return self._data[scraper_name]

    def update(
        self,
        scraper_name: str,
        *,
        records_added: int = 0,
        last_record_id: str | None = None,
        last_page: int | None = None,
        completed_set: str | None = None,
        scraped_ids: list[str] | None = None,
    ) -> None:
        """Update status for a scraper."""
        status = self.get(scraper_name)
        status.last_run = datetime.now().isoformat()
        status.total_records += records_added

        if last_record_id:
            status.last_record_id = last_record_id
        if last_page is not None:
            status.last_page = last_page
        if completed_set and completed_set not in status.completed_sets:
            status.completed_sets.append(completed_set)
        if scraped_ids:
            status.scraped_ids.update(scraped_ids)

        self.save()

    def is_id_scraped(self, scraper_name: str, record_id: str) -> bool:
        """Check if a record ID has already been scraped."""
        return record_id in self.get(scraper_name).scraped_ids

    def is_set_completed(self, scraper_name: str, set_slug: str) -> bool:
        """Check if a set has been fully scraped."""
        return set_slug in self.get(scraper_name).completed_sets

    def get_resume_page(self, scraper_name: str) -> int:
        """Get the page to resume from (0 means start fresh)."""
        return self.get(scraper_name).last_page

    def get_offset(self, scraper_name: str) -> int:
        """Get current offset (how many cards already scraped)."""
        return self.get(scraper_name).offset

    def set_offset(self, scraper_name: str, offset: int) -> None:
        """Set offset and save."""
        status = self.get(scraper_name)
        status.offset = offset
        status.total_records = offset  # Keep in sync
        status.last_run = datetime.now().isoformat()
        self.save()

    def clear(self, scraper_name: str | None = None) -> None:
        """Clear status for one or all scrapers."""
        if scraper_name:
            if scraper_name in self._data:
                del self._data[scraper_name]
        else:
            self._data = {}
        self.save()

    def summary(self) -> str:
        """Return a summary of crawl status."""
        if not self._data:
            return "No previous crawl data found."

        lines = ["Crawl Status:"]
        for name, status in self._data.items():
            last = status.last_run[:16] if status.last_run else "never"
            lines.append(f"  {name}: {status.total_records} records (last: {last})")
        return "\n".join(lines)
