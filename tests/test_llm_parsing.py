"""Test the lenient JSON parser without invoking any real LLM."""

import pytest

from go_contributor.llm import LLMError, _parse_json_lenient


def test_plain_json():
    assert _parse_json_lenient('{"a": 1}') == {"a": 1}


def test_fenced_json():
    raw = "```json\n{\"a\": 2}\n```"
    assert _parse_json_lenient(raw) == {"a": 2}


def test_prose_then_json():
    raw = "Sure, here is the answer:\n{\"k\": \"v\"}\n"
    assert _parse_json_lenient(raw) == {"k": "v"}


def test_no_json_raises():
    with pytest.raises(LLMError):
        _parse_json_lenient("no braces here")
