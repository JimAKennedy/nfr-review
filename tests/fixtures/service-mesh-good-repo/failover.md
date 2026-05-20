# Failover Procedures

## Primary failover

1. Shift traffic to standby cluster via VirtualService weight update.
2. Verify health checks pass on standby pods.
3. Update DNS if cross-region failover is required.

## Rollback

Revert VirtualService weights to restore original traffic distribution.
