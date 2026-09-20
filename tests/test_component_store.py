"""Tests for the persistent component store and DNA-driven styling."""
import pytest

from ppt_agent.component_store import (
    build_component_from_plan, find_by_kind, list_components,
    load_component, save_component, store_dir,
)
from ppt_agent.component_style import apply_dna_to_slots, resolve_component_style


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr("ppt_agent.component_store.store_dir", lambda: tmp_path / "components")
    (tmp_path / "components").mkdir(exist_ok=True)


def _make_component(cid="cards-grid-4", kind="cards_grid", slots=None):
    if slots is None:
        slots = [
            {"role": "title", "rel": {"x": 0, "y": 0, "w": 1.0, "h": 0.15}},
            {"role": "card-0", "rel": {"x": 0, "y": 0.2, "w": 0.45, "h": 0.35}},
            {"role": "card-1", "rel": {"x": 0.55, "y": 0.2, "w": 0.45, "h": 0.35}},
        ]
    return build_component_from_plan(kind, slots, component_id=cid)


class TestStore:
    def test_save_and_load(self):
        comp = _make_component()
        save_component(comp)
        loaded = load_component("cards-grid-4")
        assert loaded is not None
        assert loaded["component_id"] == "cards-grid-4"

    def test_list(self):
        save_component(_make_component("a", "cards_grid"))
        save_component(_make_component("b", "title_bar"))
        items = list_components()
        assert len(items) == 2

    def test_find_by_kind(self):
        save_component(_make_component("a", "cards_grid"))
        save_component(_make_component("b", "timeline"))
        matches = find_by_kind("cards_grid")
        assert len(matches) == 1
        assert matches[0]["component_id"] == "a"

    def test_find_by_kind_and_count(self):
        save_component(_make_component("a", "cards_grid"))
        comp = _make_component("b", "cards_grid")
        comp["min_items"] = 3
        comp["max_items"] = 3
        save_component(comp)
        assert len(find_by_kind("cards_grid", item_count=2)) == 1
        assert len(find_by_kind("cards_grid", item_count=3)) == 1

    def test_load_missing_returns_none(self):
        assert load_component("nonexistent") is None


class TestStyle:
    def _kind_dna(self):
        return {
            "typography": {"scale_named": {"display": 36, "title": 24, "body": 14, "caption": 11}},
            "color": {"primary": "1A73E8", "text": "333333", "surface": "FFFFFF"},
            "shape": {"line_widths_pt": [0.5]},
            "layout": {"margin_left": 0.7, "margin_top": 0.5},
        }

    def test_title_role_gets_display_size(self):
        style = resolve_component_style({}, self._kind_dna(), role="title")
        assert style["font_size"] == 36

    def test_body_role_gets_body_size(self):
        style = resolve_component_style({}, self._kind_dna(), role="body")
        assert style["font_size"] == 14

    def test_decoration_gets_fill(self):
        dna = self._kind_dna()
        dna["color"]["primary_soft"] = "E8F0FE"
        style = resolve_component_style({}, dna, role="decoration")
        assert style["fill"] == "E8F0FE"

    def test_apply_dna_to_slots(self):
        comp = _make_component()
        pkd = {"kinds": {"content": self._kind_dna()}}
        slots = apply_dna_to_slots(comp, pkd, "content")
        assert len(slots) == 3
        title_slot = next(s for s in slots if s["role"] == "title")
        assert title_slot["style"]["font_size"] == 36
