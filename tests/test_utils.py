# -*- coding: utf-8 -*-
"""utils.py 核心逻辑单元测试（纯 mock，无真实网络/子进程）"""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg
import utils


def make_print(buf):
    """构造一个收集输出的 print 替身"""
    def p(*values, sep=" ", end="\n", file=None, flush=False):
        buf.append(sep.join(str(v) for v in values) + end)
    return p


class CfgSnapshotTestCase(unittest.TestCase):
    """自动保存/恢复 cfg 模块属性，避免测试间状态污染"""

    def setUp(self):
        self._snapshot = {
            k: v for k, v in vars(cfg).items()
            if not k.startswith("_") and not callable(v)
            and not isinstance(v, types.ModuleType)
        }

    def tearDown(self):
        vars(cfg).update(self._snapshot)


class TestAutoDecode(unittest.TestCase):

    def test_utf8(self):
        self.assertEqual(utils._auto_decode("哔哩哔哩".encode("utf-8")), "哔哩哔哩")

    def test_gbk_fallback(self):
        self.assertEqual(utils._auto_decode("哔哩哔哩".encode("gbk")), "哔哩哔哩")


class TestNormalizeLlamaBaseUrl(CfgSnapshotTestCase):

    def test_variants(self):
        cases = {
            "http://h:1/v1": "http://h:1",
            "http://h:1/v1/": "http://h:1",
            "http://h:1/v1/v1": "http://h:1",
            "http://h:1/v1/v1/": "http://h:1",
            "http://h:1/": "http://h:1",
            "http://h:1": "http://h:1",
            " http://h:1/v1 ": "http://h:1",
            "https://h/v1": "https://h",
            "": "",
            "/v1": "",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(utils._normalize_llama_base_url(raw), want)


class TestRecognizeBvIds(unittest.TestCase):

    def test_single(self):
        self.assertEqual(utils.recognize_bv_ids("BV1abc123456"), ["1abc123456"])

    def test_dedup(self):
        self.assertEqual(
            utils.recognize_bv_ids("BV1abc123456 BV1abc123456"), ["1abc123456"])

    def test_from_url(self):
        text = "https://www.bilibili.com/video/BV1abcdefghi?p=1"
        self.assertEqual(utils.recognize_bv_ids(text), ["1abcdefghi"])

    def test_empty(self):
        self.assertEqual(utils.recognize_bv_ids("no bv here"), [])

    def test_multiple(self):
        text = "BV1abc123456 和 BV1def987654"
        self.assertEqual(utils.recognize_bv_ids(text), ["1abc123456", "1def987654"])


class TestCheckRemoteLlamaCppAddress(CfgSnapshotTestCase):

    def _fake_resp(self, status=200, body=None):
        resp = mock.Mock()
        resp.status_code = status
        resp.json.return_value = body if body is not None else {"status": "ok"}
        if status >= 400:
            resp.raise_for_status.side_effect = utils.requests.HTTPError(str(status))
        else:
            resp.raise_for_status.return_value = None
        return resp

    @mock.patch.object(utils.requests, "get")
    def test_ok_with_key_header(self, mock_get):
        mock_get.return_value = self._fake_resp()
        cfg.remote_llama_server_address = "http://h:1/v1"
        cfg.remote_llama_server_key = "kk"
        self.assertTrue(utils.check_remote_llama_cpp_address())
        url = mock_get.call_args.args[0]
        self.assertEqual(url, "http://h:1/health")
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Authorization"], "Bearer kk")

    @mock.patch.object(utils.requests, "get")
    def test_ok_without_key_no_header(self, mock_get):
        mock_get.return_value = self._fake_resp()
        cfg.remote_llama_server_address = "http://h:1"
        cfg.remote_llama_server_key = ""
        self.assertTrue(utils.check_remote_llama_cpp_address())
        self.assertNotIn("Authorization", mock_get.call_args.kwargs.get("headers") or {})

    @mock.patch.object(utils.requests, "get")
    def test_bad_status(self, mock_get):
        mock_get.return_value = self._fake_resp(body={"status": "error"})
        cfg.remote_llama_server_address = "http://h:1"
        self.assertFalse(utils.check_remote_llama_cpp_address())

    @mock.patch.object(utils.requests, "get")
    def test_http_error(self, mock_get):
        mock_get.return_value = self._fake_resp(status=404)
        cfg.remote_llama_server_address = "http://h:1"
        buf = []
        self.assertFalse(utils.check_remote_llama_cpp_address(print=make_print(buf)))

    @mock.patch.object(utils.requests, "get", side_effect=ConnectionError("refused"))
    def test_connection_error(self, mock_get):
        cfg.remote_llama_server_address = "http://h:1"
        self.assertFalse(utils.check_remote_llama_cpp_address())


class TestGetFirstModelId(CfgSnapshotTestCase):

    def _fake_resp(self, ids):
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"id": i} for i in ids]}
        resp.raise_for_status.return_value = None
        return resp

    def setUp(self):
        super().setUp()
        utils._model_id_cache.clear()

    def tearDown(self):
        utils._model_id_cache.clear()
        super().tearDown()

    @mock.patch.object(utils.requests, "get")
    def test_first_id_and_cache(self, mock_get):
        mock_get.return_value = self._fake_resp(["m1", "m2"])
        self.assertEqual(utils._get_first_model_id("http://h:1/v1", ""), "m1")
        self.assertEqual(utils._get_first_model_id("http://h:1/v1", ""), "m1")
        self.assertEqual(mock_get.call_count, 1)  # 第二次命中缓存

    @mock.patch.object(utils.requests, "get", side_effect=Exception("boom"))
    def test_fallback_default(self, mock_get):
        self.assertEqual(utils._get_first_model_id("http://h:1/v1", "k"), "default")


class FakeReadProc:
    """模拟 raw 模式子进程（download_video 用）"""

    def __init__(self, read_chunks=(), returncode=0):
        self._chunks = list(read_chunks)
        self.returncode = returncode
        self.terminated = False
        self.waited = False
        self.stdout = self

    def read(self, size=-1):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self):
        self.waited = True
        return self.returncode


class FakeReadlineProc:
    """模拟 text 模式子进程（convert_to_subtitle 用）"""

    def __init__(self, lines=(), returncode=0):
        self._lines = list(lines)
        self.returncode = returncode
        self.terminated = False
        self.waited = False
        self.stdout = self

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return ""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self):
        self.waited = True
        return self.returncode


class TestDownloadVideo(CfgSnapshotTestCase):

    def setUp(self):
        super().setUp()
        cfg.stop_requested = False
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = self._tmp.name

    @mock.patch.object(utils.time, "sleep", lambda *_: None)
    @mock.patch.object(utils.subprocess, "Popen")
    def test_basic_and_command_args(self, mock_popen):
        buf = []
        fake = FakeReadProc(read_chunks=[b"line1\n", b"line2\n"], returncode=0)
        mock_popen.return_value = fake

        ok = utils.download_video("1abc123456", self.out_dir, True,
                                  print=make_print(buf))

        self.assertTrue(ok)
        self.assertTrue(fake.waited)
        cmd = mock_popen.call_args.args[0]
        self.assertIn("BV1abc123456", cmd)
        self.assertIn("--audio-only", cmd)
        self.assertIn("--work-dir", cmd)
        self.assertIn(self.out_dir, cmd)

    @mock.patch.object(utils.time, "sleep", lambda *_: None)
    @mock.patch.object(utils.subprocess, "Popen")
    def test_multibyte_across_chunks(self, mock_popen):
        """多字节字符被 read 切断时，行边界缓冲应保证解码正确"""
        buf = []
        bi = "哔哩哔哩".encode("utf-8")
        fake = FakeReadProc(read_chunks=[bi[:2], bi[2:] + b"\n"], returncode=0)
        mock_popen.return_value = fake

        utils.download_video("1abc123456", self.out_dir, False, print=make_print(buf))
        self.assertIn("哔哩哔哩", "".join(buf))

    @mock.patch.object(utils.time, "sleep", lambda *_: None)
    @mock.patch.object(utils.subprocess, "Popen")
    def test_cr_progress_lines(self, mock_popen):
        """BBDown 的 \\r 进度行应转为独立行输出"""
        buf = []
        fake = FakeReadProc(
            read_chunks=[b"\r[progress] 10%\r", b"\r[progress] 50%\n", b"done\n"],
            returncode=0)
        mock_popen.return_value = fake

        utils.download_video("1abc123456", self.out_dir, False, print=make_print(buf))
        text = "".join(buf)
        self.assertIn("[progress] 10%", text)
        self.assertIn("[progress] 50%", text)
        self.assertIn("done", text)

    @mock.patch.object(utils.time, "sleep", lambda *_: None)
    @mock.patch.object(utils.subprocess, "Popen")
    def test_stop_terminates(self, mock_popen):
        buf = []
        fake = FakeReadProc(read_chunks=[b"data\n"], returncode=0)
        mock_popen.return_value = fake
        cfg.stop_requested = True

        ok = utils.download_video("1abc123456", self.out_dir, False, print=make_print(buf))
        self.assertFalse(ok)
        self.assertTrue(fake.terminated)
        self.assertIn("收到停止请求", "".join(buf))

    @mock.patch.object(utils.time, "sleep", lambda *_: None)
    @mock.patch.object(utils.subprocess, "Popen")
    def test_nonzero_exit(self, mock_popen):
        fake = FakeReadProc(read_chunks=[], returncode=2)
        mock_popen.return_value = fake
        ok = utils.download_video("1abc123456", self.out_dir, False, print=make_print([]))
        self.assertFalse(ok)

    @mock.patch.object(utils.subprocess, "Popen")
    def test_busy_rejects_new_download(self, mock_popen):
        """已有 bbdown 进程运行时应拒绝新下载"""
        cfg.bbdown_proc = FakeReadProc(returncode=None)  # poll() -> None 模拟运行中
        ok = utils.download_video("1abc123456", self.out_dir, False, print=make_print([]))
        self.assertFalse(ok)
        mock_popen.assert_not_called()


class TestConvertToSubtitle(CfgSnapshotTestCase):

    def setUp(self):
        super().setUp()
        cfg.stop_requested = False
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    @mock.patch.object(utils.time, "sleep", lambda *_: None)
    @mock.patch.object(utils.subprocess, "Popen")
    def test_normal(self, mock_popen):
        buf = []
        fake = FakeReadlineProc(lines=['{"text": "hi"}\n'], returncode=0)
        mock_popen.return_value = fake
        media = Path(self._tmp.name) / "a.mp4"
        media.write_bytes(b"x")
        (Path(self._tmp.name) / "a.txt").write_text("hi", encoding="utf-8")

        is_ok, out = utils.convert_to_subtitle(media, print=make_print(buf))
        self.assertTrue(is_ok)
        self.assertEqual(out, media.with_suffix(".txt"))

    @mock.patch.object(utils.time, "sleep", lambda *_: None)
    @mock.patch.object(utils.subprocess, "Popen")
    def test_stop_terminates(self, mock_popen):
        buf = []
        fake = FakeReadlineProc(lines=["partial\n"], returncode=0)
        mock_popen.return_value = fake
        cfg.stop_requested = True
        media = Path(self._tmp.name) / "b.mp4"
        media.write_bytes(b"x")

        is_ok, out = utils.convert_to_subtitle(media, print=make_print(buf))
        self.assertFalse(is_ok)  # 输出文件不存在
        self.assertTrue(fake.terminated)


class TestStopAllTasks(CfgSnapshotTestCase):

    def test_terminates_running_procs(self):
        bb = FakeReadProc(returncode=None)   # poll() -> None = 运行中
        asr = FakeReadlineProc(returncode=None)
        cfg.bbdown_proc = bb
        cfg.qwen3_asr_proc = asr
        buf = []
        utils.stop_all_tasks(print=make_print(buf))
        self.assertTrue(bb.terminated)
        self.assertTrue(asr.terminated)

    def test_skips_dead_and_none(self):
        cfg.bbdown_proc = FakeReadProc(returncode=0)  # 已退出
        cfg.qwen3_asr_proc = None
        utils.stop_all_tasks(print=make_print([]))  # 不应抛异常

    def test_none_procs(self):
        cfg.bbdown_proc = None
        cfg.qwen3_asr_proc = None
        utils.stop_all_tasks(print=make_print([]))


def chunk(text):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text))])


class TestQueryLlamaServer(CfgSnapshotTestCase):

    def setUp(self):
        super().setUp()
        cfg.use_remote_llama_server = True
        cfg.remote_llama_server_address = "http://h:1/v1"
        cfg.remote_llama_server_key = "k"
        cfg.stop_requested = False
        utils._model_id_cache.clear()
        self.addCleanup(utils._model_id_cache.clear)

    @mock.patch.object(utils, "_get_first_model_id", return_value="m1")
    @mock.patch.object(utils, "OpenAI")
    def test_normal_stream(self, mock_openai, mock_probe):
        fake_client = mock.Mock()
        mock_openai.return_value = fake_client
        fake_client.chat.completions.create.return_value = iter([chunk("你"), chunk("好")])

        out = utils.query_llama_server("内容", prompt="P {text}", print=make_print([]))
        self.assertEqual(out, "你好")
        api_base = mock_openai.call_args.kwargs["base_url"]
        self.assertEqual(api_base, "http://h:1/v1")
        model = fake_client.chat.completions.create.call_args.kwargs["model"]
        self.assertEqual(model, "m1")

    @mock.patch.object(utils, "_get_first_model_id", return_value="m1")
    @mock.patch.object(utils, "OpenAI")
    def test_stop_interrupts_stream(self, mock_openai, mock_probe):
        fake_client = mock.Mock()
        mock_openai.return_value = fake_client
        fake_client.chat.completions.create.return_value = iter(
            [chunk("a"), chunk("b"), chunk("c")])
        cfg.stop_requested = True

        out = utils.query_llama_server("内容", prompt="P {text}", print=make_print([]))
        self.assertEqual(out, "")

    @mock.patch.object(utils, "_get_first_model_id", return_value="m2")
    @mock.patch.object(utils, "OpenAI")
    def test_404_invalidates_cache_and_retries(self, mock_openai, mock_probe):
        """模型 id 失效 404 时应清缓存重探一次"""
        fake_client = mock.Mock()
        mock_openai.return_value = fake_client
        utils._model_id_cache["http://h:1/v1"] = "stale"
        fake_client.chat.completions.create.side_effect = [
            utils.NotFoundError("model stale not found",
                                response=mock.Mock(status_code=404), body=None),
            iter([chunk("ok")]),
        ]

        out = utils.query_llama_server("内容", prompt="P {text}", print=make_print([]))
        self.assertEqual(out, "ok")
        self.assertEqual(fake_client.chat.completions.create.call_count, 2)
        self.assertNotIn("http://h:1/v1", utils._model_id_cache)  # 旧缓存被清
        self.assertEqual(mock_probe.call_count, 2)                # 重探了一次

    @mock.patch.object(utils, "_get_first_model_id", return_value="m1")
    @mock.patch.object(utils, "OpenAI")
    def test_template_requires_text_placeholder(self, mock_openai, mock_probe):
        fake_client = mock.Mock()
        mock_openai.return_value = fake_client
        fake_client.chat.completions.create.return_value = iter([])
        with self.assertRaises(AssertionError):
            utils.query_llama_server("内容", prompt="no placeholder", print=make_print([]))


class TestSummarizeSubtitles(CfgSnapshotTestCase):

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        cfg.stop_requested = False

    @mock.patch.object(utils, "query_llama_server", return_value="# 总结内容")
    def test_normal_writes_file(self, _mock_q):
        src = Path(self._tmp.name) / "a.txt"
        src.write_text("字幕", encoding="utf-8")
        out = Path(self._tmp.name) / "a.md"

        ok = utils.summarize_subtitles(src, out, print=make_print([]))
        self.assertTrue(ok)
        self.assertEqual(out.read_text(encoding="utf-8"), "# 总结内容")

    @mock.patch.object(utils, "query_llama_server", return_value="半成品")
    def test_stop_does_not_write(self, _mock_q):
        src = Path(self._tmp.name) / "b.txt"
        src.write_text("字幕", encoding="utf-8")
        out = Path(self._tmp.name) / "b.md"
        cfg.stop_requested = True

        ok = utils.summarize_subtitles(src, out, print=make_print([]))
        self.assertFalse(ok)
        self.assertFalse(out.exists())


class TestFindMediaFiles(CfgSnapshotTestCase):

    def test_recursive_and_ext_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.mp4").write_bytes(b"x")
            (root / "note.txt").write_text("x", encoding="utf-8")
            sub = root / "sub"
            sub.mkdir()
            (sub / "b.mp3").write_bytes(b"x")

            files = utils.find_media_files(str(root), print=make_print([]))
            names = sorted(f.name for f in files)
            self.assertEqual(names, ["a.mp4", "b.mp3"])


class TestConfigPersistence(CfgSnapshotTestCase):

    def test_save_load_roundtrip_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            cf = Path(td) / "config.json"
            orig = cfg.text2md_prompt
            try:
                cfg.text2md_prompt = "测试提示词 {text}"
                with mock.patch.object(utils, "config_file", cf):
                    utils.save_config()
                    self.assertTrue(cf.exists())
                    self.assertFalse((Path(td) / "config.json_tmp").exists())

                    cfg.text2md_prompt = "被覆盖"
                    utils.load_config()
                    self.assertEqual(cfg.text2md_prompt, "测试提示词 {text}")
            finally:
                cfg.text2md_prompt = orig

    def test_load_missing_file_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(utils, "config_file", Path(td) / "none.json"):
                utils.load_config()  # 不应抛异常


class TestConfigNames(CfgSnapshotTestCase):

    def test_sampling_params_persisted(self):
        self.assertIn("llm_temperature", utils.config_names)
        self.assertIn("llm_max_tokens", utils.config_names)

    def test_runtime_flag_not_persisted(self):
        self.assertNotIn("stop_requested", utils.config_names)


if __name__ == "__main__":
    unittest.main()
