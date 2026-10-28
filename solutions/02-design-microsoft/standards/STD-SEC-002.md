---
id: STD-SEC-002
version: "1.1"
title: Data minimization for AI services
scope: all
category: security
keywords: data minimization, personal data, attachments, prompts, completions, request fields, privacy, logging free text
status: approved
---

# STD-SEC-002 · Data minimization for AI services (v1.1)

Send AI services only the fields the use case needs. Attachments and personal data must not be sent. Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers. Document the data flow in the ADR.
