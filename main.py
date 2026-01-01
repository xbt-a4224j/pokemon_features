"""Pokemon Feature Store - Main Pipeline."""

import argparse
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from config import CRAWL_STATUS_FILE, DEMO_CARD_LIMIT, FEATURE_STORE_DIR, LOGS_DIR, RAW_DATA_DIR, RESUME_RECORD_LIMIT
from crawl_status import CrawlStatus
from normalizers.card_normalizer import CardNormalizer
from scrapers.pricecharting_scraper import PriceChartingScraper

__version__ = "0.1.0"


@dataclass
class ScraperConfig:
    """Configuration for a scraper."""
    name: str
    description: str
    run: Callable
    output_file: str


def setup_logging():
    """Configure logging to file only (console output handled separately)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "pipeline.log"),
        ],
    )
    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# Thread-safe print lock
print_lock = threading.Lock()


def run_scraper(config: ScraperConfig) -> tuple[str, bool, int, str]:
    """Run a single scraper with error handling. Returns (name, success, count, message)."""
    try:
        count = config.run()
        if count > 0:
            return config.name, True, count, f"✓ {count} records"
        else:
            # 0 records could mean "already done" or "failed" - check output file exists
            output_path = RAW_DATA_DIR / config.output_file
            if output_path.exists():
                return config.name, True, 0, "✓ Already up to date"
            else:
                return config.name, False, 0, "⚠ No data (source unavailable)"
    except ConnectionError:
        return config.name, False, 0, "✗ Connection failed"
    except TimeoutError:
        return config.name, False, 0, "✗ Timed out"
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            return config.name, False, 0, "✗ 404 - endpoint changed"
        elif "403" in error_msg or "blocked" in error_msg.lower():
            return config.name, False, 0, "✗ Access denied"
        elif "timeout" in error_msg.lower():
            return config.name, False, 0, "✗ Timed out"
        elif "maintenance" in error_msg.lower():
            return config.name, False, 0, "✗ Under maintenance"
        else:
            return config.name, False, 0, f"✗ {error_msg[:40]}"


def run_scrapers_parallel(scrapers: list[ScraperConfig]) -> list[tuple[str, bool, int, str]]:
    """Run all scrapers in parallel with live status updates."""
    results = []
    status = {c.name: "⏳ waiting..." for c in scrapers}

    def print_status():
        """Print current status of all scrapers."""
        with print_lock:
            lines = []
            for config in scrapers:
                lines.append(f"  {config.name}: {status[config.name]}")
            # Move cursor up and reprint
            if len(results) > 0:
                sys.stdout.write(f"\033[{len(scrapers)}A")  # Move up
            for line in lines:
                print(f"{line:<60}")
            sys.stdout.flush()

    # Initial status display
    print()
    for config in scrapers:
        print(f"  {config.name}: ⏳ waiting...")

    with ThreadPoolExecutor(max_workers=6) as executor:
        # Submit all scrapers
        future_to_config = {}
        for config in scrapers:
            status[config.name] = "🔄 scraping..."
            future = executor.submit(run_scraper, config)
            future_to_config[future] = config

        # Update display to show all running
        print_status()

        # Process completions as they arrive
        for future in as_completed(future_to_config):
            config = future_to_config[future]
            name, success, count, message = future.result()
            status[name] = message
            results.append((name, success, count, message))
            print_status()

    return results


def run_scrapers_sequential(scrapers: list[ScraperConfig], record_limit: int) -> list[tuple[str, bool, int, str]]:
    """Run scrapers sequentially, stopping after record_limit cumulative records."""
    results = []
    total_records = 0

    print()
    for config in scrapers:
        print(f"  {config.name}: 🔄 scraping...", end="", flush=True)
        name, success, count, message = run_scraper(config)
        print(f"\r  {config.name}: {message:<50}")
        results.append((name, success, count, message))

        if success:
            total_records += count
            if total_records >= record_limit:
                print(f"\n  ⏹ Reached {total_records} records (limit: {record_limit}), stopping early")
                break

    return results


def create_scrapers(limit: int, crawl_status: CrawlStatus | None = None) -> list[ScraperConfig]:
    """Create list of scrapers to run."""

    def run_pricecharting():
        scraper = PriceChartingScraper(limit=limit, crawl_status=crawl_status)
        df = scraper.scrape()
        if len(df) > 0:
            scraper.save(df)
        return len(df)

    # Only PriceCharting enabled - most reliable source with pricing data
    return [
        ScraperConfig(
            name="PriceCharting",
            description="Market prices for ungraded and graded cards",
            run=run_pricecharting,
            output_file="pricecharting_cards.csv",
        ),
    ]
    # Disabled scrapers - can re-enable if needed:
    # - Pokemon TCG API: timing out
    # - Pokellector: no pricing
    # - PKMNCards: no pricing
    # - PSA Population: not working
    # - Sold Prices: too slow


def run_pipeline(limit: int = DEMO_CARD_LIMIT, skip_scrape: bool = False, resume: bool = False, quiet: bool = False):
    """Run the full feature store pipeline."""
    logger = logging.getLogger(__name__)

    # Get before count for comparison
    before_count = 0
    if FEATURE_STORE_DIR.exists():
        feature_file = FEATURE_STORE_DIR / "features_complete.csv"
        if feature_file.exists():
            import pandas as pd
            before_count = len(pd.read_csv(feature_file))

    if not quiet:
        print("\n" + "=" * 60)
        print("  Pokemon Feature Store Pipeline")
        print("=" * 60)

    # Initialize crawl status for incremental scraping
    crawl_status = CrawlStatus(CRAWL_STATUS_FILE) if resume else None

    # Phase 1: Scraping
    if not skip_scrape:
        scrapers = create_scrapers(limit, crawl_status=crawl_status)

        if resume:
            if not quiet:
                print(f"\n[1/3] SCRAPING - RESUME MODE (limit: {RESUME_RECORD_LIMIT} new records)")
                print("-" * 60)
                if crawl_status:
                    print(f"  {crawl_status.summary()}")
                print(f"  Running scrapers sequentially until {RESUME_RECORD_LIMIT} new records...")

            # Run sequentially with early stopping
            results = run_scrapers_sequential(scrapers, RESUME_RECORD_LIMIT)
        else:
            if not quiet:
                print(f"\n[1/3] SCRAPING ({len(scrapers)} sources)")
                print("-" * 60)

            # Run all scrapers in parallel
            results = run_scrapers_parallel(scrapers)

        # Summary
        if not quiet:
            print()
            successful = sum(1 for _, s, _, _ in results if s)
            total_records = sum(c for _, s, c, _ in results if s)
            failed = len(results) - successful

            print("-" * 60)
            print(f"  Caught {successful}/{len(results)} sources ({total_records} total records)")
            if failed > 0:
                print(f"  {failed} sources unavailable (will use available data)")
    else:
        if not quiet:
            print("\n[1/3] SCRAPING")
            print("-" * 60)
            print("Skipped (using existing data)")

    # Phase 2: Normalization
    if not quiet:
        print(f"\n[2/3] NORMALIZING")
        print("-" * 60)

    try:
        normalizer = CardNormalizer()
        tables = normalizer.normalize_all()
        if not quiet:
            for name, data in tables.items():
                print(f"  ✓ {name}.csv: {len(data)} rows")
    except FileNotFoundError:
        print("  ✗ No raw data found - run scraping first")
        return None
    except Exception as e:
        print(f"  ✗ Normalization failed: {e}")
        return None

    # Phase 3: Feature Store
    if not quiet:
        print(f"\n[3/3] FEATURE STORE")
        print("-" * 60)

    try:
        features = normalizer.create_feature_store(tables)
        output_path = FEATURE_STORE_DIR / "features_complete.csv"
        features.to_csv(output_path, index=False, encoding="utf-8")
        if not quiet:
            print(f"  ✓ features_complete.csv: {len(features)} rows")
            print(f"  ✓ Completeness: {features['completeness_score'].mean():.1f}%")

            price_cols = [c for c in features.columns if "price" in c.lower()]
            has_price = features[price_cols].notna().any(axis=1).sum() if price_cols else 0
            print(f"  ✓ Cards with pricing: {has_price}/{len(features)}")
    except Exception as e:
        print(f"  ✗ Feature store creation failed: {e}")
        return None

    # Final summary
    after_count = len(features)
    new_cards = after_count - before_count

    if quiet:
        # Concise output for UI
        num_sets = features["set_name"].nunique() if "set_name" in features.columns else 0
        if new_cards > 0:
            print(f"Added {new_cards} new cards. Total: {after_count}")
        else:
            print(f"No new cards. Total: {after_count} cards across {num_sets} sets (all sets fully scraped)")
    else:
        print("\n" + "=" * 60)
        if new_cards > 0:
            print(f"  Done! Added {new_cards} new cards (was {before_count}, now {after_count})")
        else:
            print(f"  Done! {after_count} cards (no new data - all sets fully scraped)")
        print(f"  Output: {FEATURE_STORE_DIR}")
        print("=" * 60 + "\n")

    return features


def main():
    parser = argparse.ArgumentParser(
        description="Pokemon Feature Store Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python main.py              # Run full pipeline (100 cards)
  uv run python main.py --limit 50   # Limit to 50 cards
  uv run python main.py --skip-scrape # Use existing raw data
  uv run python main.py --resume     # Resume from last crawl, skip already-fetched records
        """,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEMO_CARD_LIMIT,
        help=f"Number of cards to scrape (default: {DEMO_CARD_LIMIT})",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip scraping and use existing raw data",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from previous crawl - skips already-scraped records/sets",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal output (just summary)",
    )
    args = parser.parse_args()

    setup_logging()

    try:
        run_pipeline(limit=args.limit, skip_scrape=args.skip_scrape, resume=args.resume, quiet=args.quiet)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
