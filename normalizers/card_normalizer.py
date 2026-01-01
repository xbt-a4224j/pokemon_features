"""Normalizer for Pokemon card data into feature store format."""

import logging
from pathlib import Path

import pandas as pd

# Add parent to path for imports when run as script
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

from config import NORMALIZED_DIR, RAW_DATA_DIR

logger = logging.getLogger(__name__)


class CardNormalizer:
    """Normalizes raw card data into feature store tables."""

    def __init__(self):
        self.raw_data_dir = RAW_DATA_DIR
        self.normalized_dir = NORMALIZED_DIR

    def load_raw_data(self, filename: str = "pokemon_tcg_cards.csv") -> pd.DataFrame | None:
        """Load raw data from a CSV file. Returns None if file doesn't exist or is empty."""
        raw_path = self.raw_data_dir / filename
        if not raw_path.exists():
            return None
        try:
            df = pd.read_csv(raw_path)
            return df if len(df) > 0 else None
        except Exception:
            return None

    def normalize_master(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract card identity features into card_master.csv."""
        master = pd.DataFrame({
            "card_id": df.get("card_id", df.index.astype(str)),
            "data_source": df.get("data_source", "UNKNOWN"),
            "card_name": df["card_name"],
            "set_name": df["set_name"],
            "set_code": df.get("set_code", ""),
            "card_number": df["card_number"],
            "rarity_symbol": df.get("rarity"),
            "language": "EN",
            "series": df.get("series"),
            "release_year": pd.to_datetime(df.get("release_date"), errors="coerce").dt.year,
            "release_date": df.get("release_date"),
            "artist": df.get("artist"),
            "national_pokedex_number": df.get("national_dex", pd.Series([None] * len(df))).apply(
                lambda x: str(x).split(",")[0] if pd.notna(x) and x else None
            ),
        })
        return master

    def normalize_attributes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract card attribute features into card_attributes.csv."""
        # Handle missing columns gracefully
        types_series = df.get("types", pd.Series([None] * len(df)))
        subtypes_series = df.get("subtypes", pd.Series([None] * len(df)))
        rarity_series = df.get("rarity", pd.Series([""] * len(df))).fillna("")

        attributes = pd.DataFrame({
            "card_id": df.get("card_id", df.index.astype(str)),
            "card_type": df.get("supertype", "Pokémon"),
            "pokemon_type": types_series.apply(
                lambda x: str(x).split(",")[0] if pd.notna(x) and x else None
            ),
            "hp": pd.to_numeric(df.get("hp"), errors="coerce"),
            "supertype": df.get("supertype", "Pokémon"),
            "subtype": subtypes_series.apply(
                lambda x: str(x).split(",")[0] if pd.notna(x) and x else None
            ),
            "is_first_edition": df.get("pc_first_edition", False),
            "is_shadowless": df.get("pc_shadowless", False),
            "is_holographic": rarity_series.str.contains("Holo", case=False, na=False),
            "is_reverse_holo": subtypes_series.str.contains("Reverse", case=False, na=False) if hasattr(subtypes_series, 'str') else False,
            "is_error_card": False,
            "variant_type": subtypes_series,
            "evolves_from": df.get("evolves_from"),
        })
        return attributes

    def normalize_pricing(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract pricing features into card_pricing.csv."""
        pricing = pd.DataFrame({
            "card_id": df.get("card_id", df.index.astype(str)),
            # TCGPlayer prices (from Pokemon TCG API)
            "tcgplayer_low": df.get("tcgplayer_price_low"),
            "tcgplayer_mid": df.get("tcgplayer_price_mid"),
            "tcgplayer_high": df.get("tcgplayer_price_high"),
            "tcgplayer_market": df.get("tcgplayer_price_market"),
            # PriceCharting prices
            "price_ungraded": df.get("pc_price_ungraded"),
            "price_graded": df.get("pc_price_graded"),
            "price_complete": df.get("pc_price_complete"),
            # Sold prices (from auctions)
            "avg_sold_price": df.get("avg_sold_price"),
            "min_sold_price": df.get("min_sold_price"),
            "max_sold_price": df.get("max_sold_price"),
            "num_sales": df.get("num_sales"),
            # PSA grading data
            "total_graded": df.get("total_graded"),
            "psa_10_count": df.get("psa_10_count"),
            "psa_9_count": df.get("psa_9_count"),
            "psa_10_pct": df.get("psa_10_pct"),
            # Composite market price (best available)
            "market_price": df.get("tcgplayer_price_market", df.get("pc_price_ungraded", df.get("avg_sold_price"))),
            "last_updated": df.get("tcgplayer_updated_at"),
        })
        return pricing

    def _create_card_key(self, df: pd.DataFrame, name_col: str, set_col: str, num_col: str) -> pd.Series:
        """Create a canonical card key for matching across sources."""
        # Normalize card_number: remove trailing .0 (e.g., "4.0" -> "4")
        card_num = df[num_col].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        return (
            df[name_col].str.lower().str.strip() + "|" +
            df[set_col].str.lower().str.strip() + "|" +
            card_num
        )

    def _load_and_merge_all_sources(self) -> pd.DataFrame:
        """Load all available data sources and merge them."""
        merged = None

        # Source 1: Pokemon TCG API (primary - has most fields)
        tcg = self.load_raw_data("pokemon_tcg_cards.csv")
        if tcg is not None:
            tcg = self._adapt_pokemon_tcg(tcg)
            tcg["_key"] = self._create_card_key(tcg, "card_name", "set_name", "card_number")
            merged = tcg
            logger.info(f"Loaded Pokemon TCG: {len(tcg)} records")

        # Source 2: PriceCharting (prices)
        pc = self.load_raw_data("pricecharting_cards.csv")
        if pc is not None:
            pc_adapted = self._adapt_pricecharting(pc)
            pc_adapted["_key"] = self._create_card_key(pc_adapted, "card_name", "set_name", "card_number")
            if merged is None:
                merged = pc_adapted
            else:
                # Find keys only in PriceCharting (not in merged)
                existing_keys = set(merged["_key"])
                pc_only = pc_adapted[~pc_adapted["_key"].isin(existing_keys)]

                # Add new cards from PriceCharting (they already have all price columns)
                if len(pc_only) > 0:
                    merged = pd.concat([merged, pc_only], ignore_index=True)
                    logger.info(f"Added {len(pc_only)} new cards from PriceCharting")

                # For overlapping cards (in both TCG and PC), add price columns
                # Only update rows that don't already have pc_price_ungraded
                pc["_key"] = self._create_card_key(pc, "card_name", "set_name", "card_number")
                overlapping_keys = existing_keys & set(pc["_key"])
                if overlapping_keys:
                    price_cols = ["_key"]
                    col_renames = {}
                    for col, new_name in [
                        ("price_ungraded", "pc_price_ungraded"),
                        ("price_graded", "pc_price_graded"),
                        ("price_sealed", "pc_price_complete"),
                        ("is_first_edition", "pc_first_edition"),
                        ("is_shadowless", "pc_shadowless"),
                    ]:
                        if col in pc.columns:
                            price_cols.append(col)
                            col_renames[col] = new_name
                    pc_cols = pc[pc["_key"].isin(overlapping_keys)][price_cols].copy()
                    pc_cols = pc_cols.rename(columns=col_renames)
                    # Drop duplicates (take first, usually highest value variant)
                    pc_cols = pc_cols.drop_duplicates(subset=["_key"], keep="first")
                    # Merge only for rows without existing pc prices
                    merged = merged.merge(pc_cols, on="_key", how="left", suffixes=("", "_new"))
                    # Coalesce: use existing value if present, else new value
                    for col in ["pc_price_ungraded", "pc_price_graded", "pc_price_complete", "pc_first_edition", "pc_shadowless"]:
                        if f"{col}_new" in merged.columns:
                            merged[col] = merged[col].fillna(merged[f"{col}_new"])
                            merged = merged.drop(columns=[f"{col}_new"])
                    logger.info(f"Added prices for {len(overlapping_keys)} overlapping cards")
            logger.info(f"Loaded PriceCharting: {len(pc)} records")

        # Source 3: Pokellector (images)
        pokellector = self.load_raw_data("pokellector_cards.csv")
        if pokellector is not None:
            pokellector["_key"] = self._create_card_key(pokellector, "card_name", "set_name", "card_number")
            if merged is None:
                merged = self._adapt_pokellector(pokellector)
                merged["_key"] = self._create_card_key(merged, "card_name", "set_name", "card_number")
            else:
                pk_cols = pokellector[["_key", "image_url"]].copy()
                pk_cols = pk_cols.rename(columns={"image_url": "pokellector_image"})
                merged = merged.merge(pk_cols, on="_key", how="left")
            logger.info(f"Loaded Pokellector: {len(pokellector)} records")

        # Source 4: PKMNCards (high-res images)
        pkmn = self.load_raw_data("pkmncards_cards.csv")
        if pkmn is not None:
            pkmn["_key"] = self._create_card_key(pkmn, "card_name", "set_name", "card_number")
            if merged is None:
                merged = self._adapt_pkmncards(pkmn)
                merged["_key"] = self._create_card_key(merged, "card_name", "set_name", "card_number")
            else:
                pm_cols = pkmn[["_key", "image_url", "card_url"]].copy()
                pm_cols = pm_cols.rename(columns={"image_url": "pkmncards_image", "card_url": "pkmncards_url"})
                merged = merged.merge(pm_cols, on="_key", how="left")
            logger.info(f"Loaded PKMNCards: {len(pkmn)} records")

        # Source 5: PSA Population
        psa = self.load_raw_data("psa_population.csv")
        if psa is not None and len(psa) > 0:
            psa["_key"] = self._create_card_key(psa, "card_name", "set_name", "card_number")
            psa_cols = psa[["_key", "total_graded", "psa_10_count", "psa_9_count", "psa_10_pct"]].copy()
            if merged is not None:
                merged = merged.merge(psa_cols, on="_key", how="outer")
            logger.info(f"Loaded PSA: {len(psa)} records")

        # Source 6: Sold Prices
        sold = self.load_raw_data("sold_prices.csv")
        if sold is not None and len(sold) > 0:
            sold["_key"] = self._create_card_key(sold, "card_name", "set_name", "card_number")
            sold_cols = sold[["_key", "avg_sold_price", "min_sold_price", "max_sold_price", "num_sales"]].copy()
            if merged is not None:
                merged = merged.merge(sold_cols, on="_key", how="outer")
            logger.info(f"Loaded Sold Prices: {len(sold)} records")

        if merged is not None:
            merged = merged.drop(columns=["_key"], errors="ignore")
            # Remove duplicate rows
            merged = merged.drop_duplicates(subset=["card_name", "set_name", "card_number"])

        return merged

    def _adapt_pokemon_tcg(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adapt Pokemon TCG API data to common format."""
        return pd.DataFrame({
            "card_id": df["id"],
            "data_source": df["data_source"],
            "card_name": df["name"],
            "set_name": df["set_name"],
            "set_code": df["set_id"],
            "card_number": df["number"],
            "rarity": df["rarity"],
            "series": df["set_series"],
            "release_date": df["set_release_date"],
            "artist": df["artist"],
            "supertype": df["supertype"],
            "subtypes": df["subtypes"],
            "hp": df["hp"],
            "types": df["types"],
            "evolves_from": df["evolvesFrom"],
            "national_dex": df["nationalPokedexNumbers"],
            "tcgplayer_price_low": df["tcgplayer_price_low"],
            "tcgplayer_price_mid": df["tcgplayer_price_mid"],
            "tcgplayer_price_high": df["tcgplayer_price_high"],
            "tcgplayer_price_market": df["tcgplayer_price_market"],
            "tcgplayer_updated_at": df["tcgplayer_updated_at"],
            "image_small": df["image_small"],
            "image_large": df["image_large"],
        })

    def _adapt_pokellector(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adapt Pokellector data to common format when used as primary."""
        return pd.DataFrame({
            "card_id": df["card_id"],
            "data_source": df["data_source"],
            "card_name": df["card_name"],
            "set_name": df["set_name"],
            "set_code": df.get("set_slug", df.get("set_code", "")),
            "card_number": df["card_number"],
            "rarity": None,
            "series": None,
            "release_date": None,
            "artist": None,
            "supertype": "Pokémon",
            "subtypes": None,
            "hp": None,
            "types": None,
            "evolves_from": None,
            "national_dex": None,
            "tcgplayer_price_low": None,
            "tcgplayer_price_mid": None,
            "tcgplayer_price_high": None,
            "tcgplayer_price_market": None,
            "tcgplayer_updated_at": None,
            "image_small": df["image_url"],
            "image_large": df["image_url"],
            "pokellector_image": df["image_url"],
        })

    def _adapt_pkmncards(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adapt PKMNCards data to common format when used as primary."""
        return pd.DataFrame({
            "card_id": df["card_id"],
            "data_source": df["data_source"],
            "card_name": df["card_name"],
            "set_name": df["set_name"],
            "set_code": df.get("set_code", ""),
            "card_number": df["card_number"],
            "rarity": None,
            "series": None,
            "release_date": None,
            "artist": None,
            "supertype": "Pokémon",
            "subtypes": None,
            "hp": None,
            "types": None,
            "evolves_from": None,
            "national_dex": None,
            "tcgplayer_price_low": None,
            "tcgplayer_price_mid": None,
            "tcgplayer_price_high": None,
            "tcgplayer_price_market": None,
            "tcgplayer_updated_at": None,
            "image_small": df["image_url"],
            "image_large": df["image_url"],
            "pkmncards_image": df["image_url"],
            "pkmncards_url": df["card_url"],
        })

    def normalize_all(self) -> dict[str, pd.DataFrame]:
        """Run full normalization pipeline, merging all available sources."""
        logger.info("Starting normalization pipeline")

        # Load and merge all available data sources
        df = self._load_and_merge_all_sources()

        if df is None:
            raise FileNotFoundError("No raw data available. Run scraping first.")

        logger.info(f"Merged {len(df)} unique cards from all sources")

        results = {
            "card_master": self.normalize_master(df),
            "card_attributes": self.normalize_attributes(df),
            "card_pricing": self.normalize_pricing(df),
        }

        for name, data in results.items():
            output_path = self.normalized_dir / f"{name}.csv"
            data.to_csv(output_path, index=False, encoding="utf-8")
            logger.info(f"Saved {name}.csv: {len(data)} rows")

        return results

    def _adapt_pricecharting(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adapt PriceCharting data to common format."""
        return pd.DataFrame({
            "card_id": df.get("pricecharting_id", df.index.astype(str)),
            "data_source": df.get("data_source", "PRICECHARTING"),
            "card_name": df.get("card_name", ""),
            "set_name": df.get("set_name", ""),
            "set_code": df.get("set_slug", ""),
            "card_number": df.get("card_number", ""),
            "rarity": None,
            "series": None,
            "release_date": None,
            "artist": None,
            "supertype": "Pokémon",
            "subtypes": None,
            "hp": None,
            "types": None,
            "evolves_from": None,
            "national_dex": None,
            "tcgplayer_price_low": None,
            "tcgplayer_price_mid": df.get("price_ungraded"),
            "tcgplayer_price_high": df.get("price_graded"),
            "tcgplayer_price_market": df.get("price_ungraded"),
            "tcgplayer_updated_at": None,
            "image_small": None,
            "image_large": None,
            # Include PriceCharting-specific fields
            "pc_price_ungraded": df.get("price_ungraded"),
            "pc_price_graded": df.get("price_graded"),
            "pc_price_complete": df.get("price_sealed"),
            "pc_first_edition": df.get("is_first_edition", False),
            "pc_shadowless": df.get("is_shadowless", False),
        })

    def create_feature_store(self, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Join normalized tables into final feature store."""
        logger.info("Creating feature store")

        # Start with master
        features = tables["card_master"].copy()

        # Join attributes
        features = features.merge(
            tables["card_attributes"].drop(columns=["card_id"]),
            left_index=True,
            right_index=True,
            how="left",
        )

        # Join pricing
        features = features.merge(
            tables["card_pricing"].drop(columns=["card_id"]),
            left_index=True,
            right_index=True,
            how="left",
        )

        # Calculate derived features
        features["days_since_release"] = (
            pd.to_datetime("today") - pd.to_datetime(features["release_date"])
        ).dt.days

        # Calculate completeness score
        features["completeness_score"] = (
            features.notna().sum(axis=1) / len(features.columns) * 100
        ).round(2)

        return features


def main():
    """Run normalizer standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    normalizer = CardNormalizer()
    tables = normalizer.normalize_all()

    print("\n✓ Normalization complete:")
    for name, data in tables.items():
        print(f"  - {name}.csv: {len(data)} rows")


if __name__ == "__main__":
    main()
