# Improving face matching

Open People → **Improve matching with saved examples**. Choose **Analyze matching
quality** to run a stoppable background study. It reads saved embeddings and
labels; it does not read original photographs, change assignments, enable new
rules or retrain the neural network.

## What the report tests

Photographs are deterministically split into reference, tuning and validation
partitions. All video frames and known exact copies stay in one partition.
Every eligible fitting photograph contributes a reference; tuning and validation
are capped at 80 independent photographs per person. Compared with the former
96-reference/40-query study, this represents people with larger collections more
fully while bounding the query work. Tuning chooses candidate similarity/separation cutoffs; separate
validation decides whether that proposal earns an adjustment. An additional
test removes the true person from the reference gallery to measure mistaken
acceptance of someone absent from it. Supporting evidence still requires two
different photographs/videos.

The report shows per-person reference/validation photograph counts, correct
matches under enabled/trial rules, observed mistakes and the decision. Validated
existing rules can be retained when a new trial offers no improvement. A change
to enabled rules during analysis or before application invalidates the draft.
Conflicting examples include normal mistaken predictions and simulated open-set
errors; the latter deliberately omit the saved identity from the gallery.
People without sufficient evidence retain conservative rules. The study is
against **saved labels**, which may include mistakes and previous automatic
confirmations. Related burst photos can remain correlated. Zero observed errors
in a finite test is not a guaranteed accuracy percentage or proof of identity.

The People page always shows the effective **Matching rules: Conservative /
Calibrated** mode, including fallback when saved labels have changed. A report
alone does not enable calibrated rules.

Review the report, then choose **Enable reviewed matching rules**. Enabling
automatically starts reevaluation and clears existing high-confidence flags
until that pass publishes a consistent replacement. It does not approve faces. The optional Auto approve
loop uses enabled rules when the user starts it. **Use conservative rules**
disables the profile and automatically reevaluates afterwards. A stale report is rejected if
reviews changed before enablement. Relabelled/deleted examples used by an
enabled profile cause fallback to conservative matching until another analysis.

## Review batches and useful examples

Use **Suggested person** to focus on one identity, then **Spread across dates**
to see a representative from each date/photo bucket before repeated examples.
This is date variety, not an inferred age/pose classifier. Check individual
faces or **Select this page**, then **Approve selected N**. Only the exact
selected face/identity pairs are submitted. The batch can be undone.

Approve all applies to the displayed confidence section and person filter.
Auto approve high-confidence covers all people in the visible library,
independent of that review filter. Match cards explain which evidence is missing:
similarity, separation from another person, or supporting photographs/videos.

**Refresh matches after reviewing** waits eight seconds after the latest saved
approval/correction/rejection, then starts one background reevaluation. The preference is
remembered in that browser and can be disabled. Ordinary refresh never approves
faces. Progress and Stop use the same People-operation panel as manual reevaluation.

## Learning from “Not this person”

Rejections are saved per face and rejected person. The next ordinary
reevaluation uses their saved embeddings as negative examples for that person;
no original file reads, encoder retraining or prior assignment changes are
needed. Existing rejections participate too. Exact rejected face/person pairs
remain excluded even when the example cannot safely generalize.

Each negative example gets a local neighbourhood protected by that person's
confirmed faces: its similarity cutoff is at least 0.65 and at least 0.05 above
its closest confirmed positive. A new face inside that neighbourhood is withheld
when the negative match also exceeds its positive match by at least 0.03.
Borderline faces remain reviewable, but high confidence additionally requires
their positive score to exceed nearby negative evidence by 0.04. The base
calibrated/conservative rules and two-independent-media support still apply.
These are conservative operational separation rules, not accuracy percentages
or a guarantee that every photograph of a rejected person will be recognized.

Nearly identical conflicting labels (cosine similarity at least 0.95), missing
embeddings and unavailable/dismissed examples do not spread a rejection to
other faces. Conflicts are counted in reevaluation results. Rejections target
only the rejected identity; confirming the correct identity adds positive
evidence for that person. An explicit confirmation overrides that face's
rejection of the confirmed identity. Undo removes its learned influence on the
next reevaluation. Corrective reassignment also invalidates the former person's
high-confidence flags.

Saving a rejection immediately demotes that person's old high-confidence flags
until reevaluation, so automatic approvals cannot use confidence computed before
the feedback. Other cards remain reviewable. Background refresh applies the
learning after the usual idle delay; with refresh disabled, choose **Reevaluate
unassigned faces**. Group identity hints use the same negative evidence.
Progress reports withheld lookalikes, borderline demotions and conflicting
examples. The additive evidence table is disposable; original annotations and
review history remain authoritative. The first upgrade demotes legacy high
flags once, retaining suggestions until the first new reevaluation.

## Reuse of saved comparisons

The matcher caches candidate/reference comparisons under
`DAHAN_DATA/face-matching/comparisons.npz`. Unchanged people reuse exact saved
scores/support counts. Changed reference sets are rescored; newly added or
modified candidates are compared as needed. Rejections and current labels/rules
are always checked again before publishing suggestions. The first pass still
does the full comparison work. This is an optional performance cache, not the
authoritative catalogue; an unreadable/corrupt cache causes recomputation.

Profiles and suggestion evidence are stored in SQLite. New tables are additive;
existing faces, embeddings, identities, approvals, corrections and history are
preserved. Stop/stale-review errors retain the previous suggestion queue.

## Automatic-reference feedback: known limitation

Automatic high-confidence approvals are saved with the same `manual` face status
as explicit assignments, and subsequent reevaluation includes them as reference
examples. The approval history distinguishes how a batch was created, but the
live reference selector does not yet use that provenance to separate trust.
An early incorrect automatic match can therefore become evidence for later
matches, especially when a person has a large reference gallery and scoring
uses the closest single reference.

A read-only diagnosis confirmed that a person's remaining low-confidence queue
depended largely on automatically approved references. This does not establish
which individual saved identities are wrong, and no labels were changed by the
diagnosis. The UI's per-person queue filtering was checked separately and worked.

Human/automatic reference separation, stronger independent corroboration and a
reference-audit workflow are follow-up work; they are not implemented by this
milestone. Retrospective cleanup must preserve explicit corrections and history.
Calibration splits photos, but its saved labels may include automatic approvals:
zero observed held-back errors is not independent evidence of identity accuracy.

## Recognition model candidates

SFace remains the active encoder. No model weights are changed by calibration.
Candidates for a separately measured comparison include:

| Candidate | Why evaluate it |
| --- | --- |
| [InsightFace ArcFace / buffalo_l](https://github.com/deepinsight/insightface/blob/master/python-package/docs/model_zoo.md) | Established pretrained recognition option and useful reference baseline. |
| [InsightFace antelopev2](https://github.com/deepinsight/insightface/blob/master/python-package/docs/model_zoo.md) | Larger recognition backbone, worth comparing against buffalo_l for difficult examples. |
| [AdaFace](https://github.com/mk-minchul/AdaFace) | Quality-adaptive recognition, particularly relevant to degraded/low-quality faces. |
| [MagFace](https://github.com/IrvingMeng/MagFace) | Recognition plus quality assessment, potentially useful for reference selection and difficult-face handling. |

The recommendation is to compare ArcFace and AdaFace first on held-back,
reviewed photographs, including age changes, small faces, blur, profiles and
similar relatives. Measure wrong identity assignments alongside recovered
matches and CPU/runtime cost. Published benchmark percentages are not expected
accuracy on a household library. Code and pretrained-weight licences are
separate; InsightFace's distributed pretrained weights have research-use terms.

A future model comparison must version embeddings separately and preserve
existing face IDs, annotations and old embeddings. Higher-resolution crop
extraction and a production model switch remain separate work; this release
does not rescan originals or install another recognition engine.

Validation: 403 backend tests, frontend build and three mocked browser workflows
passed. Matching tests cover cache invalidation/corruption, separate validation,
wrong-match rejection, stale profiles, cancellation and retained annotations.


## Grouped review trial

`GET /api/people/review-groups` builds read-only sets from visible, ready,
lower-confidence suggestions. It excludes exact rejected pairs and already
named/dismissed faces. All members have the same suggested identity, and every
pair must meet the selected cosine-similarity floor: 0.78 for tighter sets or
0.70 for broader sets. A transitive A–B–C bridge cannot join A and C when their
similarity fails the floor. These values are grouping controls, not accuracy
probabilities or relaxed recognition rules.

Sets are bounded to 64 members and formed in deterministic 512-face blocks per
suggested identity. The endpoint analyzes up to 20,000 candidates per request,
reports the analyzed/total counts, and leaves every ungrouped/unanalysed face in
individual review. Four sets are returned per UI page, with representative,
different-appearance and lower-score examples plus access to all members.
Approval uses the existing exact-selection batch transaction and Undo. Backend
stale-face guards and the browser's changed-revision guard reject stale previews.

The isolated trial compared the former bounded gallery, a full-photo gallery,
and a three-photo mean-score experiment using the same held-out examples per
run. More references recovered more saved examples for one person, but a relaxed trial still
had an observed open-set/identity error; no live threshold or encoder change was
made on that evidence. Grouping offers a manual workload reduction; it does not
establish that all remaining suggestions are correct.
