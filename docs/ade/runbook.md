# ADE — Operations Runbook

## First deployment

```bash
# 1. Build the Lambda package
make package

# 2. Provision (dry-run mode is the default — keep it for the first week)
cd terraform
terraform init
terraform apply -var alert_email=you@example.com

# 3. Confirm the SNS email subscriptions (check your inbox — twice: alerts + approvals)

# 4. Watch the agent decide without acting
aws logs tail /aws/lambda/ade-dev-agent --follow
```

Prerequisites: Bedrock model access for Anthropic models enabled in the
account/region, and a GitHub OIDC deploy role for CI
(`secrets.AWS_DEPLOY_ROLE_ARN`, `secrets.ALERT_EMAIL`).

### Graduating from dry-run

After reviewing decisions in DynamoDB (`pk` begins with `DECISION#`) and
being satisfied with plan quality:

```bash
terraform apply -var alert_email=you@example.com -var dry_run=false
```

## Routine operations

| Task | How |
|---|---|
| See what the agent decided | DynamoDB partiQL: `SELECT * FROM "ade-dev-state" WHERE begins_with(pk, 'DECISION#')` |
| Approve a destructive action | Reply to the approvals email; then invoke the action manually or re-emit the event with approval recorded |
| Check platform health | CloudWatch dashboard `ade-dev` (link in terraform output `dashboard_url`) |
| Read generated docs | `s3://<docs bucket>/handbook.md` |
| Force a discovery scan | `aws lambda invoke --function-name ade-dev-discovery /dev/stdout` |
| Re-run a failed pipeline | `aws stepfunctions start-execution --state-machine-arn <etl arn> --input '<original input>'` |

## Alarm response

### `ade-*-planner-errors` (agent cannot plan)
1. Check agent Lambda logs for the Bedrock error.
2. Throttling → request a Bedrock TPS quota bump; the agent degrades safely
   (events fail and retry via EventBridge; no actions are taken blind).
3. Model access / auth errors → verify Bedrock model access in the region.

### `ade-*-plans-rejected` (model proposing disallowed actions)
1. Read rejected plans in the logs — the alert includes the reason.
2. Usually indicates prompt/catalog mismatch after a code change. Fix the
   action catalog or planner prompt; redeploy.

### `ade-*-etl-failures` (self-healing may be looping)
1. Find the incident: `INCIDENT#<id>` rows show each attempt + outcome.
2. The circuit breaker escalates after 3 attempts — if you got paged, the
   playbook is exhausted. Common terminal causes: upstream contract change
   (see `schema_drift` decisions), IAM (never auto-fixed), capacity.
3. After fixing the root cause, re-run the pipeline and clear the incident
   rows to reset the breaker.

### Budget alerts (80% / 100% forecast)
1. `aws lambda invoke --function-name ade-dev-cost /dev/stdout` to force a
   cost scan; review anomaly events + recommendations.
2. Apply recommendations (these arrive as approval requests) or raise
   `monthly_budget_usd` deliberately.

## Emergency stop

```bash
# Stop the agent from acting (keeps sensors + audit running)
aws lambda put-function-concurrency --function-name ade-dev-agent --reserved-concurrent-executions 0

# Or flip back to dry-run without a redeploy
aws lambda update-function-configuration --function-name ade-dev-agent \
  --environment "Variables={ADE_DRY_RUN=true,...}"   # preserve other vars
```

Re-enable by deleting the concurrency limit / re-applying Terraform.

## Known limits

- The drift Lambda expects sampled rows in the event payload; very wide
  datasets should sample columns server-side first.
- Approval flow is notify-only (SNS email); a future iteration can move to
  Step Functions `waitForTaskToken` for one-click approve/deny.
- The worker Lambda handles modest data volumes; point the Transform state
  at a Glue job for >1GB partitions.
