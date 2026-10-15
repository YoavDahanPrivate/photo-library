# Improving face matching

Open People → **Improve matching with saved examples**. Choose **Analyze matching
quality** to run a stoppable background study. It reads saved embeddings and
labels; it does not read original photographs, change assignments, enable new
rules or retrain the neural network.

## What the report tests

Photographs are deterministically split into reference, tuning and validation
partitions. All video frames and known exact copies stay in one partition.
Each person's contribution is bounded so a large collection does not dominate
the study. Tuning chooses candidate similarity/separation cutoffs; separate
validation decides whether that proposal earns an adjustment. An additional
test removes the true person from the reference gallery to measure mistaken
acceptance of someone absent from it. Supporting evidence still requires two
different photographs/videos.

The report shows per-person reference/validation photograph counts, correct
matches under current/proposed rules, observed mistakes and the decision.
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
approval/correction, then starts one background reevaluation. The preference is
remembered in that browser and can be disabled. Ordinary refresh never approves
faces. Progress and Stop use the same People-operation panel as manual reevaluation.

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
