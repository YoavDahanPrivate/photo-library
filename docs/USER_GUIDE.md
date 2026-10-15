# Dahan user guide

A new installation starts empty. Add your own original folders through Library tools.
Installation paths and optional hostnames are local configuration, independent of the developer's computer.

## Register and manage Databases

Open **Library tools → Databases, Sources & Albums → + Add Database**. Enter an
absolute server path, or use Browse when visiting the server directly through
localhost. Browse is a real Windows folder dialog; the backend checks loopback,
Host and Origin, so LAN/proxied clients enter a server path instead.

The folder name becomes the default Database alias. The backend analyzes the
predominant tree pattern, suggests an interpretation and flags ambiguity. Both
the alias and interpretation remain editable. Use folder name / Use detected
layout restores automatic defaults. Database and Source aliases are independent
in every layout:

| Interpretation | Meaning |
| --- | --- |
| Database → Sources → Albums → media | Immediate Source folders, followed by Album paths. |
| Database also acts as Source → Albums → media | One Source for the Database; subfolders supply Albums. |
| Database also acts as Source and Album → media | One Source and Album; include media recursively under the whole root. |

Ordinary `Photos/<folders>/media` suggests Database Photos and one Photos
Collection Source. Root-level media uses Main folder. Phone-backup patterns can
suggest separate Sources. Nested Album names retain their relative hierarchy,
flattened with ` › ` where needed. Details and previews also separate Album from
Sub Album: `Holiday/A/B/C/photo.jpg` shows Album Holiday and Sub Album `A/B/C`.

**Preview assignments** shows representative filenames before indexing. Initial
analysis samples directory entries, not file contents or EXIF. An incomplete
preview is labelled and can start complete folder discovery, with progress and
cancellation. The complete pass has no folder/depth cap, includes empty/container
folders, and stops stalled listing helpers. First/previous/next/last controls
expose all discovered Albums, ten per page, with up to three sample files each.
Sampling/discovery is separate from indexing. Sync recursively processes
supported media, including descendants not represented by a sampled filename.

Confirmation validates the bounded preview; complete media/content checks happen
during sync. Invalid/inaccessible roots, traversed links and overlapping roots
are rejected. Registration itself does not start a scan.

The Database table supports aliases, expandable Sources/Albums, independent
visibility and sync controls, exclusions, schedules, Sync now, Pause/Resume and
More actions. Exclusions affect future scans; existing catalogue records remain.
Hiding leaves records intact. Removing a Database requires two confirmations and
typing its alias. Removal deletes its catalogue records/annotations, preserves
originals and derivatives, and prunes affected queues/history. Parent removal is
blocked while child Databases exist.

## Protected folders and moved roots

Use a UNC path such as `\\server\share\Photos` for a protected NAS share.
Network access offers Test folder access, Remember, Use current Windows access
and Forget. Enter credentials through localhost on the backend PC. Passwords are
not stored in the catalogue, browser, environment or command line; remembered
access uses that Windows account's Credential Manager, scoped to the database
directory and SMB server. Other shares on the same server can reuse it.

When Windows already has a session under another account, Dahan tests that
existing session and continues if it can read the folder. It does not save an
unverified new password or disconnect another application's session. If access
is still denied, resolve the server account/session in Windows before retrying.
Forget deletes Dahan's saved credential, not existing Windows sessions.

Use **Reconnect moved root** rather than deleting and re-adding a moved library.
The reviewed migration verifies content, updates paths and preserves identities,
faces and annotations. Offline originals without saved hashes cannot be matched
safely. Disconnected roots are not treated as wholesale deletions.

## Advanced relayout and Linked Sources

**Database → More → Advanced relayout** opens the tree wizard. It initially uses
saved catalogue folders, then discovers accessible directories asynchronously.
Select a subtree to override its Source interpretation or make it a child
Database with its own template and aliases. Multiple staged changes can be
reviewed together before one atomic catalogue migration. The most specific rule
applies, and a child Database owns its entire subtree; parent scans exclude it.

For example, keep A–F as Albums under Photos' original Source while making
MobileBackup a child Database whose Alice/Bob/Charlie folders become Sources. No
original files are moved. Child schedules initially remain off. Hidden/paused
controls and future-Source policies are preserved; incompatible merges need an
explicit resolution. Applying migrations waits for active scans to stop and
rejects stale previews.

The Linked Sources tab groups existing physical Sources under a logical name,
including Sources in different Databases. Member identities/sync settings stay
separate; visibility applies, and equal Album names do not merge. The Library
Source filter offers these views. Database filtering includes child Databases
only when Include child Databases is selected. Removing a link keeps its members.

## Sync, Pause, Stop and Resume

Sync now starts a fresh snapshot. Preview batches make newly indexed media
visible while scanning continues; recognition follows preview publishing. The
Library refreshes loaded results when the catalogue revision changes, preserving
filters, loaded pages, scroll and selection. Old imports follow the current
date sort; use View importing Database to narrow the results.

Library tools shows phases, current folder/file, stage counts, last progress,
and Pause / **Stop scan** controls. Face matching reports reference/comparison
counts and checks Stop between scoring blocks. A current file/network operation
may need to finish before its safe checkpoint. Stop preserves progress for
Resume; it does not undo completed indexing or annotations.

Pause saves folder listings, remaining folders, mapped batches, file hashes and
processing queues in `sync.sqlite`. Clean Resume reuses completed directory
listings instead of walking them again. After a crash, only unfinished/uncommitted
work needs revalidation; media batches contain at most 50 files. Files added to
an already-read folder are discovered by the next **new** Sync now. Changes to
roots, layouts or scope invalidate incompatible inventory snapshots. Older scans
may need one initial walk to obtain the new checkpoints.

Missing-file reconciliation follows a complete, available inventory. A later
drive failure preserves already published previews and annotations. Schedules
wait while the latest run is paused/stopped; a server restart recovers interrupted
states but does not automatically resume a scan. Phase percentages are not a
whole-scan ETA.

## People review and automatic approval

High- and lower-confidence suggestions are paged in groups of 48, with the total
visible. Individual approval, rejection and **Approve all N** remain available.
Approve all includes the entire confidence group, not just its current page.
It sends one request, commits a single transaction and creates one undo batch;
changed/unavailable suggestions prevent that batch from being applied.

**Reevaluate unassigned faces** compares saved embeddings with trusted examples
in a separate worker. This does not retrain the YuNet/SFace model or reopen all
originals. The progress panel shows phases, real comparison counts, elapsed time,
and **Stop reevaluation**. Reading/saving can use an activity indicator while a
total is unknown. The worker continues across a page refresh, and its progress
files live separately from the catalogue database.

Beside the high-confidence Approve all button, **Auto approve high-confidence**
starts this user-controlled loop:

1. Approve the current eligible high-confidence matches using the same assignment
   and undo rules as manual Approve all.
2. Reevaluate using those newly confirmed references.
3. Repeat until no eligible high-confidence matches remain or Stop is requested.

Lower-confidence matches remain for manual review. Hidden/unavailable, rejected,
dismissed or changed assignments are not silently approved. Every batch rechecks
that its suggestions are still high-confidence inside the transaction. Large
rounds use bounded batches. A concurrent correction stops stale matching rather
than overwriting it.

The panel shows the round, committed approval total, completed approval rounds,
current phase and **Stop automatic approval**. Queue updates appear between
rounds; refresh and other tabs retain status. Stop before commit rolls back that
batch. Stop after commit keeps saved approvals and prevents the next pass. Use
Undo last change to undo saved batches individually. A storage failure stops
the operation and retains committed work. This is a user-started operation, not
an always-on setting. Recognition similarity scores are not accuracy percentages.

## Missing dates and locations

Select media, or scope all matching results, then choose Edit dates & locations.
Fill missing values is the default. Correct existing values needs a reviewed
preview and confirmation. Embedded metadata is retained, originals are not
rewritten, and restore/undo refuses to overwrite newer catalogue edits.

Capture dates can be a year, month, day, range or estimated value; search uses
overlapping ranges without inventing an exact day. File creation/modification
and first-index dates are separate. Old records may lack earlier timestamps.
Sort by File date explicitly instead of treating file dates as capture dates.

Map includes **Unlocated** and **No GPS coordinates**. A named place can be
searchable without a fabricated pin; a manually supplied coordinate appears on
the map with its provenance. These collections and map regions can be combined
with OR. Search supports `Location("unknown")`, `Location("no_gps")` and
`Location("no_date")`. Identical rescans, moves and layout changes preserve edits;
a genuinely replaced file is a new version, not a recipient of old annotations.

## Mobile download and sharing

Startup shows an immediate loading shell and retry state, with iOS launch images.
In the viewer, Download and Share offer Original or Largest preview (JPEG, up to
1,600 pixels). A video's JPEG is a still, not an exported video.

On HTTP in an iPhone Home Screen app, an in-app image supports touch-and-hold
saving. Exact originals/videos use a copyable link opened separately in Safari;
the Dahan viewer stays open. The standalone app avoids attachment/iframe flows
that can strand users in an iOS system preview. This HTTP fallback includes a
manual Safari handoff.

Trusted HTTPS enables compatible native file-sharing destinations. File
preparation is bounded to 128 MiB, followed by a separate Share tap; larger
originals can stream as downloads. Cancel/error preserves the viewer. Certificate
trust/HTTPS setup and physical iPhone system-UI validation are not automated.

## Search, maps and duplicates

Unified search combines people, devices, Albums, dates, media types and geographic
regions. Examples include `Includes("Alex") and Place("Italy")`,
`Phone("My iPhone") and after 2025`, and `Location("no_gps")`. Use saved catalogue
names. Boolean AND/OR/NOT and date comparisons/ranges are supported. Face filters
describe detected faces, not a guarantee about everyone in a frame.

Country boundaries and nearby settlement labels are approximate offline data.
Map references and installation commands are in [Operations](OPERATIONS.md).

Indexing/layout/metadata edits do not rewrite originals. Duplicate cleanup is a
separate reviewed action that **moves selected originals** into recoverable
`.dtrash/dahan-duplicates` folders; restore refuses conflicting paths. Trash does
not free disk space. Display-only HEIC/JPEG hiding leaves both copies stored.

## Improve face matching and review in batches

In People, open **Improve matching with saved examples → Analyze matching
quality**. The background study produces per-person held-back validation results
without changing assignments. The always-visible matching-mode banner shows
which rules are effective. Review the results before enabling adjusted rules;
enabling automatically reevaluates suggestions. The automatic approval loop uses the enabled rules when started.
Conservative rules remain available with one button. See the [matching guide](FACE_MATCHING.md)
for the study's limits and model candidates.

Filter suggestions by person, choose strongest-first or spread-across-dates
ordering, select individual matches or the current page, and approve that exact
selection as one reversible batch. Cards explain missing confidence evidence.
Optional refresh after reviewing starts in the background after eight idle
seconds. Unchanged comparisons are reused, and new corrections/rejections are
always respected. Original photographs are not rescanned by reevaluation.

Use **Expand review** on either confidence panel for a full-window review
workspace. Switch between High-confidence and Lower-confidence at the top;
filters, selected matches and each panel's current page are preserved. Open
**Review options** for filters, ordering and background refresh settings. **Back to
People** or Escape returns to the split view. Both views let matches scroll with
the page, rather than inside a fixed-height box. In expanded desktop review,
approval actions and page navigation remain accessible while scrolling.

**Not <Person Name>** now teaches the matcher rejected lookalikes as well as
blocking that exact face/person pair. Reevaluate (or leave background refresh
enabled) to apply the feedback to similar faces. Confident negative matches are
withheld; borderline ones stay in Lower-confidence with an explanation.
Existing assignments remain saved. Undo or an explicit correction can reverse
the feedback. Closely conflicting confirmed/rejected examples stay face-specific
instead of blocking a whole person's appearance. See [Face matching](FACE_MATCHING.md).


## Review similar faces together

In People, choose **Try grouped review**. The suggested-person filter also
filters groups. **Tighter similarity** offers more cohesive sets; **Broader
similarity** can combine more faces and needs closer inspection. Grouping does
not change confidence or assign faces. The summary reports grouped faces and
those still needing individual review; every face stays available in the
ordinary confidence panels.

Choose **Review all N faces** to open the set. All members are initially
selected, including members on other pages. Inspect the pages, deselect any
exceptions, then choose **Approve selected N**. This sends the exact selection
as one batch, with the existing Undo behavior. A changed library invalidates an
open preview; reopen a fresh group before retrying. Each set contains at most
64 faces. Groups are formed within bounded 512-face blocks; this is a review
aid, not exhaustive identity clustering or automatic approval.

**Analyze matching quality** now uses all eligible reference photos, with up to
80 independent photos each for tuning and validation. The report compares the
trial against enabled rules, shows conflicting examples, and can retain
existing validated adjustments. Analysis creates a draft and does not enable
it or assign faces. Review the report before choosing **Enable reviewed matching
rules**. An open-set conflict means the saved identity was deliberately omitted
from the gallery for that test; it is not proof the saved label is wrong.


## Review suggestions one person at a time

In **People → Review by person**, choose from a searchable, paged list ranked by
confirmed face count across all visible databases and Sources. Pending suggestions
are counted separately; the default filter shows people who have suggestions.
Turn off **Only people with suggestions** to include everyone with a name.

Choosing a person shows their current high- and lower-confidence suggestions,
with the same selection, approval, rejection, paging and expanded review controls.
**View photo / video** opens the media for context. **Try grouped review** is also
scoped to this person. Approve all applies only to the selected confidence list
for this person. The global automatic approval loop remains in Catalogue review.

**Next person** chooses the most frequently confirmed other person with pending
suggestions. **Choose another person** returns to the ranked list. Completing a
person's queue does not advance automatically, and new suggestions may appear
after reevaluation. These are the matcher's current proposals, not a search for
every possible appearance. Switching to **Catalogue review** restores the full
suggestion queue and clears the person filter and selected checkboxes. Changing
people also clears selections so one person's batch cannot include another's.


If the suggestion lists are empty, **Reevaluate unassigned faces** is available
in both review modes. A failed/interrupted matching job also offers **Reevaluate
matches**; this regenerates proposals without automatically assigning faces.
Background matching retries up to twice if saved corrections or matching rules
change during its calculation. Persistent changes stop the job visibly and
leave the last committed suggestions intact. Renaming an existing named person
preserves unrelated suggestions; naming a previously unnamed group removes that
group's own proposals and demotes existing high-confidence flags until reevaluation.


In each confidence list, use the checkboxes or **Select this page**, then choose
**Assign to <name>** or **Not <name>** beside **Approve all**. These selected-only
buttons are disabled until that list has a selection. Selections span pages;
each action affects only selected faces in its confidence list. When multiple
people are proposed, the labels become **Assign selected** and **Not suggested
people**: each face uses the person proposed on its own card. Selections in the
other confidence list are retained, although rejection feedback may move its
affected high-confidence proposals into lower-confidence.

A selected rejection is one atomic, undoable batch. Faces remain unassigned;
the rejected proposals are removed and their feedback is used on reevaluation.
Other high flags for affected people are demoted until refreshed. Undo restores
the selected proposals and their prior rejection records; other demoted flags
remain conservative until reevaluation. Individual card actions remain available.


## Filter and sort the People portraits

Above the round portraits, **Browse people** has **Known people** and **Unknown
people** toggles. Enable both to show everyone, or disable one to focus on the
other. Known means named identities; Unknown includes unnamed groups, Unassigned
faces and the Unknown People bucket. At least one category stays enabled. These
controls affect the portrait directory; suggestion review has its own controls.

**Sort by → Name** starts with **A–Z**. **Face count** starts with **Largest
first**, using the face count printed under each portrait, rather than the number
of unique photos or pending suggestions. Both directions are available. Each sort
remembers its direction, and the selected categories, sort and directions persist
in this browser for the next visit. Portraits continue loading as you scroll;
filtering or changing sort resets the loaded window without limiting the results.
Hiding a category clears unnamed-group selection so hidden groups cannot be moved
accidentally. These display changes do not alter face assignments or matching.
