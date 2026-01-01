"""Configuration for Pokemon Feature Store."""

import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class DataSource(Enum):
    """Enum for data source tracking."""
    POKEMON_TCG_API = "POKEMON_TCG_API"
    PRICECHARTING = "PRICECHARTING"
    PSA = "PSA"


# Paths
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "outputs"
RAW_DATA_DIR = OUTPUT_DIR / "raw_data"
NORMALIZED_DIR = OUTPUT_DIR / "normalized"
FEATURE_STORE_DIR = OUTPUT_DIR / "feature_store"
LOGS_DIR = BASE_DIR / "logs"
CRAWL_STATUS_FILE = BASE_DIR / ".crawl_status.json"

# Create directories
for dir_path in [RAW_DATA_DIR, NORMALIZED_DIR, FEATURE_STORE_DIR, LOGS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# API endpoints
POKEMON_API_BASE = "https://api.pokemontcg.io/v2"
PRICECHARTING_BASE = "https://www.pricecharting.com"
PSA_BASE = "https://www.psacard.com"

# Rate limiting (seconds between requests)
POKEMON_API_DELAY = 0.1  # 10 req/sec
PRICECHARTING_DELAY = 0.3  # ~3 req/sec
PSA_DELAY = 1.0  # 1 req/sec (was 4.0 - too slow for resume runs)

# Demo limits
DEMO_CARD_LIMIT = 100
RESUME_RECORD_LIMIT = 50  # Stop resume mode after this many new records (target: <2 min)
MAX_RETRIES = 2  # Reduced from 3 to fail faster
REQUEST_TIMEOUT = 10  # Reduced from 30 for faster failure detection

# API Keys
POKEMON_TCG_API_KEY = os.getenv("POKEMON_TCG_API_KEY")

# Headers for web scraping
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
