"""
generate_feeds.py — Synthetic Factory Station Data Generator
============================================================

Generates ~80 synthetic parts across 3 station feeds (component_scan,
quality_check, packaging) and deliberately injects data-quality problems:

  • Duplicate scans          (same part_id + station repeated)
  • Missing timestamps       (null / unparseable event_ts)
  • Part-ID mismatches       (IDs that won't exist in the parts table)
  • Out-of-sequence events   (downstream timestamp before upstream)

Outputs land in ../data/raw/ as a mix of CSV and JSON.
"""

import os
import csv
import json
import random
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NUM_PARTS = 80
PRODUCT_LINES = ["Smartphone_X", "Laptop_Pro_14", "Wireless_Earbuds_Gen3", "Smartwatch_Ultra"]
STATIONS = ["component_scan", "quality_check", "packaging"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "..", "data", "raw")
PARTS_REGISTRY = os.path.join(RAW_DIR, "parts_registry.csv")

# Anomaly injection counts
NUM_DUPLICATES = 7
NUM_MISSING_TS = 5
NUM_MISMATCHES = 4
NUM_OUT_OF_SEQ = 5


def generate_parts():
    """Create a registry of valid parts."""
    parts = []
    for i in range(NUM_PARTS):
        part_id = f"PART-{fake.bothify('??##??').upper()}-{i:04d}"
        product_line = random.choice(PRODUCT_LINES)
        created_at = fake.date_time_between(start_date="-30d", end_date="now")
        parts.append({
            "part_id": part_id,
            "product_line": product_line,
            "created_at": created_at.isoformat(),
        })
    return parts


def generate_station_events(parts):
    """
    For each part, generate events at each station in order.
    Returns three lists: component_scan events, quality_check events, packaging events.
    """
    component_scan_events = []
    quality_check_events = []
    packaging_events = []

    for part in parts:
        # Base time: some time after part creation
        base_ts = datetime.fromisoformat(part["created_at"]) + timedelta(hours=random.randint(1, 12))

        # Station 1: component_scan
        cs_ts = base_ts + timedelta(minutes=random.randint(5, 60))
        component_scan_events.append({
            "part_id": part["part_id"],
            "station": "component_scan",
            "event_type": "scan_complete",
            "event_ts": cs_ts.isoformat(),
        })

        # Station 2: quality_check (after component_scan)
        qc_ts = cs_ts + timedelta(minutes=random.randint(30, 180))
        quality_check_events.append({
            "part_id": part["part_id"],
            "station": "quality_check",
            "event_type": "inspection_pass",
            "event_ts": qc_ts.isoformat(),
        })

        # Station 3: packaging (after quality_check)
        pk_ts = qc_ts + timedelta(minutes=random.randint(15, 120))
        packaging_events.append({
            "part_id": part["part_id"],
            "station": "packaging",
            "event_type": "package_sealed",
            "event_ts": pk_ts.isoformat(),
        })

    return component_scan_events, quality_check_events, packaging_events


def inject_duplicates(events_list, count):
    """Inject duplicate scans (same part_id + station repeated)."""
    injected = 0
    sample = random.sample(range(len(events_list)), min(count, len(events_list)))
    for idx in sample:
        dup = dict(events_list[idx])
        dup["event_type"] = dup["event_type"] + "_dup"
        events_list.append(dup)
        injected += 1
    print(f"  [OK] Injected {injected} DUPLICATE_SCAN anomalies")
    return events_list


def inject_missing_timestamps(events_list, count):
    """Replace timestamps with None or garbage values."""
    injected = 0
    sample = random.sample(range(len(events_list)), min(count, len(events_list)))
    for idx in sample:
        choice = random.choice(["null", "garbage"])
        if choice == "null":
            events_list[idx]["event_ts"] = None
        else:
            events_list[idx]["event_ts"] = "NOT_A_TIMESTAMP"
        injected += 1
    print(f"  [OK] Injected {injected} MISSING_TIMESTAMP anomalies")
    return events_list


def inject_mismatched_ids(events_list, count):
    """Add events with part_ids that don't exist in the parts registry."""
    injected = 0
    for i in range(count):
        fake_id = f"FAKE-{fake.bothify('??##??').upper()}-{9000 + i:04d}"
        station = random.choice(STATIONS)
        events_list.append({
            "part_id": fake_id,
            "station": station,
            "event_type": "mystery_event",
            "event_ts": fake.date_time_between(start_date="-7d", end_date="now").isoformat(),
        })
        injected += 1
    print(f"  [OK] Injected {injected} PART_ID_MISMATCH anomalies")
    return events_list


def inject_out_of_sequence(component_events, quality_events, packaging_events, count):
    """
    Make some downstream station timestamps earlier than upstream ones.
    e.g. quality_check timestamp < component_scan timestamp for same part.
    """
    injected = 0
    sample = random.sample(range(min(len(quality_events), len(component_events))),
                           min(count, len(quality_events)))
    for idx in sample:
        if quality_events[idx]["event_ts"] and component_events[idx]["event_ts"]:
            try:
                cs_ts = datetime.fromisoformat(str(component_events[idx]["event_ts"]))
                # Set quality_check timestamp BEFORE component_scan
                quality_events[idx]["event_ts"] = (cs_ts - timedelta(hours=random.randint(2, 8))).isoformat()
                injected += 1
            except (ValueError, TypeError):
                pass
    print(f"  [OK] Injected {injected} OUT_OF_SEQUENCE anomalies")
    return quality_events


def write_csv(filepath, events, extra_columns=None):
    """Write events to CSV."""
    if not events:
        return
    fieldnames = list(events[0].keys())
    if extra_columns:
        fieldnames.extend(extra_columns)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            # Convert None to empty string for CSV
            row = {k: ("" if v is None else v) for k, v in event.items()}
            writer.writerow(row)
    print(f"  -> Wrote {len(events)} rows to {os.path.basename(filepath)}")


def write_json(filepath, events):
    """Write events to JSON."""
    # Intentionally use slightly different key names to simulate messy feeds
    remapped = []
    for e in events:
        remapped.append({
            "partId": e["part_id"],          # camelCase instead of snake_case
            "stationName": e["station"],     # different column name
            "eventType": e["event_type"],
            "timestamp": e["event_ts"],      # 'timestamp' instead of 'event_ts'
        })
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(remapped, f, indent=2, default=str)
    print(f"  -> Wrote {len(remapped)} records to {os.path.basename(filepath)}")


def main():
    os.makedirs(RAW_DIR, exist_ok=True)

    print("=" * 60)
    print("FACTORY TRACEABILITY - Synthetic Data Generator")
    print("=" * 60)

    # --- Generate clean base data ---
    print("\n[1/6] Generating parts registry...")
    parts = generate_parts()
    print(f"  -> Created {len(parts)} parts across {len(PRODUCT_LINES)} product lines")

    print("\n[2/6] Generating station events...")
    cs_events, qc_events, pk_events = generate_station_events(parts)
    print(f"  -> component_scan: {len(cs_events)} events")
    print(f"  -> quality_check:  {len(qc_events)} events")
    print(f"  -> packaging:      {len(pk_events)} events")

    # --- Inject anomalies ---
    print("\n[3/6] Injecting DUPLICATE_SCAN anomalies...")
    cs_events = inject_duplicates(cs_events, NUM_DUPLICATES)

    print("\n[4/6] Injecting MISSING_TIMESTAMP anomalies...")
    pk_events = inject_missing_timestamps(pk_events, NUM_MISSING_TS)

    print("\n[5/6] Injecting OUT_OF_SEQUENCE anomalies...")
    qc_events = inject_out_of_sequence(cs_events, qc_events, pk_events, NUM_OUT_OF_SEQ)

    # Inject PART_ID_MISMATCH into quality_check feed
    print("\n[5.5/6] Injecting PART_ID_MISMATCH anomalies...")
    qc_events = inject_mismatched_ids(qc_events, NUM_MISMATCHES)

    # --- Write output files ---
    print("\n[6/6] Writing feed files...")

    # Parts registry (needed by ingest.py to populate `parts` table)
    write_csv(PARTS_REGISTRY, parts)

    # Station feeds — mix of CSV and JSON to test format handling
    write_csv(
        os.path.join(RAW_DIR, "component_scan_feed.csv"),
        cs_events
    )
    write_json(
        os.path.join(RAW_DIR, "quality_check_feed.json"),
        qc_events
    )
    write_csv(
        os.path.join(RAW_DIR, "packaging_feed.csv"),
        pk_events
    )

    # Summary
    total_events = len(cs_events) + len(qc_events) + len(pk_events)
    print("\n" + "=" * 60)
    print(f"DONE - {len(parts)} parts, {total_events} total events")
    print(f"Files written to: {os.path.abspath(RAW_DIR)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
