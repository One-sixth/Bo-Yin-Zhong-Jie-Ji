# -*- coding: utf-8 -*-
"""config.py 默认值与运行时标志测试"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg


class TestConfigDefaults(unittest.TestCase):

    def test_project_root_exists(self):
        self.assertTrue(cfg.project_root.is_dir())

    def test_runtime_flag_default_false(self):
        self.assertIs(cfg.stop_requested, False)

    def test_sampling_params(self):
        self.assertIsInstance(cfg.llm_temperature, (int, float))
        self.assertGreater(cfg.llm_max_tokens, 0)

    def test_prompts_have_text_placeholder(self):
        self.assertIn("{text}", cfg.text2md_prompt)
        self.assertIn("{text}", cfg.summary_prompt)

    def test_default_prompts_kept(self):
        self.assertEqual(cfg.text2md_prompt, cfg._default_text2md_prompt)
        self.assertEqual(cfg.summary_prompt, cfg._default_summary_prompt)


if __name__ == "__main__":
    unittest.main()
