"""
validate.py — Data Quality Validation Layer
=============================================

Reads part_events from PostgreSQL, applies four validation rules,
and writes flagged issues into the data_quality_flags table.

Validation Rules:
  1. DUPLICATE_SCAN       — same part_id + station appears more than once
  2. MISSING_TIMESTAMP    — null event_ts
  3. PART_ID_MISMATCH     — part_id not in parts table
  4. OUT_OF_SEQUENCE      — downstream station timestamp before upstream

Expected station order: component_scan → quality_check → packaging
"""

import os
import sys

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import create_engine

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

STATION_ORDER = {
    "component_scan": 1,
    "quality_check": 2,
    "packaging": 3,
}


def get_connection():
    """Get a psycopg2 connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        return conn
    except psycopg2.OperationalError as e:
        print(f"[ERROR] Could not connect to PostgreSQL: {e}")
        sys.exit(1)


def get_engine():
    """Get a SQLAlchemy engine for pd.read_sql."""
    return create_engine(
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@"
        f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    )


def load_events(engine):
    """Load all part_events into a DataFrame."""
    query = """
        SELECT event_id, part_id, station, event_type, event_ts, source_file
        FROM part_events
        ORDER BY part_id, event_ts
    """
    df = pd.read_sql(query, engine)
    return df


def load_valid_parts(engine):
    """Load all valid part_ids from the parts table."""
    query = "SELECT part_id FROM parts"
    df = pd.read_sql(query, engine)
    return set(df["part_id"].tolist())


def clear_flags(conn):
    """Clear existing flags for idempotent re-runs."""
    cur = conn.cursor()
    cur.execute("DELETE FROM data_quality_flags")
    conn.commit()


def insert_flags(conn, flags):
    """Bulk insert quality flags."""
    if not flags:
        return 0

    cur = conn.cursor()
    execute_values(
        cur,
        """
        INSERT INTO data_quality_flags (event_id, flag_type, description)
        VALUES %s
        """,
        flags
    )
    conn.commit()
    return len(flags)


# ---------------------------------------------------------------------------
# Validation Rule Implementations
# ---------------------------------------------------------------------------

def check_duplicate_scans(df):
    """
    Rule 1: DUPLICATE_SCAN
    Same part_id + station appears more than once.
    Flag all occurrences after the first.
    """
    flags = []
    duplicates = df[df.duplicated(subset=["part_id", "station"], keep="first")]

    for _, row in duplicates.iterrows():
        flags.append((
            int(row["event_id"]),
            "DUPLICATE_SCAN",
            f"Duplicate scan detected for part {row['part_id']} at station {row['station']}"
        ))

    return flags


def check_missing_timestamps(df):
    """
    Rule 2: MISSING_TIMESTAMP
    Null event_ts values.
    """
    flags = []
    missing = df[df["event_ts"].isna()]

    for _, row in missing.iterrows():
        flags.append((
            int(row["event_id"]),
            "MISSING_TIMESTAMP",
            f"Missing or unparseable timestamp for part {row['part_id']} at station {row['station']}"
        ))

    return flags


def check_part_id_mismatch(df, valid_parts):
    """
    Rule 3: PART_ID_MISMATCH
    part_id in event that doesn't exist in the parts table.
    """
    flags = []
    for _, row in df.iterrows():
        if row["part_id"] not in valid_parts:
            flags.append((
                int(row["event_id"]),
                "PART_ID_MISMATCH",
                f"Part ID {row['part_id']} not found in parts registry"
            ))

    return flags


def check_out_of_sequence(df):
    """
    Rule 4: OUT_OF_SEQUENCE
    A downstream station has a timestamp earlier than an upstream station
    for the same part.

    Expected order: component_scan (1) → quality_check (2) → packaging (3)
    """
    flags = []

    # Only check rows with valid timestamps and known stations
    valid = df[
        df["event_ts"].notna() &
        df["station"].isin(STATION_ORDER.keys())
    ].copy()

    valid["station_order"] = valid["station"].map(STATION_ORDER)

    # Group by part_id and check ordering
    for part_id, group in valid.groupby("part_id"):
        if len(group) < 2:
            continue

        sorted_group = group.sort_values("station_order")
        prev_ts = None
        prev_station = None

        for _, row in sorted_group.iterrows():
            if prev_ts is not None and row["event_ts"] < prev_ts:
                flags.append((
                    int(row["event_id"]),
                    "OUT_OF_SEQUENCE",
                    f"Part {part_id}: {row['station']} timestamp "
                    f"({row['event_ts']}) is earlier than {prev_station} "
                    f"({prev_ts}) -- expected sequential ordering"
                ))
            prev_ts = row["event_ts"]
            prev_station = row["station"]

    return flags


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("FACTORY TRACEABILITY - Validation Pipeline")
    print("=" * 60)

    # Connect
    print("\n[1/6] Connecting to PostgreSQL...")
    conn = get_connection()
    engine = get_engine()
    print(f"  [OK] Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")

    # Load data
    print("\n[2/6] Loading part_events...")
    df = load_events(engine)
    print(f"  [OK] Loaded {len(df)} events")

    if df.empty:
        print("  [WARN] No events found -- run ingest.py first!")
        sys.exit(1)

    valid_parts = load_valid_parts(engine)
    print(f"  [OK] Loaded {len(valid_parts)} valid part IDs from parts registry")

    # Clear old flags
    print("\n[3/6] Clearing existing flags...")
    clear_flags(conn)
    print("  [OK] Cleared")

    # Run validations
    all_flags = []

    print("\n[4/6] Running validation rules...")

    # Rule 1: Duplicate scans
    dup_flags = check_duplicate_scans(df)
    all_flags.extend(dup_flags)
    print(f"  -> DUPLICATE_SCAN:     {len(dup_flags)} flags")

    # Rule 2: Missing timestamps
    ts_flags = check_missing_timestamps(df)
    all_flags.extend(ts_flags)
    print(f"  -> MISSING_TIMESTAMP:  {len(ts_flags)} flags")

    # Rule 3: Part ID mismatch
    id_flags = check_part_id_mismatch(df, valid_parts)
    all_flags.extend(id_flags)
    print(f"  -> PART_ID_MISMATCH:   {len(id_flags)} flags")

    # Rule 4: Out of sequence
    seq_flags = check_out_of_sequence(df)
    all_flags.extend(seq_flags)
    print(f"  -> OUT_OF_SEQUENCE:    {len(seq_flags)} flags")

    # Insert flags
    print(f"\n[5/6] Inserting {len(all_flags)} flags into data_quality_flags...")
    inserted = insert_flags(conn, all_flags)
    print(f"  [OK] Inserted {inserted} flags")

    # Summary
    print(f"\n[6/6] Validation summary:")
    print(f"  +-------------------------+-------+")
    print(f"  | Flag Type               | Count |")
    print(f"  +-------------------------+-------+")
    print(f"  | DUPLICATE_SCAN          | {len(dup_flags):>5} |")
    print(f"  | MISSING_TIMESTAMP       | {len(ts_flags):>5} |")
    print(f"  | PART_ID_MISMATCH        | {len(id_flags):>5} |")
    print(f"  | OUT_OF_SEQUENCE         | {len(seq_flags):>5} |")
    print(f"  +-------------------------+-------+")
    print(f"  | TOTAL                   | {len(all_flags):>5} |")
    print(f"  +-------------------------+-------+")

    conn.close()
    print("\n" + "=" * 60)
    print("DONE - Validation complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
