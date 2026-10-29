# -*- coding: utf-8 -*-
"""main_ui.py 离屏 UI 冒烟测试（无 PySide6/qfluentwidgets 时自动跳过）"""
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import PySide6  # noqa: F401
    import qfluentwidgets  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False

import config as cfg


@unittest.skipUnless(HAS_QT, "PySide6/qfluentwidgets not installed")
class TestMainUIOffscreen(unittest.TestCase):

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
        cls.mi = main_ui.MainInterface()
        cls.si = main_ui.SummaryInterface()

    @classmethod
    def tearDownClass(cls):
        for iface in (cls.mi, cls.si):
            iface.worker_thread.stop()
            iface.worker_thread.wait(5000)
            iface.log_timer.stop()
        vars(cfg).update(cls._snapshot)

    def test_stop_buttons_exist_and_enabled(self):
        for iface in (self.mi, self.si):
            self.assertTrue(hasattr(iface, "stop_button"))
            self.assertTrue(iface.stop_button.isEnabled())

    def test_stop_buttons_not_disabled_during_task(self):
        """disable_all_* 不应禁用停止按钮（任务运行时必须可点）"""
        self.mi.disbale_all_button()
        self.assertTrue(self.mi.stop_button.isEnabled())
        self.mi.enable_all_button()

        self.si.disable_all_buttons()
        self.assertTrue(self.si.stop_button.isEnabled())
        self.si.enable_all_buttons()

    def test_stop_tasks_no_task_is_safe(self):
        """无任务时点停止：安全提示、不误置标志"""
        cfg.stop_requested = False
        self.mi.stop_tasks()
        self.si.stop_tasks()
        self.assertIs(cfg.stop_requested, False)

    def test_stop_tasks_with_working_thread_sets_flag(self):
        """任务运行中点停止：置位标志"""
        cfg.stop_requested = False
        self.mi.worker_thread._working = True
        try:
            self.mi.stop_tasks()
            self.assertIs(cfg.stop_requested, True)
        finally:
            self.mi.worker_thread._working = False
            cfg.stop_requested = False

    def test_worker_resets_stop_flag_on_new_task(self):
        """核心回归：新任务开始时自动清除上次残留的停止请求"""
        w = self.main_ui.WorkerThread()
        result = {}
        ev = threading.Event()

        def task():
            result["flag"] = cfg.stop_requested
            ev.set()

        cfg.stop_requested = False
        w.send_task([task, []])
        cfg.stop_requested = True  # 模拟上次任务遗留的停止请求
        w.start()
        try:
            self.assertTrue(ev.wait(10), "task did not run in time")
            w.stop()
            self.assertTrue(w.wait(5000))
            self.assertIs(result["flag"], False, "stop flag was not reset for new task")
        finally:
            cfg.stop_requested = False

    def test_worker_survives_task_exception(self):
        """任务抛异常：线程不死、task_error 信号发出、按钮可恢复"""
        w = self.main_ui.WorkerThread()
        errors = []
        done_evt = threading.Event()
        error_evt = threading.Event()

        def boom():
            raise RuntimeError("boom")

        def after_done():
            done_evt.set()

        def on_error(msg):
            errors.append(msg)
            error_evt.set()

        w.task_error.connect(on_error)
        w.task_done.connect(after_done)
        w.send_task([boom, []])
        w.start()
        try:
            # 跨线程信号是 QueuedConnection，需要主线程 processEvents 投递
            import time as _time
            deadline = _time.time() + 10
            while _time.time() < deadline and not error_evt.is_set():
                self.app.processEvents()
                _time.sleep(0.05)
            self.assertTrue(error_evt.is_set(), "task_error not emitted")
            self.assertIn("RuntimeError", errors[0])
            deadline = _time.time() + 10
            while _time.time() < deadline and not done_evt.is_set():
                self.app.processEvents()
                _time.sleep(0.05)
            self.assertTrue(done_evt.is_set(), "task_done not emitted after error")
        finally:
            w.stop()
            self.assertTrue(w.wait(5000))

    def test_task_buttons_disabled_then_enabled(self):
        self.mi.disbale_all_button()
        self.assertFalse(self.mi.full_process_button.isEnabled())
        self.mi.enable_all_button()
        self.assertTrue(self.mi.full_process_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
