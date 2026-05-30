#!/usr/bin/env python3
"""Query a googleaisearch2api /query endpoint and render a usable answer."""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://aisearch.102465.xyz"
DEFAULT_MODEL = "google-search"
DEFAULT_USER_AGENT = "curl/8.7.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query the hosted AI Search API and print answer/citations."
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Search question. If omitted, stdin is used.",
    )
    parser.add_argument(
        "--instructions",
        help="Optional system-style instructions for the search answer.",
    )
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        help="Optional context string. May be repeated.",
    )
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        type=Path,
        help="Read additional context from a local file. May be repeated.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "text", "json"),
        default="markdown",
        help="Output format. Default: markdown.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AI_SEARCH_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("AI_SEARCH_API_KEY"),
        help="Bearer token. Prefer AI_SEARCH_API_KEY instead of this flag.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("AI_SEARCH_MODEL", DEFAULT_MODEL),
        help=f"Model name. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--timeout",
        default=float(os.environ.get("AI_SEARCH_TIMEOUT", "90")),
        type=float,
        help="Request timeout in seconds. Default: 90.",
    )
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("AI_SEARCH_USER_AGENT", DEFAULT_USER_AGENT),
        help=f"HTTP User-Agent header. Default: {DEFAULT_USER_AGENT}",
    )
    return parser.parse_args()


def read_query(parts: list[str]) -> str:
    if parts:
        return " ".join(parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise SystemExit("No query supplied. Pass a query argument or pipe stdin.")


def build_context(args: argparse.Namespace) -> str | list[dict[str, str]] | None:
    chunks = [item.strip() for item in args.context if item.strip()]
    for path in args.context_file:
        try:
            chunks.append(f"# {path}\n{path.read_text(encoding='utf-8')}")
        except OSError as exc:
            raise SystemExit(f"Failed to read context file {path}: {exc}") from exc
    if not chunks:
        return None
    return "\n\n".join(chunks)


def post_query(args: argparse.Namespace, query: str) -> dict[str, Any]:
    if not args.api_key:
        raise SystemExit("AI_SEARCH_API_KEY is required.")

    payload: dict[str, Any] = {
        "model": args.model,
        "query": query,
        "stream": False,
    }
    if args.instructions:
        payload["instructions"] = args.instructions
    context = build_context(args)
    if context:
        payload["context"] = context

    base_url = args.base_url.rstrip("/")
    url = urllib.parse.urljoin(f"{base_url}/", "query")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": args.user_agent,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"AI Search HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"AI Search request failed: {exc.reason}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"AI Search returned non-JSON response:\n{text}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"AI Search returned unexpected JSON: {data!r}")
    return data


def answer_from_response(data: dict[str, Any]) -> str:
    answer = data.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"].strip()

    output = data.get("output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        if texts:
            return "\n".join(texts).strip()

    return ""


def citation_label(item: Any, index: int) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)

    title = first_string(item, ("title", "name", "source", "label")) or f"Source {index}"
    url = first_string(item, ("url", "uri", "link", "href"))
    snippet = first_string(item, ("snippet", "text", "description"))
    parts = [title]
    if url:
        parts.append(f"<{url}>")
    if snippet:
        parts.append(f"- {snippet}")
    return " ".join(parts)


def first_string(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def render_markdown(data: dict[str, Any]) -> str:
    answer = answer_from_response(data)
    citations = data.get("citations")
    usage = data.get("usage")

    sections: list[str] = []
    sections.append(answer if answer else "_No answer field returned._")

    if isinstance(citations, list) and citations:
        sections.append(
            "**Citations**\n"
            + "\n".join(
                f"{index}. {citation_label(item, index)}"
                for index, item in enumerate(citations, start=1)
            )
        )
    elif isinstance(citations, list):
        sections.append("**Citations**\n_No citations returned._")
    elif citations is not None:
        sections.append(
            "**Citations**\n"
            + textwrap.indent(json.dumps(citations, ensure_ascii=False, indent=2), "    ")
        )

    if usage:
        sections.append(
            "**Usage**\n"
            + textwrap.indent(json.dumps(usage, ensure_ascii=False, sort_keys=True), "    ")
        )

    return "\n\n".join(sections)


def main() -> int:
    args = parse_args()
    query = read_query(args.query)
    data = post_query(args, query)

    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.format == "text":
        print(answer_from_response(data))
    else:
        print(render_markdown(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
