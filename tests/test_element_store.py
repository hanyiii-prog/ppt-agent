"""Tests for the persistent element store and fingerprint-based caching."""
import pytest

from ppt_agent.element_store import (
    clear, fingerprint_element, increment_usage, list_components, lookup, stats, store,
)
from ppt_agent.element_generator import generate_element, generate_with_cache


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr("ppt_agent.element_store.store_dir", lambda: tmp_path / "elements")
    (tmp_path / "elements").mkdir(exist_ok=True)


class TestFingerprint:
    def test_deterministic(self):
        spec = {"type": "title", "text": "Hello World"}
        fp1 = fingerprint_element(spec)
        fp2 = fingerprint_element(spec)
        assert fp1 == fp2
        assert len(fp1) == 12

    def test_different_text_different_fp(self):
        fp1 = fingerprint_element({"type": "title", "text": "Hello"})
        fp2 = fingerprint_element({"type": "title", "text": "World"})
        assert fp1 != fp2

    def test_same_pattern_same_fp(self):
        fp1 = fingerprint_element({"type": "title", "text": "Chapter 1"})
        fp2 = fingerprint_element({"type": "title", "text": "Chapter 2"})
        assert fp1 == fp2  # digits normalised to #

    def test_different_type_different_fp(self):
        fp1 = fingerprint_element({"type": "title", "text": "Same"})
        fp2 = fingerprint_element({"type": "body", "text": "Same"})
        assert fp1 != fp2


class TestStoreRoundtrip:
    def test_store_and_lookup(self):
        fp = fingerprint_element({"type": "title", "text": "Test"})
        store(fp, {"type": "title", "text": "Test", "font_pt": 28})
        entry = lookup(fp)
        assert entry is not None
        assert entry["element"]["text"] == "Test"

    def test_lookup_missing(self):
        assert lookup("nonexistent00") is None

    def test_usage_counter(self):
        fp = fingerprint_element({"type": "body", "text": "counter test"})
        store(fp, {"type": "body", "text": "counter test"})
        increment_usage(fp)
        increment_usage(fp)
        assert lookup(fp)["usage_count"] == 2

    def test_stats(self):
        fp1 = fingerprint_element({"type": "title", "text": "A"})
        store(fp1, {"type": "title", "text": "A"})
        fp2 = fingerprint_element({"type": "body", "text": "B"})
        store(fp2, {"type": "body", "text": "B"})
        increment_usage(fp1)
        s = stats()
        assert s["total_elements"] == 2
        assert s["total_usage"] == 1


class TestGenerateWithCache:
    def test_first_call_is_miss(self):
        spec = {"type": "title", "text": "cache miss test"}
        element, meta = generate_with_cache(spec)
        assert meta["cache"] == "miss"
        assert meta["generator"] == "rules"

    def test_second_call_is_hit(self):
        spec = {"type": "title", "text": "cache hit test"}
        generate_with_cache(spec)
        element, meta = generate_with_cache(spec)
        assert meta["cache"] == "hit"
        assert meta["generator"] == "cache"

    def test_hit_has_zero_tokens(self):
        spec = {"type": "body", "text": "zero tokens on hit"}
        generate_with_cache(spec)
        _, meta = generate_with_cache(spec)
        assert meta["tokens_estimate"] == 0


class TestGenerateElement:
    def test_rules_title(self):
        element, meta = generate_element({"type": "title", "text": "Hello"})
        assert meta["generator"] == "rules"
        assert element["type"] == "title"

    def test_rules_bullet_list(self):
        element, meta = generate_element({"type": "bullet_list", "items": ["a", "b"]})
        assert element["type"] == "body"
        assert "- a" in element["text"]

    def test_rules_quote(self):
        element, meta = generate_element({"type": "quote", "text": "Wise words"})
        assert element["type"] == "quote"
        assert element.get("italic") is True

    def test_unknown_type_without_llm_gives_placeholder(self):
        element, meta = generate_element({"type": "hologram", "text": "???"})
        assert meta["generator"] == "placeholder"
        assert element.get("_placeholder") is True

    def test_llm_fallback_called_for_unknown(self):
        def fake_llm(prompt):
            return '{"type": "hologram", "text": "LLM made this", "font_pt": 16}'
        element, meta = generate_element({"type": "hologram", "text": "???"}, llm_fn=fake_llm)
        assert meta["generator"] == "llm"
        assert element["text"] == "LLM made this"
        assert meta["tokens_estimate"] > 0
