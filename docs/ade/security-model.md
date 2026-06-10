# ADE — Security Model

## Threat model

An autonomous agent that can start jobs, move data, and modify ML serving is
itself the biggest risk in this system. The security model therefore treats
the LLM output as **untrusted input** and constrains what any component can
do even if the planner is wrong, manipulated, or compromised.

| Threat | Mitigation |
|---|---|
| LLM proposes harmful/unknown action (incl. prompt injection via data) | Hard allowlist in `ACTION_CATALOG`; unknown actions reject the whole plan; plan size capped |
| LLM triggers destructive change | Destructive actions (`promote_model`, `rollback_model`, `trigger_retraining`, `apply_cost_recommendation`) are *forced* to approval regardless of model output |
| Runaway remediation loops | Per-incident retry budget + circuit breaker → escalate |
| Cost blowout (agent or otherwise) | AWS Budgets backstop independent of agent code; LLM budget env cap; spot training |
| Credential theft from code | No static secrets anywhere: Lambda IAM roles, GitHub OIDC for deploys |
| Data exfiltration / tampering | Per-function least-privilege IAM; KMS everywhere; S3 public access blocked; versioned buckets |
| Privilege escalation by the agent | The agent has **no IAM write permissions**; `permissions` failures escalate to humans by design |
| Tampered deploys | CI runs tests + validation; applies gated by a protected GitHub environment with required reviewers |

## Identity & access

- **One IAM role per Lambda** (`terraform/iam.tf`), each scoped to the exact
  resources that function touches:
  - *agent*: `bedrock:InvokeModel` (anthropic models only), `states:StartExecution`
    on the two ADE state machines, `sns:Publish` on the two ADE topics,
    `glue:StartCrawler` on `ade-*` crawlers.
  - *discovery*: read-only listing of the data lake, Glue catalog, RDS metadata.
  - *drift / worker*: data-lake read (worker also writes curated/quarantine).
  - *cost*: `ce:GetCostAndUsage` only.
  - *docs*: `s3:PutObject` on the docs bucket only.
- Shared baseline grants only: own log group, `cloudwatch:PutMetricData`
  **conditioned on the `ADE` namespace**, the state table, the ADE KMS key,
  and `events:PutEvents` on the ADE bus.
- RDS discovery is **opt-in**: only instances tagged `ade:discover=true`
  are ever scanned.
- Deploys use GitHub OIDC (`id-token: write`) to assume a dedicated deploy
  role — no long-lived AWS keys in CI secrets.

## Data protection

- All S3 buckets: KMS (CMK with rotation), versioning, public access block.
- DynamoDB: CMK encryption + point-in-time recovery.
- SNS topics and CloudWatch log groups encrypted with the same CMK.
- Quarantined records are isolated under `quarantine/` and expire after 90
  days via lifecycle rule.
- The planner prompt contains only metadata (schemas, stats, error strings)
  — row-level data is never sent to the LLM. Error text forwarded to
  incidents is truncated to 2,000 chars.

## Human-in-the-loop boundaries

```
autonomous (no approval)            approval required (SNS → human)
─────────────────────────           ────────────────────────────────
crawl/profile/document              trigger_retraining
build + run ETL pipelines           promote_model / rollback_model
quality checks + quarantine         apply_cost_recommendation
retry/backfill per playbook         anything the planner flags itself
alerts + escalation
```

Dry-run mode (`ADE_DRY_RUN=true`, the Terraform default) additionally turns
*every* non-approval action into a logged no-op — the recommended state for
the first weeks of operation while reviewing the decision audit log.

## Auditability

- Every plan (reasoning, risk, actions, outcomes) is persisted under
  `DECISION#<timestamp>` in DynamoDB.
- Every remediation attempt is persisted under `INCIDENT#<id>`.
- CloudWatch metrics (`PlansAccepted/Rejected`, `Action.*`,
  `EscalationsTriggered`) make agent behavior observable and alarmable.
- Recommended additions for production: CloudTrail data events on the data
  lake bucket, and AWS Config rules on the IAM roles.
