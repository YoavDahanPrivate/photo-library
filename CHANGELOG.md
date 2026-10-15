# Changelog

## 2026-10-15 — Make calibrated matching activation explicit

People now always shows the effective matching rules, flags stale reports and
explains conservative fallback. Enabling/resetting rules automatically starts
reevaluation. Completed jobs started elsewhere refresh the queue even when the
browser misses their running state between polls. Validated with 30 focused
backend tests and all three browser workflows.

## 2026-10-15 — Matching quality and review batches

Added a stoppable, photo-disjoint calibration study with explicit profile
preview/enable/reset, per-person validation and conservative fallback. Matching
reuses unchanged comparisons and exposes missing evidence. People now supports
person filters, date variety, exact selected-batch approval and optional
debounced background reevaluation after reviews. SFace remains active; model
comparison and higher-resolution extraction are documented follow-up work.

Validated with 403 backend tests, the frontend build and three mocked browser
workflows. See [Face matching](docs/FACE_MATCHING.md).

## 2026-10-15 — Independent first-time installation

Removed household drive paths, preset phone Sources, trusted PC hostnames and
regional schedule defaults from runtime code. Fresh installs start empty;
legacy Source names are inferred from records when an explicit upgrade root
is provided. Added a Windows install script, local ignored configuration,
public model/map setup, and fixture checks for onboarding, thumbnail indexing,
restart persistence, legacy annotations and incomplete-storage protection.

## 2026-10-15 — Managed libraries and People automation

Configurable Databases/Sources/Albums, smart editable previews, advanced subtree
relayout and Linked Sources; protected NAS access; missing date/location tools;
incremental/resumable scans; persistent application storage and recovery; mobile
launch/save/share improvements; transactional bulk face approval, bounded review
pages, background progress and the stoppable high-confidence approval loop.

Includes refreshed operating/user guides, configurable Windows launch/indexing
helpers, a supervised production entry point and reproducible browser checks.
Validated with 389 backend tests, the production build and isolated UI checks.
See the [milestone report](docs/MILESTONE-2026-10-15.md) for details and limits.

## 2026-10-08 — Initial ALPHA source checkpoint

Self-hosted Library, People, maps/search, sync, duplicate review and desktop/mobile
viewer, followed by remembered source selections and an all-sources toggle.
