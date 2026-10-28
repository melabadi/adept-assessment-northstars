---
id: STD-OPS-002
version: "2.0"
title: Central AI gateway
scope: enterprise
category: operations
keywords: AI gateway, API Management, quotas, rate limits, model endpoint, production calls
status: approved
---

# STD-OPS-002 · Central AI gateway (v2.0)

Enterprise workloads call model and agent endpoints through the central AI gateway (Azure API Management) to enforce per-department quotas, rate limits, and usage reporting. Direct calls from applications to model endpoints are not allowed in production.
