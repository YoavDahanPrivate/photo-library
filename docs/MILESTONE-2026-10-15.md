# Milestone: managed libraries and person-first People review

Date: **15 October 2026**. This consolidates work since the 8 October source
snapshot; the application remains ALPHA.

## People review additions in this checkpoint

This source checkpoint includes the People work after the earlier activation
correction below. Earlier sections retain their historical validation counts;
the final validation section records this checkpoint's complete checks.

- Full-window confidence review, paged cards, confidence switching, preserved
  selections and sticky desktop actions, with a responsive phone layout.
- Person-first review with a searchable, paged list ranked by confirmed faces,
  per-person pending counts, scoped confidence/group previews and explicit
  next/change-person navigation. Catalogue review remains available.
- Read-only similar-face groups with complete member inspection, cross-page
  deselection, exact selected approval and stale-preview checks. Grouping changes
  neither recognition confidence nor assignments.
- Selected Assign/Not-person controls in each confidence list, transactional
  bulk rejection, negative-example learning and one Undo per committed batch.
  Selections in the other list survive the operation. A rejection demotes the
  affected people's high flags until matching incorporates the feedback.
- Person renames preserve unrelated suggestions. Background matching retries
  changed snapshots twice while retaining stale-publication checks; actionable
  empty/error states expose reevaluation in both modes.
- Photo-disjoint calibration uses the full eligible fitting gallery, bounded
  tuning/validation queries, active-rule comparisons, retained validated rules
  and inspectable conflicts. Reports remain inactive until explicitly enabled.
- Known/Unknown portrait toggles, Name/Face count sorting, per-sort direction
  defaults and browser-persistent preferences. Filtered lazy loading reaches all
  results; invalid stored preferences fall back to usable defaults.
- `scripts/check.ps1 -BrowserChecks` now runs seven mocked browser workflows,
  including grouped, person-first, selected-action and portrait-directory tests.

## Recognition follow-up identified during review

Automatic approvals currently become trusted matching references alongside
explicit user confirmations. Scoring uses the closest reference, so a large
automatically extended gallery can reinforce earlier errors. A read-only audit
found a person's weak proposals depended predominantly on automatically
approved references; this identified a failure mode, not verified ground truth
for individual identities. The person-switching UI displayed the correct queue.

Separating human-verified references from automatic approvals, requiring
independent corroboration and reviewing reference provenance remain unimplemented.
This milestone does not retroactively relabel existing faces or change reference
trust. Calibration against saved labels cannot certify real-world identity
accuracy. See [Face matching](FACE_MATCHING.md#automatic-reference-feedback-known-limitation).

## Shipped behavior

- Database → Source → Album registration and management in Library tools, with
  aliases, three explicit layout interpretations, ambiguity flags, same-host
  native folder browsing and editable representative assignments.
- Fast directory-based initial previews, complete cancellable folder discovery,
  paging of all discovered Albums, recursive indexing and Album/Sub Album display.
- Independent visibility/sync, per-Database schedules, exclusions, overlap
  prevention, offline-root handling, verified reconnect and double-confirmed
  catalogue-only removal. Legacy migration retains identities/annotations.
- Advanced tree relayout: Source overrides, child Databases and cross-Database
  Linked Sources, with previewed atomic migrations and preserved ownership.
- Windows Credential Manager access for protected SMB roots, existing-session
  recovery and localhost-only credential entry.
- Missing/estimated dates and locations, reviewed bulk catalogue edits, provenance,
  undo, Unlocated/No GPS map collections and corresponding search terms.
- Incremental preview publication and live Library refresh during imports.
  Durable discovery snapshots, file hashes and work queues make clean Resume
  reuse completed folder listings; interrupted unfinished work is revalidated.
- Application/Python/derivative storage split from SQLite storage; JSON storage
  failures, health reporting, guarded existing databases and supervised startup.
- Immediate mobile launch UI and iOS launch images; download/share choices,
  safe HTTP standalone/Safari handoff and native sharing on trusted HTTPS.
- One-request, transactional Approve all with scoped undo and stale-match checks.
  Review pages render 48 matches, avoiding thousands of simultaneous face cards.
- Lower-priority, separate reevaluation workers with durable progress, measured
  phase counts, elapsed time, reconnect/reload behavior and Stop controls.
- User-started **Auto approve high-confidence**: approve → reevaluate with newly
  confirmed references → repeat until no eligible high-confidence matches remain
  or Stop. Live rounds/committed totals, per-batch undo, transactional high-status
  rechecks and preserved committed work on Stop/failure.
- Stop scan now interrupts long matching passes between scoring blocks, with
  stage units and safe-checkpoint feedback.

## Earlier validation: initial checkpoint

- **389 backend tests passed** on isolated temporary catalogues/disposable files.
- TypeScript and Vite production build passed using `--configLoader runner`.
- Mocked Edge checks covered 5,000-match paging/one-request approval, responsive
  elapsed/progress UI, loop rounds, queue refreshes, Stop across tabs and reloads,
  terminal results, mobile fit and connection recovery.
- A real isolated worker proved that first-round confirmations can enable a
  later high-confidence round, then terminate while retaining lower-confidence
  matches. Tests cover rollback before commit, Stop after commit, partial-round
  batches, stale/downgraded matches, hidden/rejected faces, storage errors and undo.
- Targeted tests cover migration/removal/reconnect preservation, unavailable
  storage and clean-pause/crash recovery without touching the family library.
- An isolated 5,000-face approval measurement completed in roughly 0.15–0.20 s
  with one transaction and no embedding reads. This is fixture evidence, not
  a production timing promise on unstable or busy storage.
- Refreshed PowerShell launchers passed syntax/settings checks and an actual
  start/stop smoke test on an empty temporary library; measurement respected
  separate runtime/database folders without assuming a fixed media count.
- Production feature deployment was verified by health, frontend manifest,
  endpoint schema and source hashes. This documentation/source checkpoint does
  not automatically start approval, scans or schedules.

## Same-day installation follow-up

The portability audit found remaining household drive defaults, preset phone
Sources, trusted PC hostnames and regional schedule defaults. These have been
removed from runtime defaults. A fresh installation starts with zero Databases,
Sources and media; legacy upgrades use an explicit original root and infer Source
names from existing records. This does not rewrite registered identities or
annotations in an already migrated installation.

`scripts/install.ps1` provisions dependencies/frontend, public face/map resources
and an empty database pair. It saves paths in ignored `dahan-config.json`.
Launchers read local configuration/environment/overrides instead of personal
drive paths. Public reference-index installation does not open the media catalogue.
Setup refuses incomplete existing storage, and production retains its missing
database guard. README and Operations now document independent installation.

Validation: **395 backend tests**, the production frontend build and both mocked
browser checks passed. Six new isolated checks cover empty onboarding, original
folder registration and real thumbnail indexing, persistent IDs/annotations after
restart, legacy Source inference, incomplete-storage protection, actual Windows
installer/launcher startup using only its saved local settings, and public map
installation/failure handling. Dependency-download and separate-physical-PC
acceptance remain release checks; the launcher fixture reuses installed
dependencies and serves a minimal fixture page. The current household server
was left running without deploying or restarting for this source follow-up.

## Reproduction

Follow [README setup](../README.md), then run `scripts/check.ps1`. Add
`-BrowserChecks -PlaywrightModule <module-directory>` for the mocked UI checks.
The harnesses serve the built frontend locally, intercept API responses and
write screenshots only into temporary/explicit QA output folders.

## Remaining work and practical limits

- Accounts/permissions, trusted HTTPS provisioning and a Windows-service/reboot
  installation workflow remain unimplemented.
- Recognition uses existing SFace embeddings and trusted references; it does not
  fine-tune neural-network weights. Similarity confidence is not a calibrated
  accuracy percentage. The approval loop explicitly treats its confirmations
  as trusted, following the user's chosen manual-equivalent workflow. This can
  amplify mistaken labels; human/automatic reference separation remains pending.
- New photos, changing references and network/drive speed make an overall ETA
  unreliable. Progress percentages refer to the current phase.
- Physical iPhone native-share/system-preview testing and clean-machine install
  certification remain distinct from desktop emulation.
- Video recognition samples frames; brief appearances can be missed. Compatible
  preview clips are limited; full-length playback depends on original codecs.
- Semantic/object/animal/occasion search and Live Photo pairing remain future work.
- Fixture-tested backup/checkpoint behavior does not replace a tested recovery
  drill or reliable hardware. Runtime/originals/credentials are outside Git.

## Matching quality follow-up

Added a background photo-disjoint calibration report, explicit per-person profile
enable/reset, conservative fallback after relabelled examples, selected-batch
review, person/date filters, confidence evidence and optional background refresh.
Unchanged face comparisons are cached with reference/candidate invalidation;
corrupt or partial caches fall back to recomputation. SFace remains active.

Validation: the 403-test full regression suite, nine focused matching/cache
checks after final hardening, frontend build and all three mocked browser checks
passed. A read-only live browser check verified the report and mobile layout,
with API writes blocked. Source/runtime catalogue migrations add only new tables.
The deployed server was restarted only after confirming scans/face jobs were
idle and backing up/checking both SQLite databases. Post-deployment fingerprints
verified faces/embeddings, people, approvals/rejections, history and registered
roots were unchanged. The generated report is inactive until explicitly enabled.

An isolated reference study and the deployed analysis agreed on 26 eligible
people and 153 additional correct held-back matches. There were no observed
wrong matches among accepted adjustments in that study, not a guarantee of
accuracy on unseen photographs. Reports are against saved labels and can
include prior automatic confirmations. Model candidates and remaining crop/model
work are documented in [Face matching](FACE_MATCHING.md).

## Matching activation correction

The subsequent user report of unchanged match yield exposed an activation and
visibility gap: the report was available but calibrated rules were still off.
The latest auto run had consumed five conservative high matches. A read-only
audit compared 256 current candidate faces across all 70 people (17,920
candidate/person comparisons) against fresh calculations and found no cache
discrepancies. The saved report projected 5,877 high suggestions in the current
queue; this was not an accuracy guarantee.

Refreshed and applied the calibration under the approved matching plan, then
ran reevaluation without automatic approval. The resulting queue contained
5,877 high and 4,595 lower suggestions; assignment count was zero and the latest
approval/action records were unchanged. Effective per-person calibration remained
enabled for 26 people. Added persistent effective-mode reporting, stale-report
feedback, automatic reevaluation on enable/reset, and cross-browser completion
refresh. The correction passed 30 focused backend tests and all three browser
workflows. A live browser check used API-write blocking to verify displayed
mode/counts and mobile layout. The service restart was for a read endpoint and
static UI only, with rollback copies and no schema migration.


## Final checkpoint validation

The complete source check passed on 15 October 2026:

- **440 backend tests** against isolated temporary catalogues and disposable
  originals, including migrations, preservation, recovery and worker behavior.
- TypeScript checking and the Vite production build.
- **Seven mocked Edge browser workflows**: operation progress, automatic-review
  rounds, matching-quality controls, grouped review, person-first review,
  selected assignment/rejection, and People portrait filtering/sorting.
- Staged whitespace checks and a source inventory check. No databases, originals,
  embeddings, models, generated assets, credentials, local configuration or
  household-path additions are part of this Git checkpoint.

The two existing Starlette/httpx deprecation warnings and Vite's large-chunk
advisory remain non-failing diagnostics. Fixture success does not certify face
identity accuracy, physical-drive reliability or native iPhone system dialogs.
Earlier live read-only checks verified desktop/mobile review behavior, portrait
sort/filter persistence, endpoint availability and service health with API writes
blocked. This Git checkpoint does not restart the deployed server, run scans,
approve faces or apply calibration reports.
