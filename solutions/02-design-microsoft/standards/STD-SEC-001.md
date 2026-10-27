---
id: STD-SEC-001
version: "2.0"
title: Workload identity for service-to-service calls
scope: all
category: security
keywords: authentication, managed identity, workload identity, secrets, API keys, credentials, Foundry, PostgreSQL
status: approved
---

# STD-SEC-001 · Workload identity for service-to-service calls (v2.0)

Service-to-service calls authenticate with managed identities or workload identity federation. API keys, connection-string secrets, and shared keys must not be stored in configuration or code. Disable local (key) authentication on AI and data services where the service supports it.
