"""Unit tests for the verifier layer."""

from __future__ import annotations

from codebrain import verifier as v


def test_detect_noop_flags_identical():
    ok, reason = v.detect_noop("Hello world", "Hello world")
    assert not ok
    assert "no-op" in reason


def test_detect_noop_flags_whitespace_only_change():
    ok, _ = v.detect_noop("Hello world", "  HELLO  WORLD  ")
    assert not ok


def test_detect_noop_accepts_real_change():
    ok, _ = v.detect_noop("Hello world", "Greetings earth")
    assert ok


def test_check_word_count_under_min():
    ok, reason = v.check_word_count("one two", min_words=5)
    assert not ok
    assert "below minimum" in reason


def test_check_word_count_over_max():
    ok, reason = v.check_word_count("one two three four five", max_words=3)
    assert not ok
    assert "above maximum" in reason


def test_check_word_count_within_bounds():
    ok, _ = v.check_word_count("one two three", min_words=2, max_words=5)
    assert ok


def test_check_word_count_unbounded():
    ok, _ = v.check_word_count("anything")
    assert ok


def test_check_regex_schema_match():
    ok, _ = v.check_regex_schema("ID: abc-123", r"ID: [a-z]+-\d+")
    assert ok


def test_check_regex_schema_no_match():
    ok, reason = v.check_regex_schema("ID: none", r"ID: [a-z]+-\d+")
    assert not ok
    assert "schema" in reason


def test_check_regex_schema_invalid_pattern():
    ok, reason = v.check_regex_schema("x", "[invalid")
    assert not ok
    assert "invalid regex" in reason


def test_run_checks_all_pass():
    ok, _ = v.run_checks(
        "a b c d e",
        text_in="different",
        min_words=3,
        max_words=10,
        must_match=r"[a-e ]+",
        check_noop=True,
    )
    assert ok


def test_run_checks_returns_first_failure():
    ok, reason = v.run_checks("same", text_in="same", check_noop=True)
    assert not ok
    assert "no-op" in reason


def test_run_checks_noop_requires_text_in():
    ok, reason = v.run_checks("x", check_noop=True)
    assert not ok
    assert "text_in" in reason


def test_tightened_retry_instruction_includes_reason():
    instr = v.tightened_retry_instruction("word count 5 above maximum 3")
    assert "word count 5 above maximum 3" in instr
    assert "regenerate" in instr.lower()
