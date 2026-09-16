"""Snowflake connection + the cached snapshot loader.

Local runs read ``~/.snowflake/connections.toml``; the entry is selected by
``SNOWFLAKE_DEFAULT_CONNECTION_NAME`` and defaults to FANATICS_COLLECTIBLES_PROD
so ``streamlit run`` works with no extra env setup. Override either value at
launch:

    $env:SNOWFLAKE_DEFAULT_CONNECTION_NAME = "FANATICS_COLLECTIBLES_DEV"
    $env:SNOWFLAKE_WAREHOUSE = "MY_WH"

Deployed to the Streamlit-in-Snowflake CONTAINER runtime (SPCS under the hood)
there is no connections.toml and no browser for OAuth. Snowflake injects an
OAuth login token at /snowflake/session/token plus SNOWFLAKE_ACCOUNT /
SNOWFLAKE_HOST; we detect those and connect as the app's owner role.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import queries
import transforms as tx  # ordered aging categories; imports only pandas (no cycle)

_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE") or "ANALYTICS_WAREHOUSE"

# Snowpark Container Services — and the Streamlit-in-Snowflake CONTAINER runtime,
# which is SPCS under the hood — mounts a short-lived OAuth login token here and
# sets SNOWFLAKE_ACCOUNT / SNOWFLAKE_HOST. Its presence means we are running
# INSIDE Snowflake rather than on a laptop.
_SPCS_TOKEN_PATH = "/snowflake/session/token"

# How long a pulled snapshot stays warm. The loader and the inner conn.query
# cache share this value and the same SQL text, so both layers fill and expire
# together and the freshness stamp cannot drift away from the data it describes.
_TTL = timedelta(hours=2)


def _running_in_snowflake() -> bool:
    """True when hosted by Streamlit-in-Snowflake or a Snowpark Container service."""
    if os.path.exists(_SPCS_TOKEN_PATH):
        return True
    try:
        from snowflake.snowpark.context import get_active_session

        get_active_session()
        return True
    except Exception:
        return False


# Local `streamlit run` ONLY: select the connections.toml entry. When hosted in
# Streamlit-in-Snowflake the runtime provides a connection named 'default';
# overriding SNOWFLAKE_DEFAULT_CONNECTION_NAME there makes the connector search
# for a named connection that does not exist ("Default connection ... cannot be
# found, known ones are ['default']"). So set it only when NOT hosted.
#
# NOTE the default is a real connection name, not the literal "default": this
# machine's connections.toml has no entry called "default", so that would break
# local runs outright.
if not _running_in_snowflake():
    _CONN_NAME = os.getenv("SNOWFLAKE_DEFAULT_CONNECTION_NAME") or "FANATICS_COLLECTIBLES_PROD"
    os.environ["SNOWFLAKE_DEFAULT_CONNECTION_NAME"] = _CONN_NAME


def _spcs_connection_kwargs() -> dict | None:
    """Connector kwargs for a standalone Snowpark Container Services run.

    Returns None when the SPCS login token is absent, so callers fall back to the
    connections.toml / in-DB session behaviour.
    """
    try:
        with open(_SPCS_TOKEN_PATH) as f:
            token = f.read()
    except OSError:
        return None
    return {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "host": os.environ["SNOWFLAKE_HOST"],
        "authenticator": "oauth",
        "token": token,
        "warehouse": _WAREHOUSE,
    }


@st.cache_resource(show_spinner=False)
def _connection():
    """One pooled Snowflake connection for the app session.

    Locally, naming the connection "snowflake" with no extra kwargs makes
    Streamlit call the connector with no args, which loads the entry selected by
    SNOWFLAKE_DEFAULT_CONNECTION_NAME. Hosted in Streamlit-in-Snowflake (either
    runtime) the platform supplies the session through its built-in 'default'
    connection, so again: no name override, no extra kwargs. Only a standalone
    SPCS *service* needs the injected OAuth token.
    """
    if _running_in_snowflake():
        try:
            conn = st.connection("snowflake", type="snowflake")
        except Exception:
            # Standalone SPCS service: no 'default' connection — use the token.
            spcs = _spcs_connection_kwargs()
            conn = (
                st.connection("snowflake", type="snowflake", **spcs)
                if spcs is not None
                else st.connection("snowflake", type="snowflake")
            )
    else:
        conn = st.connection("snowflake", type="snowflake")
    if _WAREHOUSE:
        try:
            conn.query(f"USE WAREHOUSE {_WAREHOUSE}", ttl=0)
        except Exception:
            pass
    return conn


# Measures arrive as Snowflake NUMBER -> Python Decimal, which pandas holds as
# object dtype; arithmetic and .sum() then behave unpredictably (Decimal/float
# TypeErrors). Coerce every one to float up front.
_NUMERIC_COLS = (
    "quantity_cases",
    "unit_cost_per_case",
    "inventory_value",
    "dealernet_price_per_case",
    "dn_listing_count",
    "year_priority",
    "market_value",
    "wholesale_value",
    "total_potential_profit",
    "margin_dollars_per_case",
    "markup_multiple",
    "margin_pct",
    "boxes_per_case",
    "packs_per_box",
    "cards_per_pack",
    "street_date_year",
)

# Text columns where SQL NULL must read as a real missing value rather than the
# string "None" once it reaches a formatter or a filter dropdown.
_TEXT_COLS = (
    "item_number",
    "item_key",
    "product_name",
    "brand",
    "brand_bucket",
    "box_type",
    "aging_bucket",
    "dealernet_name",
    "price_source",
    "year_match_type",
    "mapping_status",
    "street_date_month_label",
)


@st.cache_data(ttl=_TTL, show_spinner="Loading vault inventory…")
def load_inventory() -> tuple[pd.DataFrame, datetime]:
    """The full SKU-grain snapshot, one row per ``item_key``.

    Returns ``(df, pulled_at)``. ``pulled_at`` is the UTC instant the SELECT
    actually ran, captured INSIDE the cached body so a cache HIT keeps the
    original pull time — that is what makes it a real freshness stamp instead of
    a render clock. ``st.cache_data.clear()`` (the ↻ Refresh button) forces a new
    pull and therefore a new stamp.

    There is no as-of argument: ``queries.INVENTORY_SQL`` pins the open SCD2
    record, so this is always the live snapshot.
    """
    df = _connection().query(queries.INVENTORY_SQL, ttl=_TTL)
    pulled_at = datetime.now(timezone.utc)

    df.columns = [c.lower() for c in df.columns]

    for c in _NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Additive measures: a NULL would poison sums and the footer totals. The
    # ratio columns (margin_pct, markup_multiple) are deliberately NOT filled —
    # NULL there means "unpriced", which must render as an em dash, not 0%.
    # market_value and wholesale_value are likewise left NULL for unpriced rows:
    # pandas .sum() skips NaN, which is exactly Sigma's NULL-skipping Sum, so
    # filling them with 0.0 would change nothing but lose the "unpriced" signal.
    for c in ("quantity_cases", "inventory_value"):
        if c in df.columns:
            df[c] = df[c].fillna(0.0)

    for c in _TEXT_COLS:
        if c in df.columns:
            df[c] = df[c].astype("object").where(df[c].notna(), None)

    df["street_date"] = pd.to_datetime(df["street_date"], errors="coerce")
    df["dn_latest_date"] = pd.to_datetime(df["dn_latest_date"], errors="coerce")

    # street_date_year drives a filter dropdown, so it must be a clean nullable
    # integer — a float would render as "2024.0".
    if "street_date_year" in df.columns:
        df["street_date_year"] = df["street_date_year"].astype("Int64")

    # The SQL already assigns the bucket; making it an ORDERED categorical here is
    # what keeps the donuts, the legend and the filter dropdown in ramp order
    # (oldest last) and keeps empty buckets visible as zero rows.
    df["aging_bucket"] = tx.as_aging_category(df["aging_bucket"])

    return df, pulled_at
