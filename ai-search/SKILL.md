---
name: ai-search
description: Run live web and current-fact research through the hosted googleaisearch2api service at https://aisearch.102465.xyz. Use when Codex needs AI-generated Google Search answers, web-grounded summaries, source/citation discovery, recent information, or when the user explicitly asks to use AI Search, Google AI Search, googleaisearch2api, /query, /v1/chat/completions, or /v1/responses.
---

# AI Search

## Overview

Query the hosted Google AI Search2API service and return a grounded answer plus
any citations the service provides. Prefer the bundled script for repeatable
calls and use the raw API only when the script needs adaptation.

## Configuration

Set the token in the environment before making requests:

```bash
export AI_SEARCH_API_KEY="..."
```

Optional environment variables:

- `AI_SEARCH_BASE_URL`: override the default `https://aisearch.102465.xyz`.
- `AI_SEARCH_MODEL`: override the default `google-search`.
- `AI_SEARCH_TIMEOUT`: request timeout in seconds.
- `AI_SEARCH_USER_AGENT`: override the default `curl/8.7.1`.

Never commit bearer tokens into skill files, scripts, shell history snippets, or
final reports. Use environment variables or a local secret store.

## Workflow

1. Start with `scripts/ai_search.py` for normal research queries.
2. Ask focused questions and include the date or region when recency matters.
3. Preserve returned citations in the user-facing answer when they are useful.
4. If citations are missing, weak, or conflict with primary sources, say so and
   verify with authoritative sources before presenting high-stakes claims.
5. For API details or direct curl examples, read `references/api.md`.

## Quick Commands

Return a Markdown answer with citations:

```bash
python3 ai-search/scripts/ai_search.py "What changed in OpenAI model releases this week?"
```

Add search instructions:

```bash
python3 ai-search/scripts/ai_search.py \
  "Compare the latest Apple and Google AI announcements" \
  --instructions "Prioritize official sources and include dates."
```

Return raw JSON for further parsing:

```bash
python3 ai-search/scripts/ai_search.py "latest SQLite release notes" --format json
```

Use extra local context:

```bash
python3 ai-search/scripts/ai_search.py \
  "Find current support policy for these dependencies" \
  --context-file pyproject.toml
```

## Output Policy

Treat AI Search as a research accelerator, not the sole source of truth. For
medical, legal, financial, security, or production-impacting answers, corroborate
important claims with primary or official sources. Report service failures,
timeouts, empty citations, and ambiguity instead of hiding them.

## Service Notes

The upstream service wraps Google AI Search through browser automation and
exposes OpenAI-compatible endpoints. It is not a Google official public API, and
Google page changes can affect reliability.
