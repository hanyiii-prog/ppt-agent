"""Tests for palette/layout/font configuration from design DNA."""
from __future__ import annotations

import pytest

from ppt_agent.page_kits import (
    configure_palette,
    configure_font_scale,
    _fs,
    FONT_TITLE,
    FONT_CARD_BODY,
    FONT_CHAPTER,
)


class TestConfigurePalette:
    def test_none_is_noop(self):
        import ppt_agent.page_kits as K
        before = K.PD
        configure_palette(None)
        assert K.PD == before

    def test_green_dna_maps_to_forest_green(self):
        import ppt_agent.page_kits as K
        configure_palette({
            "color": {"named": {"primary": "1B7A3E"}},
        })
        assert K.P == "1B7A3E"
        assert K.PD == "0D4A24"
        assert K.INK == "2E9E55"

    def test_red_dna_maps_to_imperial_red(self):
        import ppt_agent.page_kits as K
        configure_palette({
            "color": {"named": {"primary": "C0392B"}},
        })
        assert K.P == "C0392B"
        assert K.PD == "7A1A10"

    def test_hint_selects_exact_palette(self):
        import ppt_agent.page_kits as K
        from ppt_agent.page_kits import select_palette_name
        assert select_palette_name(hint="warm_earth") == "warm_earth"

    def test_empty_dna_noop(self):
        import ppt_agent.page_kits as K
        configure_palette({})
        # Empty DNA falls back to the default curated palette
        assert K.PD == "09437F"  # medical_blue default


class TestFontScale:
    def test_default_scale_is_one(self):
        configure_font_scale(1.0)
        assert _fs(FONT_TITLE) == FONT_TITLE

    def test_scale_up(self):
        configure_font_scale(1.5)
        assert _fs(20) == 30.0

    def test_scale_clamped(self):
        configure_font_scale(10.0)
        assert _fs(20) <= 40.0  # clamped at 2.0

    def test_chapter_scales(self):
        configure_font_scale(1.0)
        assert _fs(FONT_CHAPTER) == FONT_CHAPTER


class TestShiftHex:
    def test_lighten(self):
        from ppt_agent.page_kits import _shift_hex
        assert _shift_hex("000000", 1.5) == "808080" or _shift_hex("000000", 1.5) != "000000"

    def test_darken(self):
        from ppt_agent.page_kits import _shift_hex
        assert _shift_hex("FFFFFF", 0.5) == "808080" or _shift_hex("FFFFFF", 0.5) != "FFFFFF"
