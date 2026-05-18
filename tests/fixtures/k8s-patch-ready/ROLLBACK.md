# Rollback Procedures

## Overview

This document describes the rollback procedures for the patch-ready-app service.

## Automated Rollback

The CI/CD pipeline includes an automated rollback stage that triggers when:

- Health checks fail after deployment
- Error rate exceeds the configured threshold
- The canary analysis detects anomalies

## Manual Rollback

### Kubernetes Deployment Rollback

```bash
# View rollout history
kubectl rollout history deployment/patch-ready-app -n production

# Roll back to the previous revision
kubectl rollout undo deployment/patch-ready-app -n production

# Roll back to a specific revision
kubectl rollout undo deployment/patch-ready-app -n production --to-revision=<N>
```

### Database Rollback

Migration rollback scripts are maintained in the `migrations/` directory.
Each migration has a corresponding `.down.sql` file:

```bash
# Example: revert migration 002
psql -f migrations/002_add_email.down.sql

# Example: revert migration 001
psql -f migrations/001_create_users.down.sql
```

## Rollback Verification

After any rollback, verify:

1. All pods are healthy: `kubectl get pods -n production -l app=patch-ready-app`
2. PDB is satisfied: `kubectl get pdb -n production`
3. Service is responding: `curl -f http://patch-ready-app.production/healthz/ready`
