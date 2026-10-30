#!/usr/bin/env python3
"""Warn about a small class of ambiguous closing phrases, without changing issues.

This is a review aid, not GitHub's closing-reference parser. It does not decide
whether work is complete. It scans text (including quoted/code text), using a
short preceding-clause heuristic; false positives and missed cases are possible.
Manual sidebar links and commit-message references are outside this check;
merging into the default branch can close issues independently of this warning.
Only fixed messages are emitted: PR body content is never evaluated or reflected
into workflow commands or Markdown output.
"""

import json
import os
from pathlib import Path
import re


MAX_EVENT_BYTES = 2 * 1024 * 1024
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\b(?:\s*:\s*|\s+)"
    r"(?:(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[1-9][0-9]*\b|"
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*\b)",
    re.IGNORECASE,
)
NEGATION = re.compile(
    r"\b(?:not|never|without|no|cannot)\b|\b(?:ca|do|does|did|is|are|was|were|would|should|must|could)n['’]t\b|\bwon['’]t\b",
    re.IGNORECASE,
)
PARTIAL = re.compile(r"\b(?:partial(?:ly)?|incomplete)\b", re.IGNORECASE)
MESSAGES = {
    "negated": "A closing reference has nearby negation. GitHub may still close the issue; use a non-closing Refs reference for unfinished work.",
    "partial": "A closing reference is described as partial or incomplete. Use Refs unless completing the issue is intentional.",
    "unavailable": "PR reference analysis was unavailable. Review issue references manually; this warning does not determine GitHub closing behavior.",
}


def warnings_for_body(body):
    """Return fixed warning keys; ordinary references/intentional closure pass."""
    found = set()
    previous_end = 0
    for match in CLOSING.finditer(body):
        # Reset after earlier references and sentence/paragraph boundaries.
        # A single newline remains eligible for wrapped Markdown prose.
        prefix = body[max(previous_end, match.start() - 160):match.start()]
        prefix = re.split(r"[.!?;]|\n\s*\n", prefix)[-1]
        if NEGATION.search(prefix):
            found.add("negated")
        if PARTIAL.search(prefix):
            found.add("partial")
        previous_end = match.end()
    return tuple(key for key in ("negated", "partial") if key in found)


def event_warnings(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            return ("unavailable",)
        event = json.loads(raw)
        pull_request = event.get("pull_request") if isinstance(event, dict) else None
        if not isinstance(pull_request, dict):
            return ("unavailable",)
        body = pull_request.get("body")
        if body is None:
            body = ""
        if not isinstance(body, str):
            return ("unavailable",)
        return warnings_for_body(body)
    except (OSError, ValueError, TypeError):
        return ("unavailable",)


def main():
    warnings = event_warnings(os.environ.get("GITHUB_EVENT_PATH", ""))
    for key in warnings:
        print("::warning::" + MESSAGES[key])
    if not warnings:
        print("No ambiguous closing phrase detected by this limited heuristic.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write("## Issue-reference review aid\n\n")
                if warnings:
                    for key in warnings:
                        stream.write("- " + MESSAGES[key] + "\n")
                else:
                    stream.write("No ambiguous closing phrase detected. This is not proof of GitHub's complete closing behavior.\n")
                stream.write("\nThis check does not edit descriptions, close issues or block intentional completion.\n")
        except OSError:
            print("::warning::" + MESSAGES["unavailable"])
    # The analyzer only warns; contributor/reviewer intent still controls closure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
