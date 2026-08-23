#!/usr/bin/env python3
from __future__ import annotations

import unittest

import refresh_models as rm


class RefreshTests(unittest.TestCase):
    def test_pick_codex_default_prefers_sol(self):
        slugs = ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna"]
        self.assertEqual(rm.pick_codex_default(slugs), "gpt-5.6-sol")

    def test_pick_codex_cheap_prefers_luna(self):
        slugs = ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.4-mini"]
        self.assertEqual(rm.pick_codex_cheap(slugs), "gpt-5.6-luna")

    def test_grok_latest_from_catalog(self):
        catalog = {
            "models": {
                "grok-4.5": {"info": {"description": ""}},
                "grok-4.6": {"info": {"description": "SpaceXAI's latest frontier model"}},
            }
        }
        self.assertEqual(rm.grok_default(catalog), "grok-4.6")

    def test_grok_picks_highest_version_without_latest_label(self):
        catalog = {
            "models": {
                "grok-4.6": {"info": {"description": ""}},
                "grok-4.7": {"info": {"description": ""}},
            }
        }
        self.assertEqual(rm.grok_default(catalog), "grok-4.7")

    def test_scan_claude_aliases(self):
        html = "Claude Opus 5 and Claude Sonnet 5 and Claude Fable 5"
        self.assertEqual(rm.scan_claude(html)["opus"], "opus")
        self.assertEqual(rm.scan_claude(html)["sonnet"], "sonnet")

    def test_matrix_mentions_unpinned(self):
        snap = {
            "as_of": "2026-08-23T00:00:00Z",
            "observed": {
                "grok_default": "grok-4.6",
                "codex_default": "gpt-5.6-sol",
                "codex_cheap": "gpt-5.6-luna",
                "claude_hard": "opus",
            },
        }
        text = rm.render_matrix(snap)
        self.assertIn("생략", text)
        self.assertIn("MiniMax-M3", text)
        self.assertIn("qwen", text.lower())


if __name__ == "__main__":
    unittest.main()
