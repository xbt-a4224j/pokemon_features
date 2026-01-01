"""Simple admin UI for Pokemon Feature Store."""

import subprocess
import pandas as pd
import streamlit as st
from pathlib import Path

from config import CRAWL_STATUS_FILE, DEMO_CARD_LIMIT
from crawl_status import CrawlStatus

# Paths
OUTPUT_DIR = Path(__file__).parent / "outputs"
FEATURE_STORE = OUTPUT_DIR / "feature_store" / "features_complete.csv"
NORMALIZED_DIR = OUTPUT_DIR / "normalized"
RAW_DIR = OUTPUT_DIR / "raw_data"

st.set_page_config(page_title="Pokemon Feature Store", layout="wide")

st.title("Pokemon Feature Store Admin")

# Load crawl status for offset info
crawl_status = CrawlStatus(CRAWL_STATUS_FILE)
current_offset = crawl_status.get_offset("pricecharting")


# Stats section
st.header("Dataset Stats")

col1, col2, col3, col4 = st.columns(4)

if FEATURE_STORE.exists():
    df = pd.read_csv(FEATURE_STORE)
    with col1:
        st.metric("Total Cards", len(df))
    with col2:
        st.metric("Scraped So Far", current_offset, help="Cards fetched from PriceCharting")
    with col3:
        has_price = df["price_ungraded"].notna().sum()
        st.metric("With Pricing", f"{has_price} ({100*has_price/len(df):.0f}%)")
    with col4:
        st.metric("Sets", df["set_name"].nunique())
else:
    st.warning("No feature store data. Run scraper first.")
    df = None


# Add More button
st.header("Actions")

# Show current progress
next_batch_start = current_offset + 1
next_batch_end = current_offset + DEMO_CARD_LIMIT
st.caption(f"Currently at card #{current_offset}. Next batch: cards #{next_batch_start}-{next_batch_end}")

col1, col2 = st.columns(2)

with col1:
    if st.button(f"Add {DEMO_CARD_LIMIT} More Cards", type="primary"):
        with st.spinner(f"Fetching cards #{next_batch_start}-{next_batch_end}..."):
            result = subprocess.run(
                ["uv", "run", "python", "main.py", "--resume", "--quiet"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent,
            )
            # Extract just the summary line
            output = result.stdout.strip().split("\n")[-1] if result.stdout else ""
            if result.returncode == 0:
                if "No new cards" in output:
                    st.info(output)
                else:
                    st.success(output)
                st.rerun()  # Auto-refresh to show new data
            else:
                st.error("Scraper failed")
                st.code(result.stderr or result.stdout)

with col2:
    if st.button("Reset & Start Fresh"):
        # Clear crawl status to start from 0
        crawl_status.clear("pricecharting")
        st.success("Reset! Click 'Add More Cards' to start from the beginning.")
        st.rerun()


# Data tables
st.header("Browse Data")

tab1, tab2, tab3, tab4 = st.tabs(["Feature Store", "Card Master", "Card Pricing", "Raw Data"])

with tab1:
    if df is not None:
        st.dataframe(df, use_container_width=True, height=400)
        st.download_button(
            "Download CSV",
            df.to_csv(index=False),
            "features_complete.csv",
            "text/csv",
        )

with tab2:
    master_path = NORMALIZED_DIR / "card_master.csv"
    if master_path.exists():
        master = pd.read_csv(master_path)
        st.dataframe(master, use_container_width=True, height=400)

with tab3:
    pricing_path = NORMALIZED_DIR / "card_pricing.csv"
    if pricing_path.exists():
        pricing = pd.read_csv(pricing_path)
        st.dataframe(pricing, use_container_width=True, height=400)

with tab4:
    raw_files = list(RAW_DIR.glob("*.csv")) if RAW_DIR.exists() else []
    if raw_files:
        selected = st.selectbox("Select file", [f.name for f in raw_files])
        if selected:
            raw_df = pd.read_csv(RAW_DIR / selected)
            st.write(f"**{len(raw_df)} rows**")
            st.dataframe(raw_df, use_container_width=True, height=400)


# Set breakdown
if df is not None:
    st.header("Cards by Set")
    set_counts = df.groupby("set_name").size().sort_values(ascending=False)
    st.bar_chart(set_counts)
