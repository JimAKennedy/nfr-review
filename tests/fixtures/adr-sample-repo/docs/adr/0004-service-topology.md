---
title: Service Topology
status: accepted
date: 2024-03-15
---

# Service Topology

## Context

We need a clear architecture for how our microservices communicate.

## Decision

The following service communication topology is adopted:

- api-gateway → order-service (REST/HTTP)
- api-gateway → payment-service (REST/HTTP)
- order-service → inventory-service (gRPC)

The notification-service is an independent consumer that reads from a shared
event bus and does not participate in synchronous request flows.

## Status

Accepted

## Consequences

- All synchronous inter-service calls must go through the api-gateway
- Direct service-to-service calls bypass the gateway only for gRPC
- The notification-service is decoupled via async events
