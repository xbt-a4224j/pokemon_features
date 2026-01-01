# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2025-01-01

### Added
- Initial release
- PriceCharting scraper with offset-based pagination
- BaseScraper base class for shared HTTP/save logic
- CrawlStatus for tracking scraper progress
- CardNormalizer for transforming raw data to feature store
- Streamlit admin UI for browsing data
- 27 tests covering crawl status, scraper, and pipeline
- Resume mode for incremental crawling

### Architecture
- Offset-based pagination: each run picks up where the last left off
- Star schema normalization (card_master, card_attributes, card_pricing)
- Single output: `features_complete.csv`

[Unreleased]: https://github.com/xbt-a4224j/pokemon_features/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/xbt-a4224j/pokemon_features/releases/tag/v0.1.0
