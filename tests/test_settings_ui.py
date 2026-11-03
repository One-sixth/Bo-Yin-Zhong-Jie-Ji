# -*- coding: utf-8 -*-
"""SettingsInterface（设置页）离屏冒烟测试，缺 PySide6/qfluentwidgets 时自动跳过"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import PySide6  # noqa: F401
    import qfluentwidgets  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False

import config as cfg


@unittest.skipUnless(HAS_QT, "PySide6/qfluentwidgets not installed")
class TestSettingsInterfaceOffscreen(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls._snapshot = {
            k: v for k, v in vars(cfg).items()
            if not k.startswith("_") and not callable(v)
        }
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        import main_ui
        cls.main_ui = main_ui
        cls.si = main_ui.SettingsInterface()

    @classmethod
    def tearDownClass(cls):
        vars(cfg).update(cls._snapshot)

    def test_controls_exist(self):
        """全部设置控件已创建"""
        for name in (
            "bbdown_edit", "bbdown_button", "bbdown_other_args_edit",
            "qwen3_asr_edit", "qwen3_asr_button", "qwen3_asr_other_args_edit",
            "llm_gguf_edit", "llm_gguf_button",
            "llama_cpp_edit", "llama_cpp_button", "llama_cpp_port_edit",
            "llama_cpp_other_args_edit",
            "use_remote_llama_server_checkbox",
            "remote_llama_server_address_edit", "remote_llama_server_key_edit",
            "text2md_prompt_edit", "text2md_prompt_button",
            "summary_prompt_edit", "summary_prompt_button",
        ):
            self.assertTrue(hasattr(self.si, name), name)

    def test_load_config_fills_widgets(self):
        """load_config 将 cfg 回填进控件"""
        self.si.load_config()
        self.assertEqual(self.si.bbdown_edit.text(), cfg.bbdown_exe)
        self.assertEqual(self.si.llama_cpp_port_edit.text(), str(cfg.llama_cpp_port))
        self.assertEqual(self.si.text2md_prompt_edit.toPlainText(), cfg.text2md_prompt)
        self.assertEqual(self.si.summary_prompt_edit.toPlainText(), cfg.summary_prompt)

    def test_remote_checkbox_toggles_address_and_key(self):
        """checkbox 切换联动远程地址/密钥的启用状态"""
        self.si.use_remote_llama_server_checkbox.setChecked(False)
        self.assertFalse(self.si.remote_llama_server_address_edit.isEnabled())
        self.assertFalse(self.si.remote_llama_server_key_edit.isEnabled())
        self.si.use_remote_llama_server_checkbox.setChecked(True)
        self.assertTrue(self.si.remote_llama_server_address_edit.isEnabled())
        self.assertTrue(self.si.remote_llama_server_key_edit.isEnabled())

    def test_on_changed_updates_cfg(self):
        """路径/参数回调实时写入 cfg"""
        self.si.on_bbdown_edit_changed("X:/fake/bbdown.exe")
        self.assertEqual(cfg.bbdown_exe, "X:/fake/bbdown.exe")
        self.si.on_bbdown_other_args_edit_changed("--a --b")
        self.assertEqual(cfg.bbdown_other_args, ["--a", "--b"])
        self.si.on_llm_gguf_edit_changed("X:/fake/model.gguf")
        self.assertEqual(cfg.llm_gguf_file, "X:/fake/model.gguf")
        self.si.text2md_prompt_edit.setPlainText("sum {text}")  # textChanged 信号驱动回调
        self.assertEqual(cfg.text2md_prompt, "sum {text}")
        self.si.summary_prompt_edit.setPlainText("merge {text}")
        self.assertEqual(cfg.summary_prompt, "merge {text}")

    def test_port_edit_tolerates_empty_and_invalid(self):
        """端口框清空/非数字不抛异常，有效值正常写入"""
        old = cfg.llama_cpp_port
        self.si.on_llama_cpp_port_edit_changed("")      # 不应抛 ValueError
        self.assertEqual(cfg.llama_cpp_port, old)
        self.si.on_llama_cpp_port_edit_changed("abc")   # 不应抛 ValueError
        self.assertEqual(cfg.llama_cpp_port, old)
        self.si.on_llama_cpp_port_edit_changed("8888")
        self.assertEqual(cfg.llama_cpp_port, 8888)

    def test_disable_enable_all(self):
        """禁用/启用覆盖全部设置控件，远程项按 cfg 恢复"""
        cfg.use_remote_llama_server = False
        self.si.enable_all_button()
        self.si.disbale_all_button()
        for w in self.si._all_setting_widgets():
            self.assertFalse(w.isEnabled())
        self.si.enable_all_button()
        remote = {id(self.si.remote_llama_server_address_edit), id(self.si.remote_llama_server_key_edit)}
        for w in self.si._all_setting_widgets():
            if id(w) in remote:
                continue  # 远程两项按 cfg.use_remote_llama_server=False 保持禁用，单独断言
            self.assertTrue(w.isEnabled())
        self.assertFalse(self.si.remote_llama_server_address_edit.isEnabled())
        self.assertFalse(self.si.remote_llama_server_key_edit.isEnabled())
        self.assertTrue(self.si.bbdown_edit.isEnabled())

    def test_feature_interfaces_no_settings_by_default(self):
        """功能界面单体构建时 settings_interface 为 None（防御不炸）"""
        mi = self.main_ui.MainInterface()
        si = self.main_ui.SummaryInterface()
        self.assertIsNone(mi.settings_interface)
        self.assertIsNone(si.settings_interface)
        mi.disbale_all_button()   # 不应 AttributeError
        mi.enable_all_button()
        si.disable_all_buttons()
        si.enable_all_buttons()
        mi.worker_thread.stop(); mi.worker_thread.wait(5000); mi.log_timer.stop()
        si.worker_thread.stop(); si.worker_thread.wait(5000); si.log_timer.stop()


if __name__ == "__main__":
    unittest.main()