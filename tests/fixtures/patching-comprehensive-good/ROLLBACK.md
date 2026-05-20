# Rollback Procedure — Payment Platform

## Rollback artefact
- Container image tag from previous successful deployment (stored in deployment history).

## Rollback command
```bash
kubectl rollout undo deployment/payment-api -n production
kubectl rollout undo deployment/payment-worker -n production
```

## Wall-clock estimate
- API rollback: ~3 minutes (rolling update, zero-downtime).
- Worker rollback: ~5 minutes (graceful drain of in-flight jobs).

## Data implications
- Database migrations are backward-compatible for one minor version.
- If a forward-only migration shipped, see the forward-fix criteria below.

## Authorised personnel
- On-call engineer, team lead, or platform SRE.

## Forward-fix vs rollback decision criteria
| Condition | Action |
|---|---|
| Error budget burn rate > 2x baseline for 15 min | Rollback immediately |
| Single non-critical endpoint degraded | Forward-fix within 30 min or rollback |
| Data corruption suspected | Rollback + incident review |

## Last rehearsal
- 2026-04-15 in nonprod-staging (evidence: JIRA-PAY-1234).
