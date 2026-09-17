-- ============================================================
-- Factory Traceability Pipeline — Database Schema
-- ============================================================
-- This schema supports a three-station factory traceability
-- flow: component_scan → quality_check → packaging.
-- It stores raw part events and flags data-quality issues.
-- ============================================================

-- Drop existing tables for idempotent re-runs
DROP TABLE IF EXISTS data_quality_flags CASCADE;
DROP TABLE IF EXISTS part_events CASCADE;
DROP TABLE IF EXISTS parts CASCADE;

-- -----------------------------------------------------------
-- Parts registry
-- -----------------------------------------------------------
CREATE TABLE parts (
    part_id      TEXT PRIMARY KEY,
    product_line TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT now()
);

-- -----------------------------------------------------------
-- Canonical event log (one row per station scan)
-- -----------------------------------------------------------
CREATE TABLE part_events (
    event_id    SERIAL PRIMARY KEY,
    part_id     TEXT,                  -- intentionally no FK; mismatches caught by validate.py
    station     TEXT NOT NULL,          -- 'component_scan' | 'quality_check' | 'packaging'
    event_type  TEXT NOT NULL,
    event_ts    TIMESTAMP,
    source_file TEXT
);

-- Index for common queries
CREATE INDEX idx_part_events_part_id ON part_events(part_id);
CREATE INDEX idx_part_events_station ON part_events(station);

-- -----------------------------------------------------------
-- Data quality flags raised by the validation layer
-- -----------------------------------------------------------
CREATE TABLE data_quality_flags (
    flag_id     SERIAL PRIMARY KEY,
    event_id    INT REFERENCES part_events(event_id),
    flag_type   TEXT NOT NULL,          -- DUPLICATE_SCAN | MISSING_TIMESTAMP | PART_ID_MISMATCH | OUT_OF_SEQUENCE
    detected_at TIMESTAMP DEFAULT now(),
    description TEXT
);

CREATE INDEX idx_dqf_flag_type ON data_quality_flags(flag_type);
CREATE INDEX idx_dqf_event_id ON data_quality_flags(event_id);
