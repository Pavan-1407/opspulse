# Model card: SLA-breach predictor

## Purpose
Rank open operations tickets by their probability of finishing after their SLA due date, so a team lead can intervene (reassign, escalate, prioritise) while there is still time. The same model also powers the assignment recommender: it scores each candidate analyst with a what-if prediction.

## Problem framing: landmark prediction
A ticket's risk changes as time passes. Rather than one prediction at intake, the model answers:

> *Given this ticket is still open at time t, what is the probability it breaches?*

- **Training rows:** for every closed historical ticket, one snapshot taken at a random time inside its open interval (and before its due date). The label is whether that ticket eventually breached.
- **Serving rows:** every open ticket, snapshotted *now*.
- Tickets already past due are shown as **Past due**, not scored.

## Features (`app/ml/features.py`)
| Group | Features |
|---|---|
| Ticket | work type, priority, complexity, line items, channel, effective SLA window, expected handling effort |
| Clock | time already open, hours left to due, share of SLA used, day and hour received |
| Queue | team backlog pressure (days of carried-over work), captured at intake |
| Assignee | open load at assignment, skill match, historical speed vs standard |

**Monotonic constraints** keep the model business-sensible: risk can only rise with backlog, assignee load, assignee slowness, effort and share of SLA used, and only fall with hours left and skill match. These constraints cost no accuracy (AUC 0.923 either way) and prevent counter-intuitive explanations.

## Evaluation
**Time-based split:** train on the oldest 80% of tickets (about 14.9k), test on the newest 20% (about 3.7k). Analyst speed is estimated on the training window only.

| Metric | XGBoost | Logistic regression |
|---|---|---|
| ROC-AUC | 0.923 | 0.889 |
| PR-AUC (test base rate 19.5%) | 0.824 | 0.701 |
| Brier | 0.073 | 0.094 |
| Precision @ top 10% | 93.3% | |
| Recall @ top 10% | 47.7% | |

**Accuracy by ticket age** (share of SLA already used when scored):

| SLA used | Breach rate | ROC-AUC |
|---|---|---|
| 0–25% | 8% | 0.88 |
| 25–50% | 21% | 0.88 |
| 50–75% | 48% | 0.85 |
| 75–100% | 82% | 0.85 |

Early predictions still rank well, which is where the business value is: there is time to act.

**Calibration:** binned predicted vs observed rates track the diagonal (plot in the app's Model card page), so a 30% score means roughly 30% of such tickets breach.

## Explanations
Per-ticket drivers use XGBoost's native `pred_contribs` (exact TreeSHAP) in log-odds, so no extra dependency is needed. The UI shows the top five with direction.

## Why the first version was rejected
The first simulator was too deterministic: the model scored **0.99 AUC even at intake**. Real operations are never that predictable, so I treated it as a red flag rather than a win. I added unobserved variability (queue-wait noise, random client-side delays). That brought intake AUC to about 0.87 and landmark AUC to about 0.92, which is believable and still clearly better than the baseline.

## Limitations
- **Synthetic data.** Effects are as strong as the simulator makes them. On real data, expect lower scores and re-check calibration.
- **Day received** ranks as the top driver because the simulated team has no weekend staffing (Friday tickets wait through the weekend). On a 24/7 team that effect would disappear.
- **Backlog pressure at serving time is approximated** from open-ticket expected effort, while training uses the simulator's carried-over backlog. The definitions are aligned but not identical.
- Binary breach/no-breach throws away *how late*. A survival / time-to-close model is on the roadmap.
- No drift monitoring yet. Retrain via `POST /api/ml/retrain`.

## Intended use
Decision support for team leads. It is not designed for automated penalties or individual performance evaluation.
