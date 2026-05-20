# Disaster Recovery — Payment Platform

## Failover mechanism
- Traffic is shifted via Istio VirtualService weight adjustment.
- Control point: ArgoCD ApplicationSet targeting the active/passive subsets.
- Failover time: < 2 minutes (DNS TTL 30s + Istio propagation).

## Tested failover
- Last game-day: 2026-03-20 (evidence: JIRA-PAY-1180).
- Automated chaos test runs monthly via Litmus.

## DR topology
- Active region: East US 2
- Passive region: West US 2
- Hot-hot with 70/30 traffic split under normal conditions.
