# Pokemon Card Feature Store

A data pipeline for collecting Pokemon card pricing data, designed for ML feature engineering.

## Quick Start

```bash
uv sync                           # Install dependencies
uv run python main.py             # Scrape 100 cards
uv run python main.py --resume    # Add 100 more cards
uv run streamlit run ui.py        # Admin UI
```

## Architecture

```
┌─────────────┐     ┌────────────┐     ┌──────────────────┐
│ PriceChart- │────▶│ Normalizer │────▶│ features_complete│
│ ing.com     │     │            │     │ .csv             │
└─────────────┘     └────────────┘     └──────────────────┘
      │                   │
      ▼                   ▼
  raw_data/          normalized/
  pricecharting      card_master.csv
  _cards.csv         card_attributes.csv
                     card_pricing.csv
```

### Data Flow

1. **Scraper** fetches cards from PriceCharting using offset-based pagination
2. **Normalizer** transforms raw data into 3 normalized tables (star schema)
3. **Feature Store** joins tables into final `features_complete.csv`

### Why Normalized Tables?

The intermediate normalized tables (`card_master`, `card_attributes`, `card_pricing`) follow a star schema pattern:

- **Separation of concerns**: Identity data vs pricing data vs attributes
- **Extensibility**: Easy to add new sources that contribute specific columns
- **Debugging**: Easier to trace data issues to a specific table

For a single-source pipeline, this is optional overhead. The key output is `features_complete.csv`.

## Resume Mode

The scraper uses offset-based pagination for incremental crawling:

```bash
# First run: scrapes cards 0-99, offset = 100
uv run python main.py

# Second run: scrapes cards 100-199, offset = 200
uv run python main.py --resume

# Third run: scrapes cards 200-299, offset = 300
uv run python main.py --resume
```

Progress is saved in `.crawl_status.json`. Each resume adds more cards.

## Commands

```bash
uv run python main.py              # Scrape 100 cards (default)
uv run python main.py --limit 500  # Scrape 500 cards
uv run python main.py --resume     # Continue from last offset
uv run python main.py --skip-scrape # Re-normalize existing data
uv run python main.py --quiet      # Minimal output
uv run pytest tests/               # Run tests
```

## Output

```
outputs/
├── raw_data/
│   └── pricecharting_cards.csv   # Raw scraped data
├── normalized/
│   ├── card_master.csv           # Card identity (name, set, number)
│   ├── card_attributes.csv       # Card properties (type, rarity)
│   └── card_pricing.csv          # Price data
└── feature_store/
    └── features_complete.csv     # Final ML-ready dataset
```

## Project Structure

```
├── main.py                 # Pipeline entrypoint
├── config.py               # Settings and constants
├── crawl_status.py         # Offset tracking for resume
├── ui.py                   # Streamlit admin interface
├── scrapers/
│   ├── base.py             # BaseScraper with shared logic
│   └── pricecharting_scraper.py  # Active scraper
├── normalizers/
│   └── card_normalizer.py  # Data transformation
└── tests/                  # pytest test suite
```

## Extending

To add a new data source:

1. Create `scrapers/new_source_scraper.py` extending `BaseScraper`
2. Implement `_scrape_batch(offset, limit)` returning list of card dicts
3. Set `SCRAPER_NAME` and `OUTPUT_FILE` class attributes
4. Add adapter in `card_normalizer.py` to merge the new source
