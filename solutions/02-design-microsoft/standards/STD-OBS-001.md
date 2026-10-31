---
id: STD-OBS-001
version: "1.2"
title: Observable dependencies
scope: all
category: observability
keywords: telemetry, OpenTelemetry, Application Insights, tracing, spans, metrics, timeout, unavailable state, dependency monitoring
status: approved
---

# STD-OBS-001 · Observable dependencies (v1.2)

Every call to a new dependency emits OpenTelemetry spans and metrics. A dependency timeout must surface a user-facing unavailable state within two seconds of the timeout, and the core business flow must continue without the dependency.
