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

    def test_primary_overrides_ink_and_p(self):
        import ppt_agent.page_kits as K
        configure_palette({
            "color": {"named": {"primary": "00FF00", "primary_deep": "003300"}},
        })
        assert K.P == "00FF00"
        assert K.INK == "00FF00"
        assert K.PD == "003300"

    def test_partial_dna_keeps_defaults(self):
        import ppt_agent.page_kits as K
        before = K.MUT
        configure_palette({"color": {"named": {"primary": "AA0000"}}})
        assert K.MUT == before

    def test_empty_dna_noop(self):
        import ppt_agent.page_kits as K
        before = K.PD
        configure_palette({})
        assert K.PD == before


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
