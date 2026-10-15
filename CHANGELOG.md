# Changelog

## 2026-10-15 — People review milestone source checkpoint

Consolidated person-first/grouped review, scoped selected assignment/rejection,
rejection feedback, spacious confidence lists, suggestion recovery and persistent
portrait filters/sorting. Updated README, user/operations/matching guides and the
[milestone summary](docs/MILESTONE-2026-10-15.md). Automatic-reference feedback is
an explicitly documented unresolved limitation. Full validation: 440 isolated
backend tests, the TypeScript/Vite production build and seven browser workflows.
Runtime data and machine-local installation state stay outside Git.

## 2026-10-15 — People portrait filters and persistent sorting

Added independent Known/Unknown toggles above the People portraits, including
correct handling of unnamed and special unassigned buckets. Added Name sorting
(default A–Z), face-count sorting (default largest first) and remembered directions
for each. Browser preferences survive visits, invalid storage falls back safely,
and filtered lazy loading reaches every result. Review controls and recognition
are unchanged. Added a browser workflow for filters, stable ordering, persistence,
empty states, selection clearing, scrolling and mobile layout.

## 2026-10-15 — Selected face assignment and rejection

Each confidence panel now places selected-only Assign and Not-person actions
beside Approve all and Select this page. Actions are disabled without a selection
and scoped to that confidence list, including selections on other pages. Added
an atomic, validated bulk rejection endpoint with one Undo action and existing
negative-example learning. Assignment preserves selections in the other list.

## 2026-10-15 — Recover and preserve face suggestions

Person renames no longer clear the entire review queue. Newly named references
keep unrelated suggestions for manual review and invalidate old high flags.
Background matching retries changed snapshots twice while preserving the stale
publish guard. Both review modes expose reevaluation, with actionable empty/error
states and a retry action that never starts automatic approval.

## 2026-10-15 — Person-first face review

Added a second review mode with a searchable, paged people chooser ranked by
confirmed faces across visible databases. It shows separate pending counts,
scopes individual/grouped review and exact approvals to the selected person,
provides explicit next/change-person navigation and retains the full gallery
space. Completion stays on the current person. Catalogue review remains available;
changing people clears selections. Recognition rules and backend are unchanged.
Validated with the frontend build and five browser workflows, including exact
person-scoped batches, ranked paging, completion and mobile layouts.

## 2026-10-15 — Grouped review and full-gallery calibration trial

Added cohesive, paged similar-face previews with complete member inspection,
cross-page deselection, exact reversible batch approval and stale-preview guards.
Grouping does not change confidence. Calibration now uses every eligible fitting
photo, up to 80 tuning/validation photos per person, comparison against enabled
rules, retained validated adjustments and inspectable conflicting examples.
Drafts stay inactive until explicitly enabled. The three-photo consensus
experiment did not justify changing live recognition rules. Validated with 424 backend fixture tests, the frontend build and four browser workflows. The live group preview was checked without API writes.

## 2026-10-15 — Learn from rejected lookalikes

Saved rejections now refine person-specific separation on reevaluation: close
negative neighbours are withheld, borderline matches stay in lower confidence,
and confirmed positive neighbourhoods are protected. Exact rejections, undo,
corrected identities and group hints are respected. New feedback immediately
invalidates that person's stale high flags before automatic approvals. Progress
and cards explain the effect; encoder weights and prior assignments stay intact.
Validated with 414 backend fixture tests, the frontend build and all three
browser workflows, including rejection learning, undo and stale-approval guards.


## 2026-10-15 — Spacious face review

Removed the fixed-height confidence grid scroll boxes. Added a full-window
review workspace with confidence switching, preserved filters/selections/pages,
sticky desktop approval controls and a responsive phone layout. Back to People
or Escape restores the ordinary split view. Matching and approval rules are
unchanged.

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
