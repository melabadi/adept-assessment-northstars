---
id: STD-ARCH-001
version: "1.0"
title: Extend before you add
scope: all
category: architecture
keywords: new service, separate service, microservice, new deployable, extension point, in-process, existing service, architecture approach
status: approved
---

# STD-ARCH-001 · Extend before you add (v1.0)

Prefer extending an existing service behind a stable interface over introducing a new deployable component. A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence. Record the justification in an ADR.
