"""Verifier layer — cheap deterministic checks on LLM text output.

The local 14B model is solid on code but drifts on text transforms: no-op
polishes (output ≈ input), ignored word limits, schema violations. The
verifier catches those with regex / length / equality checks before the
result reaches Claude, so the expensive review budget is spent on real
drift, not obvious failures.

Every check returns `(ok, reason)` — a consistent shape that the
generate-verified pipeline loops over.
"""

from __future__ import annotations

import re


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def detect_noop(text_in: str, text_out: str) -> tuple[bool, str]:
    """Return `(ok, reason)` where `ok=False` means the output barely changed from the input.

    Compares the two texts after whitespace-collapse and lowercase. The
    polish/transform tools should produce meaningful deltas; an effective
    no-op is almost always a model failure to engage with the instruction.
    """
    if _normalise(text_in) == _normalise(text_out):
        return False, "output is effectively identical to input (no-op)"
    return True, ""


def check_word_count(
    text: str, min_words: int | None = None, max_words: int | None = None
) -> tuple[bool, str]:
    """Enforce a word-count window. Either bound may be `None` (unbounded on that side)."""
    count = len(text.split())
    if min_words is not None and count < min_words:
        return False, f"word count {count} below minimum {min_words}"
    if max_words is not None and count > max_words:
        return False, f"word count {count} above maximum {max_words}"
    return True, ""


def check_regex_schema(text: str, pattern: str) -> tuple[bool, str]:
    """True iff `text` matches `pattern` (re.search semantics, dotall)."""
    try:
        compiled = re.compile(pattern, re.DOTALL)
    except re.error as exc:
        return False, f"invalid regex pattern: {exc}"
    if compiled.search(text) is None:
        return False, f"output does not match required schema: {pattern}"
    return True, ""


def run_checks(
    text: str,
    text_in: str | None = None,
    min_words: int | None = None,
    max_words: int | None = None,
    must_match: str | None = None,
    check_noop: bool = False,
) -> tuple[bool, str]:
    """Run every requested check in order and return on first failure.

    `check_noop` requires `text_in` to be provided.
    """
    if check_noop:
        if text_in is None:
            return False, "check_noop requires text_in"
        ok, reason = detect_noop(text_in, text)
        if not ok:
            return False, reason
    if min_words is not None or max_words is not None:
        ok, reason = check_word_count(text, min_words, max_words)
        if not ok:
            return False, reason
    if must_match is not None:
        ok, reason = check_regex_schema(text, must_match)
        if not ok:
            return False, reason
    return True, ""


def tightened_retry_instruction(reason: str) -> str:
    """Build a one-line retry directive that names the specific failure."""
    return (
        f"Your previous output failed verification: {reason}. "
        "Regenerate addressing that specific problem. Output only the "
        "corrected result."
    )
