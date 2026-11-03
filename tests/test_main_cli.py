# -*- coding: utf-8 -*-
"""main_cli.py 任务编排测试（mock 外部工具，验证断链保护与续传语义）"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_cli


def fake_summarize_ok(txt_file, md_tmp_file, *args, **kwargs):
    """带真实副作用的 summarize 替身：写 md_tmp 文件、返回成功"""
    Path(md_tmp_file).write_text("# 总结", encoding="utf-8")
    return True


def fake_convert_makes_txt(media_file, *args, **kwargs):
    """带真实副作用的 convert 替身：创建非空 txt（模拟 qwen3-asr 正常产出）"""
    txt = Path(media_file).with_suffix(".txt")
    txt.write_text("转录内容", encoding="utf-8")
    return True, txt


class CliTestBase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

        # main_cli 用 from utils import * 值绑定，必须 patch main_cli 模块属性
        for name in ("load_config", "print_config", "start_llama_server",
                     "stop_llama_server", "convert_to_subtitle",
                     "summarize_subtitles"):
            patcher = mock.patch.object(main_cli, name, mock.Mock())
            patcher.start()
            self.addCleanup(patcher.stop)
        main_cli.start_llama_server.return_value = True

        # 吞掉 print 输出，保持测试输出干净
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_media(self, name):
        f = self.folder / name
        f.write_bytes(b"fake")
        return f


class TestCliFlow(CliTestBase):

    def test_no_media_files_early_exit(self):
        main_cli.main(str(self.folder))
        main_cli.start_llama_server.assert_not_called()

    def test_full_flow_success(self):
        a = self._make_media("a.mp4")
        b = self._make_media("b.mp4")

        main_cli.convert_to_subtitle.side_effect = fake_convert_makes_txt
        main_cli.summarize_subtitles.side_effect = fake_summarize_ok

        main_cli.main(str(self.folder))

        self.assertEqual(main_cli.summarize_subtitles.call_count, 2)
        main_cli.stop_llama_server.assert_called_once()
        # 成功后：.complete_asr 标记删除、md 文件落盘
        self.assertFalse(a.with_suffix(".complete_asr").exists())
        self.assertTrue(a.with_suffix(".md").exists())
        self.assertTrue(b.with_suffix(".md").exists())

    def test_existing_md_skipped(self):
        a = self._make_media("a.mp4")
        a.with_suffix(".md").write_text("已有总结", encoding="utf-8")

        main_cli.main(str(self.folder))
        main_cli.convert_to_subtitle.assert_not_called()
        main_cli.summarize_subtitles.assert_not_called()

    def test_complete_asr_marker_skips_asr(self):
        a = self._make_media("a.mp4")
        a.with_suffix(".complete_asr").touch()
        a.with_suffix(".txt").write_text("旧字幕", encoding="utf-8")

        main_cli.summarize_subtitles.side_effect = fake_summarize_ok
        main_cli.main(str(self.folder))

        main_cli.convert_to_subtitle.assert_not_called()  # 跳过 ASR
        self.assertEqual(main_cli.summarize_subtitles.call_count, 1)
        main_cli.summarize_subtitles.assert_called_once()

    def test_empty_txt_skips_summary(self):
        """0 字节 txt（无人声音频）跳过 LLM 总结，不产生 md，标记保留"""
        a = self._make_media("a.mp4")
        a.with_suffix(".complete_asr").touch()
        a.with_suffix(".txt").write_bytes(b"")  # 无人声：转录输出为空

        main_cli.main(str(self.folder))

        main_cli.convert_to_subtitle.assert_not_called()
        main_cli.summarize_subtitles.assert_not_called()  # 空转录不调 LLM
        self.assertFalse(a.with_suffix(".md").exists())
        self.assertTrue(a.with_suffix(".complete_asr").exists())  # 标记保留，不误删

    def test_single_failure_does_not_break_chain(self):
        """单文件总结异常不应中断后续文件（不断链 + 失败清单）"""
        a = self._make_media("a.mp4")
        b = self._make_media("b.mp4")

        main_cli.convert_to_subtitle.side_effect = fake_convert_makes_txt
        calls = {"n": 0}

        def flaky_summarize(txt_file, md_tmp_file, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return fake_summarize_ok(txt_file, md_tmp_file)

        main_cli.summarize_subtitles.side_effect = flaky_summarize

        main_cli.main(str(self.folder))  # 不应抛异常

        self.assertEqual(main_cli.summarize_subtitles.call_count, 2)
        main_cli.stop_llama_server.assert_called_once()
        self.assertTrue(b.with_suffix(".md").exists())
        # 失败文件：标记未删（重跑续传）、md 未生成
        self.assertTrue(a.with_suffix(".complete_asr").exists())
        self.assertFalse(a.with_suffix(".md").exists())

    def test_summarize_stopped_marks_failed(self):
        """summarize 返回 False（任务被停止）→ 计入失败、不删标记"""
        a = self._make_media("a.mp4")
        main_cli.convert_to_subtitle.side_effect = fake_convert_makes_txt
        main_cli.summarize_subtitles.return_value = False

        main_cli.main(str(self.folder))

        self.assertTrue(a.with_suffix(".complete_asr").exists())
        self.assertFalse(a.with_suffix(".md").exists())


if __name__ == "__main__":
    unittest.main()
