"""
ingest.py — Raw Feed Ingestion into PostgreSQL
===============================================

Reads all raw feed files from ../data/raw/, normalizes them into the
canonical part_events schema, and bulk-inserts into Postgres.

This script is intentionally "dumb" — no validation logic here.
Just get raw data into canonical shape.
"""

import os
import csv
import json
import sys
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host": os.environ.get("PGHOST", "localhost"),
    "port": int(os.environ.get("PGPORT", 5433)),
    "dbname": os.environ.get("PGDATABASE", "factory_trace"),
    "user": os.environ.get("PGUSER", "admin"),
    "password": os.environ.get("PGPASSWORD", "admin123"),
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "..", "data", "raw")

# Column name mappings — handles messy feed formats
COLUMN_MAPS = {
    # JSON feed uses camelCase
    "partId": "part_id",
    "stationName": "station",
    "eventType": "event_type",
    "timestamp": "event_ts",
    # CSV feeds already use snake_case (but just in case)
    "part_id": "part_id",
    "station": "station",
    "event_type": "event_type",
    "event_ts": "event_ts",
}

CANONICAL_COLUMNS = ["part_id", "station", "event_type", "event_ts"]


def get_connection():
    """Get a psycopg2 connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        return conn
    except psycopg2.OperationalError as e:
        print(f"[ERROR] Could not connect to PostgreSQL: {e}")
        print("  Make sure the Postgres container is running (docker-compose up -d)")
        sys.exit(1)


def read_csv_feed(filepath):
    """Read a CSV feed file into a list of dicts."""
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(dict(row))
    return records


def read_json_feed(filepath):
    """Read a JSON feed file into a list of dicts."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return [data]


def normalize_records(records, source_file):
    """
    Normalize column names to canonical schema and add source_file.
    Handles both snake_case (CSV) and camelCase (JSON) column names.
    """
    normalized = []
    for raw in records:
        row = {}
        for raw_key, value in raw.items():
            canonical_key = COLUMN_MAPS.get(raw_key, raw_key)
            if canonical_key in CANONICAL_COLUMNS:
                row[canonical_key] = value
        row["source_file"] = source_file

        # Handle empty strings as None
        for col in CANONICAL_COLUMNS:
            if col in row and row[col] in ("", "None", "null"):
                row[col] = None

        # Try to parse event_ts (leave None if unparseable)
        if row.get("event_ts"):
            try:
                datetime.fromisoformat(str(row["event_ts"]))
            except (ValueError, TypeError):
                row["event_ts"] = None  # Will be caught by validation later

        normalized.append(row)
    return normalized


def load_parts_registry(conn):
    """Load the parts registry into the parts table (upsert)."""
    registry_path = os.path.join(RAW_DIR, "parts_registry.csv")
    if not os.path.exists(registry_path):
        print("  [WARN] No parts_registry.csv found -- skipping parts table load")
        return 0

    records = read_csv_feed(registry_path)
    cur = conn.cursor()

    # Upsert parts
    values = []
    for r in records:
        values.append((
            r["part_id"],
            r["product_line"],
            r.get("created_at"),
        ))

    execute_values(
        cur,
        """
        INSERT INTO parts (part_id, product_line, created_at)
        VALUES %s
        ON CONFLICT (part_id) DO UPDATE SET
            product_line = EXCLUDED.product_line
        """,
        values
    )
    conn.commit()
    print(f"  [OK] Loaded {len(values)} parts into parts table")
    return len(values)


def load_events(conn, records):
    """Bulk insert normalized events into part_events."""
    if not records:
        return 0

    cur = conn.cursor()
    values = []
    for r in records:
        values.append((
            r.get("part_id"),
            r.get("station"),
            r.get("event_type"),
            r.get("event_ts"),
            r.get("source_file"),
        ))

    execute_values(
        cur,
        """
        INSERT INTO part_events (part_id, station, event_type, event_ts, source_file)
        VALUES %s
        """,
        values
    )
    conn.commit()
    return len(values)


def clear_existing_data(conn):
    """Clear existing data for idempotent re-runs."""
    cur = conn.cursor()
    cur.execute("DELETE FROM data_quality_flags")
    cur.execute("DELETE FROM part_events")
    cur.execute("DELETE FROM parts")
    conn.commit()
    print("  [OK] Cleared existing data (idempotent re-run)")


def main():
    print("=" * 60)
    print("FACTORY TRACEABILITY - Ingestion Pipeline")
    print("=" * 60)

    # Connect
    print("\n[1/4] Connecting to PostgreSQL...")
    conn = get_connection()
    print(f"  [OK] Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")

    # Clear old data
    print("\n[2/4] Clearing existing data...")
    clear_existing_data(conn)

    # Load parts registry
    print("\n[3/4] Loading parts registry...")
    load_parts_registry(conn)

    # Discover and ingest feed files
    print("\n[4/4] Ingesting station feed files...")
    if not os.path.exists(RAW_DIR):
        print(f"  [ERROR] Raw data directory not found: {RAW_DIR}")
        print("  Run generator/generate_feeds.py first!")
        sys.exit(1)

    total_events = 0
    feed_files = sorted([
        f for f in os.listdir(RAW_DIR)
        if f.endswith((".csv", ".json")) and f != "parts_registry.csv"
    ])

    if not feed_files:
        print("  [ERROR] No feed files found in data/raw/")
        print("  Run generator/generate_feeds.py first!")
        sys.exit(1)

    for filename in feed_files:
        filepath = os.path.join(RAW_DIR, filename)
        print(f"\n  Processing: {filename}")

        # Auto-detect format
        if filename.endswith(".csv"):
            raw_records = read_csv_feed(filepath)
        elif filename.endswith(".json"):
            raw_records = read_json_feed(filepath)
        else:
            print(f"    [WARN] Unsupported format, skipping")
            continue

        # Normalize
        normalized = normalize_records(raw_records, source_file=filename)
        print(f"    -> Normalized {len(normalized)} records")

        # Load
        count = load_events(conn, normalized)
        total_events += count
        print(f"    -> Inserted {count} events into part_events")

    # Summary
    conn.close()
    print("\n" + "=" * 60)
    print(f"DONE - Ingested {total_events} events from {len(feed_files)} feed files")
    print("=" * 60)


if __name__ == "__main__":
    main()
