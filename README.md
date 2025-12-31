# Pokemon Card Feature Store

A data pipeline for collecting Pokemon card pricing and grading data from multiple sources, designed for ML feature engineering.

## Quick Start

```bash
# Install dependencies
uv sync

# Run the full pipeline
uv run python main.py

# Or run with custom limit
uv run python main.py --limit 50
```

## Pipeline

The pipeline runs in 3 phases:

**1. Scrape** - Collect raw data from each source into separate CSVs

**2. Normalize** - Merge all sources by matching on (card_name, set_name, card_number)

**3. Feature Store** - Join normalized tables into a single ML-ready dataset

```
[Scrape]              [Normalize]              [Feature Store]
pokemon_tcg.csv  ──┐
pricecharting.csv ─┼──▶ card_master.csv   ──┐
pokellector.csv  ──┤    card_attributes.csv ─┼──▶ features_complete.csv
pkmncards.csv    ──┤    card_pricing.csv   ──┘
psa_population.csv─┘
```

### Commands

```bash
uv run python main.py              # Run full pipeline
uv run python main.py --limit 200  # Scrape up to 200 cards
uv run python main.py --skip-scrape # Re-normalize existing data
uv run python main.py --resume     # Top off - skip sources with enough data
```

## Data Sources

| Source | Data | Rate Limit |
|--------|------|------------|
| [Pokemon TCG API](https://pokemontcg.io/) | Card metadata, TCGPlayer prices | 10 req/sec |
| [PriceCharting](https://www.pricecharting.com/) | Ungraded/graded market prices | 2 req/sec |
| [PSA](https://www.psacard.com/) | Population reports, grade distributions | 1 req/4sec |
| [Pokellector](https://www.pokellector.com/) | Card database with images | 2 req/sec |
| [PKMNCards](https://pkmncards.com/) | High-res card scans | 2 req/sec |
| Sold Prices | Completed auction prices | 1 req/sec |

## Output

```
outputs/
├── raw_data/           # Raw scraped data (one CSV per source)
├── normalized/         # Cleaned feature tables
│   ├── card_master.csv
│   ├── card_attributes.csv
│   └── card_pricing.csv
└── feature_store/
    └── features_complete.csv  # Final ML-ready dataset
```

### Features Extracted

- **Identity**: card_name, set_name, card_number, rarity, artist
- **Pricing**: TCGPlayer low/mid/high, PriceCharting ungraded/graded, sold prices
- **Grading**: PSA population counts (total, PSA 10, PSA 9, PSA 10 %)
- **Variants**: 1st edition, shadowless, holographic flags
- **Images**: URLs from Pokellector, PKMNCards

## Configuration

Add your Pokemon TCG API key to `.env` (optional, increases rate limits):

```
POKEMON_TCG_API_KEY=your_key_here
```

## Run Individual Scrapers

```bash
uv run python scrapers/pokemon_tcg_scraper.py
uv run python scrapers/pricecharting_scraper.py
uv run python scrapers/psa_scraper.py
uv run python scrapers/pokellector_scraper.py
uv run python scrapers/pkmncards_scraper.py
uv run python scrapers/tcgfish_scraper.py
```
