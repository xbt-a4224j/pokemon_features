"""Pokemon Feature Store - Main Pipeline."""

import argparse
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from config import DEMO_CARD_LIMIT, FEATURE_STORE_DIR, LOGS_DIR, RAW_DATA_DIR
from normalizers.card_normalizer import CardNormalizer
from scrapers.pokemon_tcg_scraper import PokemonTCGScraper
from scrapers.pricecharting_scraper import PriceChartingScraper
from scrapers.psa_scraper import PSAScraper
from scrapers.pokellector_scraper import PokellectorScraper
from scrapers.pkmncards_scraper import PKMNCardsScraper
from scrapers.tcgfish_scraper import SoldPricesScraper


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


def get_existing_count(filename: str) -> int:
    """Get count of records in existing CSV file."""
    path = RAW_DATA_DIR / filename
    if not path.exists():
        return 0
    try:
        import pandas as pd
        df = pd.read_csv(path)
        return len(df)
    except Exception:
        return 0


def create_scrapers(limit: int) -> list[ScraperConfig]:
    """Create list of scrapers to run."""

    def run_pokemon_tcg():
        scraper = PokemonTCGScraper(limit=limit)
        df = scraper.scrape()
        if len(df) > 0:
            scraper.save(df)
        return len(df)

    def run_pricecharting():
        scraper = PriceChartingScraper(limit_per_set=max(10, limit // 5))
        df = scraper.scrape()
        if len(df) > 0:
            scraper.save(df)
        return len(df)

    def run_psa():
        scraper = PSAScraper()
        df = scraper.scrape()
        if len(df) > 0:
            scraper.save(df)
        return len(df)

    def run_pokellector():
        scraper = PokellectorScraper(limit_per_set=max(10, limit // 5))
        df = scraper.scrape()
        if len(df) > 0:
            scraper.save(df)
        return len(df)

    def run_pkmncards():
        scraper = PKMNCardsScraper(limit_per_set=max(10, limit // 5))
        df = scraper.scrape()
        if len(df) > 0:
            scraper.save(df)
        return len(df)

    def run_sold_prices():
        scraper = SoldPricesScraper()
        df = scraper.scrape()
        if len(df) > 0:
            scraper.save(df)
        return len(df)

    return [
        ScraperConfig(
            name="Pokemon TCG API",
            description="Card metadata, images, TCGPlayer prices",
            run=run_pokemon_tcg,
            output_file="pokemon_tcg_cards.csv",
        ),
        ScraperConfig(
            name="PriceCharting",
            description="Market prices for ungraded and graded cards",
            run=run_pricecharting,
            output_file="pricecharting_cards.csv",
        ),
        ScraperConfig(
            name="PSA Population Report",
            description="Grading population data by grade level",
            run=run_psa,
            output_file="psa_population.csv",
        ),
        ScraperConfig(
            name="Pokellector",
            description="Card database with images and set info",
            run=run_pokellector,
            output_file="pokellector_cards.csv",
        ),
        ScraperConfig(
            name="PKMNCards",
            description="Card database with high-res scans",
            run=run_pkmncards,
            output_file="pkmncards_cards.csv",
        ),
        ScraperConfig(
            name="Sold Prices",
            description="Recent sold/completed listing prices",
            run=run_sold_prices,
            output_file="sold_prices.csv",
        ),
    ]


def run_pipeline(limit: int = DEMO_CARD_LIMIT, skip_scrape: bool = False, resume: bool = False):
    """Run the full feature store pipeline."""
    logger = logging.getLogger(__name__)

    print("\n" + "=" * 60)
    print("  Pokemon Feature Store Pipeline")
    print("=" * 60)

    # Phase 1: Scraping
    if not skip_scrape:
        scrapers = create_scrapers(limit)

        if resume:
            print(f"\n[1/3] SCRAPING - RESUME MODE ({len(scrapers)} sources)")
            print("-" * 60)
            print("  Checking existing data...")

            # Filter to only scrapers that need more data
            scrapers_to_run = []
            for config in scrapers:
                existing = get_existing_count(config.output_file)
                if existing < limit:
                    scrapers_to_run.append(config)
                    needed = limit - existing
                    print(f"  {config.name}: {existing} existing, need {needed} more")
                else:
                    print(f"  {config.name}: {existing} existing ✓ (skip)")

            if not scrapers_to_run:
                print("\n  All sources have enough data!")
                scrapers = []
            else:
                scrapers = scrapers_to_run
                print(f"\n  Running {len(scrapers)} scrapers that need data...")
        else:
            print(f"\n[1/3] SCRAPING ({len(scrapers)} sources)")

        print("-" * 60)

        # Run all scrapers in parallel
        results = run_scrapers_parallel(scrapers)

        # Summary
        print()
        successful = sum(1 for _, s, _, _ in results if s)
        total_records = sum(c for _, s, c, _ in results if s)
        failed = len(results) - successful

        print("-" * 60)
        print(f"  Caught {successful}/{len(scrapers)} sources ({total_records} total records)")
        if failed > 0:
            print(f"  {failed} sources unavailable (will use available data)")
    else:
        print("\n[1/3] SCRAPING")
        print("-" * 60)
        print("Skipped (using existing data)")

    # Phase 2: Normalization
    print(f"\n[2/3] NORMALIZING")
    print("-" * 60)

    try:
        normalizer = CardNormalizer()
        tables = normalizer.normalize_all()
        for name, data in tables.items():
            print(f"  ✓ {name}.csv: {len(data)} rows")
    except FileNotFoundError:
        print("  ✗ No raw data found - run scraping first")
        print("\nPipeline stopped. Run without --skip-scrape to fetch data.")
        return None
    except Exception as e:
        print(f"  ✗ Normalization failed: {e}")
        return None

    # Phase 3: Feature Store
    print(f"\n[3/3] FEATURE STORE")
    print("-" * 60)

    try:
        features = normalizer.create_feature_store(tables)
        output_path = FEATURE_STORE_DIR / "features_complete.csv"
        features.to_csv(output_path, index=False, encoding="utf-8")
        print(f"  ✓ features_complete.csv: {len(features)} rows")
        print(f"  ✓ Completeness: {features['completeness_score'].mean():.1f}%")

        price_cols = [c for c in features.columns if "price" in c.lower()]
        has_price = features[price_cols].notna().any(axis=1).sum() if price_cols else 0
        print(f"  ✓ Cards with pricing: {has_price}/{len(features)}")
    except Exception as e:
        print(f"  ✗ Feature store creation failed: {e}")
        return None

    print("\n" + "=" * 60)
    print(f"  Done! Output in: {FEATURE_STORE_DIR}")
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
  uv run python main.py --resume     # Top off - skip sources with enough data
        """,
    )
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
        help="Resume scraping, skipping sources that already have enough data",
    )
    args = parser.parse_args()

    setup_logging()

    try:
        run_pipeline(limit=args.limit, skip_scrape=args.skip_scrape, resume=args.resume)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
