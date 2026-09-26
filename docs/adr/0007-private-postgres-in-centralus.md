# ADR-0007: Private-access Postgres, deployed to Central US

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

The API needs managed Postgres on Azure. Container Apps consumption egress IPs aren't stable, so a firewall allow-list would mean either "allow all Azure services" (any tenant) or constant maintenance. Separately, this subscription is restricted from creating Postgres Flexible Server in eastus, eastus2 and westus2.

## Decision

Postgres 16 Flexible Server (B1ms) is VNet-injected into a delegated subnet with a private DNS zone and `public_network_access_enabled = false`. The Container Apps environment runs in another delegated subnet of the same VNet. TLS is required (`sslmode=require`). The app is deployed to **centralus**, the first allowed region found; state storage stays in eastus.

## Consequences

- There is no public database endpoint and no firewall rule to get wrong.
- You can't `psql` from a laptop directly; use a job/container inside the VNet or add a jump host.
- The app connects as a DML-only role; only the db-bootstrap job uses the server admin ([ADR-0010](0010-per-workload-identities-and-db-roles.md)).
