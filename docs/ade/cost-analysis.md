# ADE — Cost Analysis

Estimates for a moderate deployment: ~20 datasets, ~50 ETL runs/day, weekly
retraining, agent handling ~60 events/day. us-east-1 pricing, June 2026.

## LLM planner (Claude Opus 4.8 on Bedrock)

Pricing: **$5 / 1M input tokens, $25 / 1M output tokens.**

Per planning call:
- System prompt (rules + action catalog): ~1,200 tokens — **cached** after
  the first call within the TTL (cache reads ≈ 0.1× input price).
- Event + memory snapshot: ~1,500 input tokens (uncached).
- Plan output (JSON): ~400 tokens (+ adaptive thinking overhead, est. ~600).

| Item | Tokens/call | Calls/month | $/month |
|---|---|---|---|
| Cached system prompt reads | 1,200 @ $0.50/M | 1,800 | $1.08 |
| Uncached input | 1,500 @ $5/M | 1,800 | $13.50 |
| Output (plan + thinking) | 1,000 @ $25/M | 1,800 | $45.00 |
| **Planner total** | | | **≈ $60** |

Levers: prompt caching is already applied (without it, input cost would
roughly double); batch-able analyses (e.g. nightly doc summaries) can use
the Batches API at 50% off; `effort` can drop to `medium` for routine events.

## AWS infrastructure

| Service | Assumption | $/month |
|---|---|---|
| Lambda (7 fns) | ~120k invocations, 512MB avg, 15s avg | ~$15 |
| Step Functions | 1,500 ETL + 4 retrain executions, ~12 transitions each | ~$0.50 |
| SageMaker training | 4 × 1h ml.m5.xlarge **spot** (~70% off $0.23/h) | ~$0.30 |
| SageMaker endpoint (if real-time serving) | 1 × ml.m5.large 24/7 | ~$83 |
| DynamoDB on-demand | ~3M RRU/WRU | ~$4 |
| S3 (lake + artifacts + docs) | 500 GB mixed classes + requests | ~$10 |
| EventBridge | custom bus events ~100k | ~$0.10 |
| CloudWatch | dashboard, 5 alarms, custom metrics, 30-day logs | ~$15 |
| SNS / Budgets / KMS | email delivery free; 1 CMK | ~$2 |
| **Infra total** | | **≈ $130** (≈ $47 without a real-time endpoint) |

## Total

| Scenario | $/month |
|---|---|
| Batch-only serving | ~$110 |
| With one real-time endpoint | ~$190 |
| Heavy (5× event volume, daily retrains, Glue jobs) | ~$600–900 |

## What ADE saves

The cost module (`ade/cost/optimizer.py`) targets exactly the line items
that dominate ML platform waste; typical findings on an unmanaged account:

| Recommendation | Typical monthly saving |
|---|---|
| Delete idle SageMaker endpoints | $80–250 each |
| Spot for training (built into ADE's job spec) | ~70% of training cost |
| Glue DPU right-sizing at <50% utilization | 30–50% of Glue cost |
| S3 lifecycle (STANDARD → GLACIER_IR after 90d idle) | ~$19 per TB |
| Lambda memory right-sizing | 20–60% of Lambda cost |

A single idle endpoint found and removed pays for the planner LLM bill.
The independent AWS Budgets guardrail (80% actual / 100% forecast alerts)
caps the downside regardless of agent behavior.
