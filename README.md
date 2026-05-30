# Research Skills

This repository collects Codex skills for research workflows. Each top-level
subdirectory is a complete, self-contained skill.

## Structure

```text
.
├── README.md
├── AGENTS.md
├── ai-search/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
└── paper-citation-resolver/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/
    └── scripts/
```

## Available Skills

### `ai-search`

Query the hosted Google AI Search2API service for live web-grounded answers,
citations, and current-fact research. The skill uses
`https://aisearch.102465.xyz` by default and includes a no-dependency Python
client for the `/query` endpoint.

The bundled client supports:

- environment-based bearer token configuration
- optional instructions and local context files
- Markdown, text, and JSON output
- configurable base URL, model, timeout, and user agent

### `paper-citation-resolver`

Find citation metadata from a verified paper title, DOI, arXiv URL, arXiv ID,
or preprint link. When the title is fuzzy, first recover the canonical title
with `paper-search` or `ai-search`, then run the citation resolver. The skill
is designed for the common research-writing problem where an AI paper is first
cited as an arXiv preprint, but a peer-reviewed conference or journal version
later becomes available and should be cited instead.

The bundled resolver queries public scholarly metadata APIs and returns:

- the recommended citable version
- BibTeX
- APA, MLA, Chicago, and IEEE-style formatted citations
- source evidence and candidate records for manual checking

Because scholarly APIs can be incomplete or unstable, the skill also documents
an agent fallback workflow: use authoritative venue pages and indexes to audit
or repair the script result before returning the final citation.

## Working on Skills

- Keep each skill in its own hyphen-case directory.
- Each skill must include `SKILL.md`.
- Put reusable automation in `scripts/`.
- Put detailed background material in `references/`.
- Skills may include companion `api/` or `mcp/` implementations when a workflow
  benefits from a service interface.
- Prefer Cloudflare Workers for API/MCP services. If the workflow needs native
  binaries, long-running jobs, local disk, or dependencies that do not fit
  Workers, use a lightweight Docker service suitable for deployment on an
  Alibaba Cloud ECS instance in Guangzhou.
- Keep skill folders lean; repository-level documentation belongs at the root.

## Validation

Validate a skill with the local skill creator validator:

```bash
python3 /Users/fwm/.codex/skills/.system/skill-creator/scripts/quick_validate.py ./<skill-name>
```

Run skill-specific scripts directly from the repository root. Example:

```bash
python3 paper-citation-resolver/scripts/resolve_citation.py "Attention Is All You Need"
```
