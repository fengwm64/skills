# Project Notes for Agents

This repository is a collection of research-oriented Codex skills. Treat every
top-level hyphen-case directory as one complete skill.

## Conventions

- Use lowercase hyphen-case for skill directories and skill names.
- Do not place multiple skills in one directory.
- Required skill file: `SKILL.md`.
- Recommended skill UI metadata: `agents/openai.yaml`.
- Put deterministic, reusable workflow code in `scripts/`.
- Put longer procedural or domain references in `references/`.
- A skill may include a companion API or MCP service when that makes the skill
  more useful or reusable.
- Prefer `api/cloudflare-worker/` or `mcp/cloudflare-worker/` for service
  implementations. Use the Cloudflare Workers stack first.
- If Workers cannot support the runtime shape, use a lightweight Docker service
  under `service/docker/`, designed for deployment on Alibaba Cloud ECS in
  Guangzhou.
- Avoid README, changelog, or install docs inside individual skill directories;
  keep human-facing repository documentation at the root.
- Prefer concise skill bodies. Move optional details into `references/`.

## Validation

After creating or materially editing a skill, run:

```bash
python3 /Users/fwm/.codex/skills/.system/skill-creator/scripts/quick_validate.py ./<skill-name>
```

For scripts, run at least one representative command and record any limitations
in the final response.

## Current Skills

- `paper-citation-resolver`: resolves paper titles, DOIs, arXiv identifiers, and
  preprint URLs to the best current citation, prioritizing peer-reviewed
  conference or journal versions over preprints when evidence supports it.

## Citation Resolver Notes

The citation resolver depends on public metadata services. Network failures,
missing API records, or ambiguous matches should be surfaced rather than hidden.
When a preprint and a peer-reviewed version disagree, prefer the version with a
DOI, venue/container title, publication date, and matching title/authors. Keep
arXiv as a fallback when no reviewed version is found.

Do not treat API output as the only source of truth. Because scholarly metadata
APIs can be incomplete, stale, rate-limited, or polluted by preprint-like DOI
records, use agent research as a fallback: search authoritative venue pages,
DBLP, OpenReview, PMLR, ACL Anthology, ACM/IEEE, publisher pages, and arXiv
metadata, then report the evidence used for the final citation.
