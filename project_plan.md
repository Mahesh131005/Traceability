# Factory Traceability Pipeline — Project Plan

> **Purpose**: This document demonstrates TPM-style program planning — scoping, sequencing, dependency management, and escalation thinking — applied to a technical POC.

---

## Milestones

| Milestone | Description | Depends On | Est. Effort | Exit Criteria |
|-----------|-------------|------------|-------------|---------------|
| **M0** | Scaffold repo, Docker infra, schema | — | 2–3 hrs | `docker-compose up` runs clean; Postgres accepts connections; schema created |
| **M1** | Synthetic data generator | M0 | 2–3 hrs | `generate_feeds.py` produces 3 feed files with injected anomalies in `data/raw/` |
| **M2** | Ingestion pipeline | M0, M1 | 2–3 hrs | All feed data loaded into `part_events`; no validation, just canonical load |
| **M3** | Validation pipeline | M2 | 3–4 hrs | All 4 flag types detected and written to `data_quality_flags`; manual spot-check passes |
| **M4** | Grafana dashboard | M0, M3 | 2–3 hrs | 3 core panels render with real data; dashboard auto-provisions on `docker-compose up` |

### Milestone Dependency Graph

```
M0 (Infra)
├──> M1 (Generator)
│    └──> M2 (Ingestion)
│         └──> M3 (Validation)
│              └──> M4 (Dashboard)
└──> M4 (Dashboard — Postgres connection)
```

### Critical Path

**M0 → M1 → M2 → M3 → M4**

M4 (Dashboard) has two dependencies:
1. M0 — needs Postgres running to query
2. M3 — needs flags in the database to visualize

The dashboard can be scaffolded in parallel with M2/M3 (mock queries), but final validation requires M3 to be complete.

---

## Dependencies & Risks

| Dependency | Risk | Mitigation |
|-----------|------|------------|
| M3 depends on M2's schema being stable | If `part_events` schema changes after M2, M3 queries break | Freeze schema at M0; M2 is a dumb loader that conforms to it |
| M4 depends on M3's flag logic being finalized | Dashboard queries reference `flag_type` enum values | Define enum values upfront in spec; dashboard queries are parameterized |
| Docker Compose networking | Grafana must reach Postgres by container name | Use `depends_on` with health check; datasource uses `postgres:5432` |
| Python package versions | Breaking changes in pandas, psycopg2 | Pin versions in `requirements.txt` |

---

## Escalation Criteria

In a real factory environment, the following situations would be **escalated** to engineering/manufacturing leads rather than silently patched:

1. **Upstream feed format changes** — If a station feed suddenly starts sending data in a different format (new columns, different delimiters, changed encoding), this breaks the ingestion contract. The correct response is to flag it, not to silently adapt, because format changes may signal an upstream system update that affects other consumers too.

2. **Anomaly rate exceeds threshold** — If more than 15% of parts in a batch have data quality flags, this likely indicates a systemic issue (station misconfiguration, clock drift, network drops) rather than isolated bad data. This should be escalated to the station engineering team.

3. **Schema migration required** — Any change to the `part_events` or `data_quality_flags` schema after M2 is complete should be treated as a change request, not a bug fix, since it impacts both the ingestion and validation pipelines.

4. **New station type introduced** — Adding a 4th station to the traceability flow changes the definition of "complete traceability" (currently 3/3 stations). This is a scope change that requires updating the generator, validation rules, and dashboard queries.

---

## Build Sequence (Actual)

| Day | Focus | Output |
|-----|-------|--------|
| Day 1 | M0 + M1 | Docker infra running; synthetic data generated |
| Day 2 | M2 + M3 | Ingestion + validation pipelines; flags verified |
| Day 3 | M4 + docs | Dashboard live; README + project_plan polished |

---

## Out of Scope (Intentional)

These were explicitly excluded to keep the POC focused:

- **Orchestration** (Airflow, Prefect) — overkill for 3 scripts
- **Message queues** (Kafka, RabbitMQ) — no real-time streaming needed
- **CI/CD pipeline** — manual runs are fine for a POC
- **Authentication/RBAC** — Grafana defaults are sufficient
- **Production error handling** — scripts fail fast with clear messages; no retry logic
