# Factory Traceability Pipeline

> **POC**: End-to-end factory traceability pipeline simulating Apple MDS (Manufacturing Design Systems) data flows — ingests messy multi-source station data, validates for data-integrity issues, and visualizes traceability metrics in Grafana.

---

## Architecture

```
[Component Scan Feed]   [Quality Check Feed]   [Packaging Feed]
   (CSV)                    (JSON)                 (CSV)
        \                     |                     /
         \________   Ingestion & ETL  _____________/
                  (normalize, validate, flag)
                           |
                           v
                      PostgreSQL
               (parts + part_events + data_quality_flags)
                           |
                           v
                    Grafana Dashboard
          (traceability % · anomaly counts · timeline)
```

## Tech Stack

| Layer | Tool |
|-------|------|
| Language | Python 3.11 (pandas, Faker, psycopg2) |
| Database | PostgreSQL 15 |
| Dashboard | Grafana (latest) |
| Infra | Docker Compose |

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Python 3.11+
- pip

### 1. Clone & Setup

```bash
git clone <repo-url>
cd factory-traceability-pipeline
pip install -r requirements.txt
```

### 2. Start Infrastructure

```bash
docker-compose up -d
```

This spins up:
- **PostgreSQL** on `localhost:5433` (auto-runs schema.sql)
- **Grafana** on `localhost:3000` (auto-provisions Postgres datasource + dashboard)

Wait ~10 seconds for Postgres to be fully healthy.

### 3. Generate Synthetic Data

```bash
python generator/generate_feeds.py
```

Generates ~80 parts across 3 station feeds with deliberately injected data quality issues:
- Duplicate scans
- Missing timestamps
- Part ID mismatches
- Out-of-sequence events

### 4. Run Ingestion Pipeline

```bash
python etl/ingest.py
```

Loads all raw feed files (CSV + JSON) into PostgreSQL, normalizing them into a canonical schema.

### 5. Run Validation Pipeline

```bash
python etl/validate.py
```

Applies 4 validation rules and writes flags to `data_quality_flags`:

| Flag Type | What It Catches |
|-----------|----------------|
| `DUPLICATE_SCAN` | Same part_id + station appears more than once |
| `MISSING_TIMESTAMP` | Null or unparseable event_ts |
| `PART_ID_MISMATCH` | Part ID not found in parts registry |
| `OUT_OF_SEQUENCE` | Downstream station timestamp before upstream |

### 6. View Dashboard

Open [http://localhost:3000](http://localhost:3000) in your browser.

- **Login**: admin / admin123
- **Navigate**: Dashboards → Factory Traceability Dashboard

### Dashboard Panels

1. **Traceability Completeness %** — gauge showing parts with all 3 station events / total
2. **Anomaly Count by Flag Type** — horizontal bar chart
3. **Total Events / Parts / Flags** — stat panels
4. **Events by Station** — vertical bar chart
5. **Part Timeline Table** — full event history with flags (filterable)
6. **Parts by Product Line** — donut chart
7. **Most Flagged Parts** — sorted table of problem parts

## Project Structure

```
factory-traceability-pipeline/
├── docker-compose.yml              # Postgres + Grafana
├── requirements.txt                # Python dependencies
├── sql/
│   └── schema.sql                  # Database schema (auto-runs on startup)
├── generator/
│   └── generate_feeds.py           # Synthetic data with injected anomalies
├── etl/
│   ├── ingest.py                   # Raw feeds → part_events (no validation)
│   └── validate.py                 # part_events → data_quality_flags
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── postgres.yml        # Auto-provision Postgres datasource
│   │   └── dashboards/
│   │       └── dashboard.yml       # Auto-provision dashboard
│   └── dashboards/
│       └── factory_traceability.json  # Dashboard JSON model
├── data/
│   └── raw/                        # Generated feed files (gitignored)
├── project_plan.md                 # TPM-style milestones & dependencies
└── README.md                       # This file
```

## Database Schema

```sql
parts (part_id PK, product_line, created_at)
  └── part_events (event_id PK, part_id FK, station, event_type, event_ts, source_file)
       └── data_quality_flags (flag_id PK, event_id FK, flag_type, detected_at, description)
```

## Teardown

```bash
docker-compose down -v   # Removes containers + volumes
```

## Resume Bullet

> Built an end-to-end factory traceability pipeline ingesting data from 3 simulated station feeds; designed integrity checks catching duplicate/missing/out-of-sequence events, and a Grafana dashboard surfacing traceability-completeness metrics — planned and sequenced the build across ingestion, validation, and visualization milestones.

---

*Built as a portfolio POC for Apple TPM Intern – MDS (Manufacturing Design Systems)*
