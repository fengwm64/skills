# AI Search API Reference

Use this reference when direct API calls are needed instead of
`scripts/ai_search.py`.

## Service

- Default base URL: `https://aisearch.102465.xyz`
- Default model: `google-search`
- Authentication: `Authorization: Bearer $AI_SEARCH_API_KEY`
- Default script `User-Agent`: `curl/8.7.1`

Do not hard-code bearer tokens in committed files.

If Cloudflare returns Error 1010 for Python requests, set
`AI_SEARCH_USER_AGENT` or pass `--user-agent`. The bundled script defaults to a
curl-like header because the service was validated with curl.

## Endpoints

- `GET /v1/models`: list available models.
- `POST /query`: lightweight tool endpoint. Prefer this for Codex workflows.
- `GET /query?q=...`: quick manual probe for short, non-sensitive queries.
- `POST /v1/chat/completions`: OpenAI-compatible chat completions endpoint.
- `POST /v1/responses`: OpenAI-compatible responses endpoint.

## `/query` Request

```json
{
  "model": "google-search",
  "query": "What changed in OpenAI Responses API?",
  "instructions": "Optional answer guidance.",
  "context": "Optional extra context.",
  "stream": false
}
```

`context` may also be an array of `{ "role": "...", "content": "..." }`
objects. Supported roles are `system`, `developer`, `user`, and `assistant`.

## `/query` Response

The tool-oriented response is expected to include:

- `answer`: generated answer text.
- `citations`: source metadata when Google AI Search provides it.
- `usage`: request usage metadata when available.
- `google_ai`: lower-level extraction details when available.

## Curl Examples

List models:

```bash
curl "$AI_SEARCH_BASE_URL/v1/models" \
  -H "Authorization: Bearer $AI_SEARCH_API_KEY"
```

Run a POST query:

```bash
curl "$AI_SEARCH_BASE_URL/query" \
  -H "Authorization: Bearer $AI_SEARCH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google-search",
    "query": "What changed in OpenAI Responses API?",
    "stream": false
  }'
```

Use Chat Completions:

```bash
curl "$AI_SEARCH_BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $AI_SEARCH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google-search",
    "messages": [
      {"role": "user", "content": "Summarize current AI search news in 3 bullets."}
    ]
  }'
```

Use Responses:

```bash
curl "$AI_SEARCH_BASE_URL/v1/responses" \
  -H "Authorization: Bearer $AI_SEARCH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google-search",
    "input": "Summarize current AI search news in 3 bullets."
  }'
```

## Boundaries

The upstream implementation wraps Google AI Search with browser automation. It
is not an official Google public API. Page changes, anti-abuse checks, queue
limits, and timeout settings can affect reliability. Streaming responses are
SSE replays after the full Google AI result is available, not native Google
streaming.
