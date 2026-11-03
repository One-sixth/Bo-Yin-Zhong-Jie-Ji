import sys
# 设置默认的错误处理策略为 'ignore'
if sys.stdin is not None:
    # 关闭控制台后，sys.stdin 等端点为None，不能 reconfigure
    sys.stdin.reconfigure(encoding='utf8', errors='ignore')
    sys.stdout.reconfigure(encoding='utf8', errors='ignore')
    sys.stderr.reconfigure(encoding='utf8', errors='ignore')
# ------------------------------------------------------------
import os, io, datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog,
)
from PySide6.QtCore import QThread, Signal, QTimer, Qt
from PySide6.QtGui import QTextCursor
from qfluentwidgets import (
    FluentWindow, FluentWidget, FluentIcon, Icon, BodyLabel,
    LineEdit, PushButton, CheckBox, PlainTextEdit, TextEdit,
    HeaderCardWidget, PrimaryPushButton, ListWidget, ScrollArea
)
from queue import Queue, Empty
import utils
import config as cfg


# ------------------------------------------------------------
# 工作线程

class WorkerThread(QThread):
    task_start = Signal()
    task_done = Signal()
    task_error = Signal(str)

    """工作线程，用于执行下载、提取字幕、总结等任务"""
    def __init__(self):
        super().__init__()
        self.task_queue = Queue(maxsize=1)
        self.running = True
        self._working = False

    def send_task(self, command):
        """发送任务到工作线程队列"""
        self.task_queue.put(command)

    def run(self):
        while self.running:
            # 从队列中获取任务
            try:
                self.command = self.task_queue.get(block=False)
            except Empty:
                if self._working:
                    self.task_done.emit()
                    self._working = False
                    self.command = None
                self.msleep(300)
                continue

            if not self._working:
                self.task_start.emit()
                self._working = True

            # 函数，功能
            func, args = self.command
            # 新任务开始：清除上次的停止请求（旧任务此时必然已结束：队列 maxsize=1）
            cfg.stop_requested = False
            # 执行任务（异常兜底：防止线程死亡导致 UI 按钮永久禁用）
            try:
                func(*args)
            except Exception:
                import traceback
                self.task_error.emit(f"任务异常中断:\n{traceback.format_exc()}")
            self.msleep(10)

    def stop(self):
        """停止线程"""
        self.running = False


# ------------------------------------------------------------
# 帮助对话框

class HelpDialog(FluentWidget):
    """帮助对话框"""
    def __init__(self, help_text, parent=None):
        super().__init__(parent)
        assert isinstance(help_text, str), "help_text must be a string"

        self.setWindowTitle("帮助")
        self.setWindowIcon(Icon(FluentIcon.HELP))
        self.setGeometry(200, 200, 600, 400)
        self.setResizeEnabled(True)

        layout = QVBoxLayout()

        text_edit = TextEdit()
        text_edit.setHtml(help_text)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)

        layout.setContentsMargins(20, self.titleBar.height() + 10, 20, 20)
        self.setLayout(layout)


# ------------------------------------------------------------
# 主功能区，实现内容的一阶导功能。

class MainInterface(QWidget):
    """主窗口"""

    settings_interface = None  # 由 MainWindow 接线，任务运行时锁定设置页控件

    help_text = """
        <h2>软件使用说明</h2>
        
        <h3>基本功能</h3>
        <ul>
            <li><strong>识别 BV 号</strong>：从输入区域提取 BV 号到下方列表</li>
            <li><strong>下载</strong>：使用 BBDown 下载视频</li>
            <li><strong>提取字幕</strong>：使用 Qwen3-ASR 提取音频为文本</li>
            <li><strong>全自动总结</strong>：启动 llama.cpp 服务器并生成总结</li>
            <li><strong>一键全流程</strong>：执行完整流程（识别→下载→提取→总结）</li>
        </ul>
        
        <h3>配置说明</h3>
        <ul>
            <li><strong>BBDown 路径</strong>：设置 BBDown 可执行文件路径</li>
            <li><strong>Qwen3-ASR 路径</strong>：设置语音识别工具路径</li>
            <li><strong>LLM 模型路径</strong>：设置大语言模型文件路径</li>
            <li><strong>视觉投影层路径</strong>：设置模型视觉投影层路径</li>
            <li><strong>Llama-CPP 服务器路径</strong>：设置服务器可执行文件路径</li>
            <li><strong>端口</strong>：设置服务器端口</li>
            <li><strong>其他参数</strong>：设置服务器其他参数</li>
        </ul>
        
        <h3>使用步骤</h3>
        <ol>
            <li>在左侧输入区域粘贴 B 站链接或其他文本</li>
            <li>点击"识别 BV 号"按钮提取 BV 号</li>
            <li>设置输出目录</li>
            <li>选择是否只下载音频</li>
            <li>点击"一键全流程"按钮开始处理</li>
        </ol>
        
        <h3>注意事项</h3>
        <ul>
            <li>确保所有路径配置正确</li>
            <li>下载视频需要稳定的网络连接</li>
            <li>总结功能需要足够的内存和 GPU 资源</li>
        </ul>
        """

    def __init__(self):
        super().__init__()
        self.setObjectName("MainInterface")
        self.resize(1200, 800)

        # 日志流
        self.log_stream = io.StringIO()

        # 初始化UI布局
        self.init_ui()

        # 启动日志更新定时器
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.update_log)
        self.log_timer.start(300)

        # 启动工作线程
        self.worker_thread = WorkerThread()
        self.worker_thread.task_start.connect(self.disbale_all_button)
        self.worker_thread.task_done.connect(self.enable_all_button)
        self.worker_thread.task_error.connect(self.print)
        self.worker_thread.start()

    def init_ui(self):
        # 主布局
        main_layout = QHBoxLayout()

        # 左侧区域
        left_layout = QVBoxLayout()

        # 左1区域：输入区
        input_card = HeaderCardWidget("输入区")
        input_layout = QVBoxLayout()

        # 上面的多行文本框：输入各种文本和链接
        self.input_text = TextEdit()
        self.input_text.setPlaceholderText("请在此输入 B 站链接或其他文本...")
        input_layout.addWidget(BodyLabel("输入文本/链接："))
        input_layout.addWidget(self.input_text)

        # 下面的多行文本框：显示提取出来的 BV 号
        self.bv_list_text = PlainTextEdit()
        self.bv_list_text.setReadOnly(True)
        self.bv_list_text.setPlaceholderText("识别到的 BV 号将显示在这里...")
        input_layout.addWidget(BodyLabel("识别到的 BV 号："))
        input_layout.addWidget(self.bv_list_text)

        input_card.viewLayout.addLayout(input_layout)
        left_layout.addWidget(input_card)


        # 右侧区域
        right_layout = QVBoxLayout()

        # 右1区域：操作区
        operation_card = HeaderCardWidget("操作区")
        operation_layout = QVBoxLayout()


        # 输入输出文件夹
        folder_layout = QHBoxLayout()
        self.input_output_folder_edit = LineEdit()
        self.input_output_folder_edit.setPlaceholderText("输入输出文件夹...")
        self.input_output_folder_edit.textChanged.connect(self.on_input_output_folder_edit_changed)
        self.input_output_folder_button = PushButton("浏览")
        self.input_output_folder_button.clicked.connect(lambda: self.select_folder("输入输出文件夹", self.input_output_folder_edit))

        folder_layout.addWidget(BodyLabel("输入输出文件夹："))
        folder_layout.addWidget(self.input_output_folder_edit)
        folder_layout.addWidget(self.input_output_folder_button)

        operation_layout.addLayout(folder_layout)

        # 按钮区域
        buttons_layout = QVBoxLayout()

        self.check_env_button = PushButton(Icon(FluentIcon.LIBRARY), "检查环境")
        self.check_env_button.clicked.connect(self.check_environment)

        self.recognize_bv_button = PushButton(Icon(FluentIcon.FILTER), "识别 BV 号")
        self.recognize_bv_button.clicked.connect(self.recognize_bv_ids)

        self.download_button = PushButton(Icon(FluentIcon.DOWNLOAD), "下载音视频")
        self.download_button.clicked.connect(self.download_videos_entry)

        self.extract_subtitle_button = PushButton(Icon(FluentIcon.CHAT), "提取字幕")
        self.extract_subtitle_button.clicked.connect(self.extract_subtitles_entry)

        self.summarize_button = PushButton(Icon(FluentIcon.CLOUD), "自动总结")
        self.summarize_button.clicked.connect(self.auto_summarize_entry)

        self.full_process_button = PrimaryPushButton("🚀一键全流程")
        self.full_process_button.clicked.connect(self.full_process_entry)

        # 停止任务按钮（任务运行时保持可点，不在禁用列表中）
        self.stop_button = PushButton(Icon(FluentIcon.CLOSE), "停止任务")
        self.stop_button.clicked.connect(self.stop_tasks)

        # 只下载音频复选框
        self.bbdown_audio_only_checkbox = CheckBox("只下载音频")
        self.bbdown_audio_only_checkbox.toggled.connect(lambda checked: setattr(cfg, 'bbdown_only_audio', bool(checked)))

        # 帮助按钮
        self.help_button = PushButton(Icon(FluentIcon.HELP), "帮助")
        self.help_button.clicked.connect(self.show_help)
        self.help_dialog = HelpDialog(help_text=self.help_text)

        buttons_layout.addWidget(self.check_env_button)
        buttons_layout.addWidget(self.recognize_bv_button)
        buttons_layout.addWidget(self.download_button)
        buttons_layout.addWidget(self.extract_subtitle_button)
        buttons_layout.addWidget(self.summarize_button)
        buttons_layout.addWidget(self.full_process_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.bbdown_audio_only_checkbox)
        buttons_layout.addWidget(self.help_button)

        operation_layout.addLayout(buttons_layout)

        operation_card.viewLayout.addLayout(operation_layout)
        right_layout.addWidget(operation_card)

        # 右2区域：日志区
        log_card = HeaderCardWidget("日志区")
        log_layout = QVBoxLayout()
        self.log_text = PlainTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_card.viewLayout.addLayout(log_layout)
        right_layout.addWidget(log_card)

        # 组装左布局和右布局
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 2)

        self.setLayout(main_layout)

    # --------------------------------------------------------------------

    def load_config(self):
        """加载配置"""
        self.input_output_folder_edit.setText(cfg.input_output_dir)

    # --------------------------------------------------------------------

    def stop_tasks(self):
        """请求停止当前运行中的任务"""
        if not self.worker_thread._working:
            self.print("当前没有运行中的任务")
            return
        cfg.stop_requested = True
        self.print("已请求停止任务，正在终止子进程...")
        utils.stop_all_tasks(print=self.print)

    def disbale_all_button(self):
        """禁用所有按钮"""
        if self.settings_interface:
            self.settings_interface.disbale_all_button()
        self.input_output_folder_edit.setEnabled(False)
        self.input_output_folder_button.setEnabled(False)
        self.check_env_button.setEnabled(False)
        self.recognize_bv_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.extract_subtitle_button.setEnabled(False)
        self.summarize_button.setEnabled(False)
        self.full_process_button.setEnabled(False)
        self.bbdown_audio_only_checkbox.setEnabled(False)

    def enable_all_button(self):
        """启用所有按钮"""
        if self.settings_interface:
            self.settings_interface.enable_all_button()
        self.input_output_folder_edit.setEnabled(True)
        self.input_output_folder_button.setEnabled(True)
        self.check_env_button.setEnabled(True)
        self.recognize_bv_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self.extract_subtitle_button.setEnabled(True)
        self.summarize_button.setEnabled(True)
        self.full_process_button.setEnabled(True)
        self.bbdown_audio_only_checkbox.setEnabled(True)

    def select_file(self, title, line_edit):
        """选择文件"""
        file_path, _ = QFileDialog.getOpenFileName(self, title)
        if file_path:
            line_edit.setText(file_path)

    def select_folder(self, title, line_edit):
        """选择文件夹"""
        folder_path = QFileDialog.getExistingDirectory(self, title)
        if folder_path:
            line_edit.setText(folder_path)

    # --------------------------------------------------------------------

    def check_environment(self) -> bool:
        """检查环境"""
        self.print("开始检查环境...")

        # 更新配置
        utils.print_config(print=self.print)

        is_ok = True

        # 检查 提示词
        if '{text}' in cfg.text2md_prompt:
            self.print("提示词 可用")
        else:
            self.print("提示词中必须包含 {text} 占位符")
            is_ok = False

        # 检查 BBDown
        if utils.check_bbdown_exe(print=self.print):
            self.print("BBDown 可用")
        else:
            self.print("BBDown 不存在或不可用")
            is_ok = False

        # 检查 qwen3-asr 程序是否可用
        if utils.check_qwen3_asr_exe(print=self.print):
            self.print("qwen3-asr 可用")
        else:
            self.print("qwen3-asr 不存在或不可用")
            is_ok = False

        if cfg.use_remote_llama_server:
            # 检查远程 Llama-CPP 服务器
            self.print(f"使用远程 llama-server: {cfg.remote_llama_server_address}")
            if utils.check_remote_llama_cpp_address(print=self.print):
                self.print("远程 llama-server 可用")
            else:
                self.print("远程 llama-server 不可用")
                is_ok = False

        else:
            # 检查 LLM 模型文件
            if os.path.exists(cfg.llm_gguf_file):
                self.print(f"LLM 模型文件存在: {cfg.llm_gguf_file}")
            else:
                self.print(f"LLM 模型文件不存在: {cfg.llm_gguf_file}")
                is_ok = False

            if utils.check_llama_cpp_exe(print=self.print):
                self.print("Llama-CPP 服务器可用")
            else:
                self.print("Llama-CPP 服务器不可用")
                is_ok = False

        self.print("环境检查完成！")
        return is_ok

    # --------------------------------------------------------------------

    def recognize_bv_ids(self):
        """识别 BV 号"""
        input_text = self.input_text.toPlainText()
        if not input_text:
            self.print("警告！识别BV号前，请先在左上输入区域输入链接")
            return

        bv_ids = utils.recognize_bv_ids(input_text, print=self.print)
        if not bv_ids:
            self.print("未识别到 BV 号")
            return

        # 显示到 BV 号列表
        self.bv_list_text.clear()
        for bv_id in bv_ids:
            self.bv_list_text.appendPlainText(bv_id)

        self.print(f"识别到 {len(bv_ids)} 个 BV 号")

    # --------------------------------------------------------------------

    def download_videos_entry(self):
        """下载视频入口"""
        self.worker_thread.send_task([self.download_videos, []])

    def download_videos(self):
        """下载视频"""

        bv_list_text = self.bv_list_text.toPlainText()
        if not bv_list_text:
            self.print('警告！BV号列表为空')
            return

        if not cfg.input_output_dir:
            self.print('警告！请选择输出目录')
            return

        # 提取 BV 号列表
        bv_ids = [line.strip() for line in bv_list_text.split('\n') if line.strip()]
        if not bv_ids:
            self.print('警告！BV 号列表为空')
            return

        # 检查 BBDown 是否可用
        if not utils.check_bbdown_exe(print=self.print):
            self.print('错误！BBDown 不可用，请检查路径设置')
            return

        # 开始下载
        self.print(f"开始下载 {len(bv_ids)} 个视频")
        for bv_id in bv_ids:
            if cfg.stop_requested:
                self.print("任务已停止")
                return
            self.print(f"下载 BV{bv_id}")
            success = utils.download_video(bv_id, cfg.input_output_dir, cfg.bbdown_only_audio, print=self.print)
            if success:
                self.print(f"下载成功: BV{bv_id}")
            elif cfg.stop_requested:
                self.print(f"已停止: BV{bv_id}")
            else:
                self.print(f"下载失败: BV{bv_id}")

        self.print("下载完成！")

    # --------------------------------------------------------------------

    def extract_subtitles_entry(self):
        """提取字幕入口"""
        self.worker_thread.send_task([self.extract_subtitles, []])

    def extract_subtitles(self):
        """提取字幕"""

        if not cfg.input_output_dir:
            self.print('警告！请选择输入目录')
            return

        # 查找媒体文件
        media_files = utils.find_media_files(cfg.input_output_dir, print=self.print)
        if not media_files:
            self.print('警告！未找到媒体文件')
            return

        # 检查 Qwen3-ASR 是否可用
        if not utils.check_qwen3_asr_exe(print=self.print):
            self.print('错误！Qwen3-ASR 路径不存在或不可用')
            return

        # 提取字幕
        self.print(f"开始提取 {len(media_files)} 个媒体文件的字幕")
        for media_file in media_files:
            if cfg.stop_requested:
                self.print("任务已停止")
                return

            out_file_pre: Path = media_file.with_suffix('.txt')
            if out_file_pre.exists():
                self.print(f"跳过已存在字幕文件: {out_file_pre}")
                continue

            self.print(f"提取 {media_file}")
            success, out_file = utils.convert_to_subtitle(media_file, print=self.print)
            if success:
                self.print(f"提取成功: {out_file}")
            else:
                self.print(f"提取失败: {media_file}")

        self.print("提取字幕完成！")

    # --------------------------------------------------------------------

    def auto_summarize_entry(self):
        """提取字幕入口"""
        self.worker_thread.send_task([self.auto_summarize, []])

    def auto_summarize(self):
        """自动总结"""

        if not cfg.input_output_dir:
            self.print('警告！请选择输入目录')
            return

        # 检查 提示词
        if '{text}' not in cfg.text2md_prompt:
            self.print("提示词中必须包含 {text} 占位符")
            return

        # 查找文本文件
        text_files = []
        for root, _, files in os.walk(cfg.input_output_dir):
            for file in files:
                if file.endswith('.txt'):
                    text_files.append(Path(os.path.join(root, file)))

        if not text_files:
            self.print("未找到文本文件")
            return

        # 启动 llama.cpp 服务器
        if not cfg.use_remote_llama_server:
            self.print("启动 llama.cpp 服务器...")
            if not utils.start_llama_server(print=self.print):
                self.print("错误！服务器启动失败")
                return
        else:
            self.print(f"使用远程 llama-server: {cfg.remote_llama_server_address}")

        # 生成总结
        self.print(f"开始生成 {len(text_files)} 个文本文件的总结")
        for text_file in text_files:
            if cfg.stop_requested:
                self.print("任务已停止")
                break

            output_file: Path = text_file.with_suffix('.md')
            output_file_tmp: Path = text_file.with_suffix('.md_tmp')

            if output_file.exists():
                self.print(f"跳过已存在的总结: {output_file}")
                continue

            if text_file.stat().st_size == 0:
                self.print(f"{text_file} 的转录为空，疑似无人声的音频。跳过该文件的 LLM 总结")
                continue

            self.print(f"处理 {text_file}")
            is_ok = utils.summarize_subtitles(text_file, output_file_tmp, prompt=cfg.text2md_prompt, print=self.print)
            if not is_ok:
                break
            output_file_tmp.replace(output_file)

        # 停止服务器
        if not cfg.use_remote_llama_server:
            utils.stop_llama_server(print=self.print)
            self.print("服务器已停止")
        self.print("任务已停止！" if cfg.stop_requested else "总结完成！")

    # --------------------------------------------------------------------

    def full_process_entry(self):
        """一键全流程入口"""
        self.worker_thread.send_task([self.full_process, []])

    def full_process(self):
        """一键全流程"""
        # 0. 检查环境
        is_ok = self.check_environment()
        if not is_ok:
            self.print('环境存在问题，需要检查')
            return

        # 1. 识别 BV 号
        self.recognize_bv_ids()

        # 2. 下载视频
        self.download_videos()
        if cfg.stop_requested:
            self.print("全流程已停止")
            return

        # 3. 提取字幕
        self.extract_subtitles()
        if cfg.stop_requested:
            self.print("全流程已停止")
            return

        # 4. 全自动总结
        self.auto_summarize()
        if cfg.stop_requested:
            self.print("全流程已停止")
            return

        self.print("全流程完成！")

    def show_help(self):
        """显示帮助对话框"""
        self.help_dialog.show()
        self.help_dialog.activateWindow()

    # --------------------------------------------------------------------

    def update_log(self):
        """更新日志框"""
        content = self.log_stream.getvalue()
        if content:
            # 清空日志流
            self.log_stream.seek(0)
            self.log_stream.truncate(0)
            # 更新日志
            self.log_text.moveCursor(QTextCursor.MoveOperation.End)
            self.log_text.insertPlainText(content)
            self.log_text.ensureCursorVisible()

    def print(self, *values: object, sep: str = " ", end: str = "\n", file = None, flush = False):
        self.log_stream.write(sep.join([str(v) for v in values]) + end)
        print(*values, sep=sep, end=end, file=file, flush=flush)

    # --------------------------------------------------------------------
    # 设定更新事件

    def on_input_output_folder_edit_changed(self, text: str):
        """输入目录改变时更新配置"""
        cfg.input_output_dir = text

    # --------------------------------------------------------------------

    def closeEvent(self, event):
        """窗口关闭事件"""

        # 停止 视频下载 进程
        utils.stop_download_video(print=self.print)
        # 停止 qwen3-asr 进程
        utils.stop_qwen3_asr(print=self.print)
        # 停止llama 服务器
        utils.stop_llama_server(print=self.print)

        cfg.stop_requested = True
        if self.worker_thread:
            self.worker_thread.stop()
            self.worker_thread.wait(5000)

        # 停止日志线程
        self.log_timer.stop()

        event.accept()

    # --------------------------------------------------------------------


class SettingsInterface(ScrollArea):
    """设置界面：程序与模型路径、远程 llama-server、提示词"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_config()

    def init_ui(self):
        """初始化界面（滚动容器 + 三张设置卡）"""
        self.scroll_widget = QWidget()
        self.expandLayout = QVBoxLayout(self.scroll_widget)
        self.expandLayout.setContentsMargins(24, 24, 24, 24)
        self.expandLayout.setSpacing(12)

        # 卡1：程序与模型路径
        path_card = HeaderCardWidget("程序与模型路径")
        path_layout = QGridLayout()

        row = 0
        path_layout.addWidget(BodyLabel("BBDown 路径："), row, 0)
        self.bbdown_edit = LineEdit()
        self.bbdown_edit.textChanged.connect(self.on_bbdown_edit_changed)
        self.bbdown_button = PushButton("浏览")
        self.bbdown_button.clicked.connect(lambda: self.select_file("BBDown 可执行文件", self.bbdown_edit))
        path_layout.addWidget(self.bbdown_edit, row, 1)
        path_layout.addWidget(self.bbdown_button, row, 2)

        row = 1
        path_layout.addWidget(BodyLabel("BBDown其他参数："), row, 0)
        self.bbdown_other_args_edit = LineEdit()
        self.bbdown_other_args_edit.textChanged.connect(self.on_bbdown_other_args_edit_changed)
        path_layout.addWidget(self.bbdown_other_args_edit, row, 1, 1, 2)

        row = 2
        path_layout.addWidget(BodyLabel("Qwen3-ASR路径："), row, 0)
        self.qwen3_asr_edit = LineEdit()
        self.qwen3_asr_edit.textChanged.connect(self.on_qwen3_asr_edit_changed)
        self.qwen3_asr_button = PushButton("浏览")
        self.qwen3_asr_button.clicked.connect(lambda: self.select_file("Qwen3-ASR 可执行文件", self.qwen3_asr_edit))
        path_layout.addWidget(self.qwen3_asr_edit, row, 1)
        path_layout.addWidget(self.qwen3_asr_button, row, 2)

        row = 3
        path_layout.addWidget(BodyLabel("Qwen3-ASR其他参数："), row, 0)
        self.qwen3_asr_other_args_edit = LineEdit()
        self.qwen3_asr_other_args_edit.textChanged.connect(self.on_qwen3_asr_other_args_edit_changed)
        path_layout.addWidget(self.qwen3_asr_other_args_edit, row, 1, 1, 2)

        row = 4
        path_layout.addWidget(BodyLabel("LLM 模型路径："), row, 0)
        self.llm_gguf_edit = LineEdit()
        self.llm_gguf_edit.textChanged.connect(self.on_llm_gguf_edit_changed)
        self.llm_gguf_button = PushButton("浏览")
        self.llm_gguf_button.clicked.connect(lambda: self.select_file("LLM 模型文件", self.llm_gguf_edit))
        path_layout.addWidget(self.llm_gguf_edit, row, 1)
        path_layout.addWidget(self.llm_gguf_button, row, 2)

        row = 5
        path_layout.addWidget(BodyLabel("Llama-CPP 服务器路径："), row, 0)
        self.llama_cpp_edit = LineEdit()
        self.llama_cpp_edit.textChanged.connect(self.on_llama_cpp_edit_changed)
        self.llama_cpp_button = PushButton("浏览")
        self.llama_cpp_button.clicked.connect(lambda: self.select_file("Llama-CPP 服务器可执行文件", self.llama_cpp_edit))
        path_layout.addWidget(self.llama_cpp_edit, row, 1)
        path_layout.addWidget(self.llama_cpp_button, row, 2)

        row = 6
        path_layout.addWidget(BodyLabel("Llama服务端口："), row, 0)
        self.llama_cpp_port_edit = LineEdit()
        self.llama_cpp_port_edit.textChanged.connect(self.on_llama_cpp_port_edit_changed)
        path_layout.addWidget(self.llama_cpp_port_edit, row, 1)

        row = 7
        path_layout.addWidget(BodyLabel("Llama服务其他参数："), row, 0)
        self.llama_cpp_other_args_edit = LineEdit()
        self.llama_cpp_other_args_edit.textChanged.connect(self.on_llama_cpp_other_args_edit_changed)
        path_layout.addWidget(self.llama_cpp_other_args_edit, row, 1, 1, 2)

        path_card.viewLayout.addLayout(path_layout)
        self.expandLayout.addWidget(path_card)

        # 卡2：远程 llama-server
        remote_card = HeaderCardWidget("远程 llama-server")
        remote_layout = QGridLayout()

        row = 0
        self.use_remote_llama_server_checkbox = CheckBox("使用远程llama-server")
        self.use_remote_llama_server_checkbox.toggled.connect(self.on_use_remote_llama_server_checkbox_toggled)
        remote_layout.addWidget(self.use_remote_llama_server_checkbox, row, 0, 1, 2)

        row = 1
        remote_layout.addWidget(BodyLabel("远程llama-server地址："), row, 0)
        self.remote_llama_server_address_edit = LineEdit()
        self.remote_llama_server_address_edit.setPlaceholderText("http://192.168.1.100:45124")
        self.remote_llama_server_address_edit.textChanged.connect(self.on_remote_llama_server_address_edit_changed)
        remote_layout.addWidget(self.remote_llama_server_address_edit, row, 1)

        row = 2
        remote_layout.addWidget(BodyLabel("远程llama-server密钥："), row, 0)
        self.remote_llama_server_key_edit = LineEdit()
        self.remote_llama_server_key_edit.setPlaceholderText("留空则无需密钥")
        self.remote_llama_server_key_edit.textChanged.connect(self.on_remote_llama_server_key_edit_changed)
        remote_layout.addWidget(self.remote_llama_server_key_edit, row, 1)

        remote_card.viewLayout.addLayout(remote_layout)
        self.expandLayout.addWidget(remote_card)

        # 卡3：提示词（多行编辑框：标签+按钮一行，编辑框占下一行）
        prompt_card = HeaderCardWidget("提示词")
        prompt_layout = QVBoxLayout()

        text2md_row = QHBoxLayout()
        text2md_row.addWidget(BodyLabel("字幕总结提示词："))
        text2md_row.addStretch(1)
        self.text2md_prompt_button = PushButton("恢复默认")
        self.text2md_prompt_button.clicked.connect(lambda: self.reset_text2md_prompt())
        text2md_row.addWidget(self.text2md_prompt_button)
        prompt_layout.addLayout(text2md_row)

        self.text2md_prompt_edit = PlainTextEdit()
        self.text2md_prompt_edit.setFixedHeight(96)
        self.text2md_prompt_edit.textChanged.connect(self.on_text2md_prompt_edit_changed)
        prompt_layout.addWidget(self.text2md_prompt_edit)

        prompt_layout.addSpacing(8)

        summary_row = QHBoxLayout()
        summary_row.addWidget(BodyLabel("二次总结提示词："))
        summary_row.addStretch(1)
        self.summary_prompt_button = PushButton("恢复默认")
        self.summary_prompt_button.clicked.connect(lambda: self.reset_summary_prompt())
        summary_row.addWidget(self.summary_prompt_button)
        prompt_layout.addLayout(summary_row)

        self.summary_prompt_edit = PlainTextEdit()
        self.summary_prompt_edit.setFixedHeight(96)
        self.summary_prompt_edit.setPlaceholderText("请输入二次总结的提示词，必须包含 {text} 字段...")
        self.summary_prompt_edit.textChanged.connect(self.on_summary_prompt_edit_changed)
        prompt_layout.addWidget(self.summary_prompt_edit)

        prompt_card.viewLayout.addLayout(prompt_layout)
        self.expandLayout.addWidget(prompt_card)

        self.expandLayout.addStretch(1)

        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)
        self.setObjectName('settingsInterface')
        self.scroll_widget.setObjectName('settingsScrollWidget')
        self.setStyleSheet(
            "QScrollArea, #settingsScrollWidget { background: transparent; border: none; }"
        )

    def _all_setting_widgets(self):
        """全部设置控件"""
        return (
            self.bbdown_edit, self.bbdown_button, self.bbdown_other_args_edit,
            self.qwen3_asr_edit, self.qwen3_asr_button, self.qwen3_asr_other_args_edit,
            self.llm_gguf_edit, self.llm_gguf_button,
            self.llama_cpp_edit, self.llama_cpp_button, self.llama_cpp_port_edit,
            self.llama_cpp_other_args_edit,
            self.use_remote_llama_server_checkbox,
            self.remote_llama_server_address_edit, self.remote_llama_server_key_edit,
            self.text2md_prompt_edit, self.text2md_prompt_button,
            self.summary_prompt_edit, self.summary_prompt_button,
        )

    def load_config(self):
        """加载配置"""
        self.text2md_prompt_edit.setPlainText(cfg.text2md_prompt)
        self.bbdown_edit.setText(cfg.bbdown_exe)
        self.bbdown_other_args_edit.setText(' '.join(cfg.bbdown_other_args))
        self.qwen3_asr_edit.setText(cfg.qwen3_asr_exe)
        self.qwen3_asr_other_args_edit.setText(' '.join(cfg.qwen3_asr_other_args))
        self.llm_gguf_edit.setText(cfg.llm_gguf_file)
        self.llama_cpp_edit.setText(cfg.llama_cpp_server)
        self.llama_cpp_port_edit.setText(str(cfg.llama_cpp_port))
        self.llama_cpp_other_args_edit.setText(' '.join(cfg.llama_cpp_other_args))
        self.use_remote_llama_server_checkbox.setCheckState(Qt.Checked if cfg.use_remote_llama_server else Qt.Unchecked)
        self.remote_llama_server_address_edit.setText(cfg.remote_llama_server_address)
        self.remote_llama_server_address_edit.setEnabled(cfg.use_remote_llama_server)
        self.remote_llama_server_key_edit.setText(cfg.remote_llama_server_key)
        self.remote_llama_server_key_edit.setEnabled(cfg.use_remote_llama_server)
        self.summary_prompt_edit.setPlainText(cfg.summary_prompt)

    def disbale_all_button(self):
        """禁用所有设置控件（任务运行时锁定）"""
        for w in self._all_setting_widgets():
            w.setEnabled(False)

    def enable_all_button(self):
        """启用所有设置控件"""
        for w in self._all_setting_widgets():
            w.setEnabled(True)
        # 远程地址/密钥按配置恢复启用状态
        remote_enabled = cfg.use_remote_llama_server
        self.remote_llama_server_address_edit.setEnabled(remote_enabled)
        self.remote_llama_server_key_edit.setEnabled(remote_enabled)

    def select_file(self, title, line_edit):
        """选择文件"""
        file_path, _ = QFileDialog.getOpenFileName(self, title)
        if file_path:
            line_edit.setText(file_path)

    # --------------------------------------------------------------------
    # 设定更新事件

    def on_text2md_prompt_edit_changed(self):
        """字幕总结提示词改变时更新配置"""
        cfg.text2md_prompt = self.text2md_prompt_edit.toPlainText()

    def reset_text2md_prompt(self):
        """字幕总结提示词重置"""
        self.text2md_prompt_edit.setPlainText(cfg._default_text2md_prompt)

    def on_bbdown_edit_changed(self, text: str):
        """bbdown 改变时更新配置"""
        cfg.bbdown_exe = text

    def on_bbdown_other_args_edit_changed(self, text: str):
        """bbdown 其他参数改变时更新配置"""
        cfg.bbdown_other_args = text.split()

    def on_qwen3_asr_edit_changed(self, text: str):
        """qwen3-asr 改变时更新配置"""
        cfg.qwen3_asr_exe = text

    def on_qwen3_asr_other_args_edit_changed(self, text: str):
        """qwen3-asr 其他参数改变时更新配置"""
        cfg.qwen3_asr_other_args = text.split()

    def on_llm_gguf_edit_changed(self, text: str):
        """llm gguf 文件改变时更新配置"""
        cfg.llm_gguf_file = text

    def on_llama_cpp_edit_changed(self, text: str):
        """llama.cpp 服务器改变时更新配置"""
        cfg.llama_cpp_server = text

    def on_llama_cpp_port_edit_changed(self, text: str):
        """llama.cpp 服务器端口改变时更新配置"""
        if not text.strip():
            return
        try:
            cfg.llama_cpp_port = int(text)
        except ValueError:
            pass

    def on_llama_cpp_other_args_edit_changed(self, text: str):
        """llama.cpp 其他参数改变时更新配置"""
        cfg.llama_cpp_other_args = text.split()

    def on_use_remote_llama_server_checkbox_toggled(self, checked: bool):
        """使用远程llama-server复选框改变时更新配置"""
        cfg.use_remote_llama_server = bool(checked)
        self.remote_llama_server_address_edit.setEnabled(bool(checked))
        self.remote_llama_server_key_edit.setEnabled(bool(checked))

    def on_remote_llama_server_address_edit_changed(self, text: str):
        """远程llama-server地址改变时更新配置"""
        cfg.remote_llama_server_address = text

    def on_remote_llama_server_key_edit_changed(self, text: str):
        """远程llama-server密钥改变时更新配置"""
        cfg.remote_llama_server_key = text

    def on_summary_prompt_edit_changed(self):
        """更新二次总结提示词"""
        cfg.summary_prompt = self.summary_prompt_edit.toPlainText()

    def reset_summary_prompt(self):
        """恢复默认二次总结提示词"""
        self.summary_prompt_edit.setPlainText(cfg._default_summary_prompt)



# ------------------------------------------------------------
# 次功能区，实现内容的二阶导功能。

class SummaryInterface(QWidget):
    """总结界面：合并和总结 MD 文件"""

    settings_interface = None  # 由 MainWindow 接线，任务运行时锁定设置页控件

    help_text = f"""
    <h2>MD 文件合并与总结工具</h2>

    <h3>使用步骤</h3>
    <ol>
        <li>在"文件夹选区"添加包含 MD 文件的文件夹</li>
        <li>点击"从文件夹中寻找md文件"按钮，自动扫描并添加 MD 文件到"文件选择区"</li>
        <li>或直接在"文件选择区"手动添加 MD 文件</li>
        <li>在"功能区"修改提示词（必须包含 {{text}} 字段）</li>
        <li>点击"开始总结"按钮，系统会：
            <ul>
                <li>读取文件选区所有的 MD 文件</li>
                <li>合并成一个大文档</li>
                <li>发送到 AI 进行去重复和总结</li>
                <li>保存总结结果为 all.md 文件</li>
                <li>保存总结结果在 文件夹 {cfg.project_root / 'sum_output'}</li>
            </ul>
        </li>
    </ol>

    <h3>操作说明</h3>
    <ul>
        <li><strong>+ 按钮</strong>：添加文件夹或文件</li>
        <li><strong>- 按钮</strong>：移除选中的文件夹或文件</li>
        <li><strong>撤销按钮</strong>：恢复最近移除的项目</li>
        <li><strong>清空按钮</strong>：清空列表</li>
    </ul>
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("SummaryInterface")

        # 日志流
        self.log_stream = io.StringIO()

        self.init_ui()

        # 启动日志更新定时器
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.update_log)
        self.log_timer.start(300)

        # 用于撤销操作的历史记录
        self.folder_removed_items = []
        self.file_removed_items = []

        self.worker_thread = WorkerThread()
        self.worker_thread.task_start.connect(self.disable_all_buttons)
        self.worker_thread.task_done.connect(self.enable_all_buttons)
        self.worker_thread.task_error.connect(self.print)
        self.worker_thread.start()

    def init_ui(self):
        """初始化界面"""
        main_layout = QHBoxLayout()

        # 左区
        left_layout = QVBoxLayout()

        # 左区上部分：文件夹选区
        folder_card = HeaderCardWidget('文件夹选区')
        folder_layout = QVBoxLayout()

        # 文件夹列表框
        self.folder_list = ListWidget()
        self.folder_list.setSelectionMode(ListWidget.ExtendedSelection)
        folder_layout.addWidget(self.folder_list)

        # 文件夹操作按钮
        folder_buttons_layout = QHBoxLayout()
        self.add_folder_button = PushButton("+")
        self.add_folder_button.setFixedWidth(40)
        self.add_folder_button.clicked.connect(self.add_folders)

        self.remove_folder_button = PushButton("-")
        self.remove_folder_button.setFixedWidth(40)
        self.remove_folder_button.clicked.connect(self.remove_folders)

        self.undo_folder_button = PushButton("撤销")
        self.undo_folder_button.clicked.connect(self.undo_remove_folders)

        self.clear_folder_button = PushButton("清空")
        self.clear_folder_button.clicked.connect(self.clear_folders)

        folder_buttons_layout.addWidget(self.add_folder_button)
        folder_buttons_layout.addWidget(self.remove_folder_button)
        folder_buttons_layout.addWidget(self.undo_folder_button)
        folder_buttons_layout.addWidget(self.clear_folder_button)

        folder_layout.addLayout(folder_buttons_layout)

        self.find_md_button = PushButton("从 文件夹选区 寻找MD文件 导入 文件选区")
        self.find_md_button.clicked.connect(self.find_md_files)
        folder_layout.addWidget(self.find_md_button)

        folder_card.viewLayout.addLayout(folder_layout)
        left_layout.addWidget(folder_card)

        # 左区下部分：文件选择区
        file_card = HeaderCardWidget('文件选区')
        file_layout = QVBoxLayout()

        # 文件列表框
        self.file_list = ListWidget()
        self.file_list.setSelectionMode(ListWidget.ExtendedSelection)
        file_layout.addWidget(self.file_list)

        # 文件操作按钮
        file_buttons_layout = QHBoxLayout()
        self.add_file_button = PushButton("+")
        self.add_file_button.setFixedWidth(40)
        self.add_file_button.clicked.connect(self.add_files)

        self.remove_file_button = PushButton("-")
        self.remove_file_button.setFixedWidth(40)
        self.remove_file_button.clicked.connect(self.remove_files)

        self.undo_file_button = PushButton("撤销")
        self.undo_file_button.clicked.connect(self.undo_remove_files)

        self.clear_file_button = PushButton("清空")
        self.clear_file_button.clicked.connect(self.clear_files)

        file_buttons_layout.addWidget(self.add_file_button)
        file_buttons_layout.addWidget(self.remove_file_button)
        file_buttons_layout.addWidget(self.undo_file_button)
        file_buttons_layout.addWidget(self.clear_file_button)

        file_layout.addLayout(file_buttons_layout)
        file_card.viewLayout.addLayout(file_layout)
        left_layout.addWidget(file_card)

        # 右区
        right_layout = QVBoxLayout()

        # 右区上部分：功能区
        function_card = HeaderCardWidget('功能区')
        function_layout = QVBoxLayout()


        # 功能按钮
        function_buttons_layout = QVBoxLayout()

        self.start_summary_button = PrimaryPushButton("开始二次总结")
        self.start_summary_button.clicked.connect(self.start_summary_entry)

        # 停止任务按钮
        self.stop_button = PushButton("停止任务")
        self.stop_button.clicked.connect(self.stop_tasks)

        self.help_button = PushButton("帮助")
        self.help_button.clicked.connect(self.show_help)
        self.help_dialog = HelpDialog(help_text=self.help_text)

        function_buttons_layout.addWidget(self.start_summary_button)
        function_buttons_layout.addWidget(self.stop_button)
        function_buttons_layout.addWidget(self.help_button)

        function_layout.addLayout(function_buttons_layout)
        function_card.viewLayout.addLayout(function_layout)
        right_layout.addWidget(function_card)

        # 右区下部分：日志区
        log_card = HeaderCardWidget('日志区')
        log_layout = QVBoxLayout()

        self.log_text = PlainTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        log_card.viewLayout.addLayout(log_layout)
        right_layout.addWidget(log_card)

        # 组装主布局
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 1)

        self.setLayout(main_layout)

    # --------------------------------------------------------------------

    def stop_tasks(self):
        """请求停止当前运行中的任务"""
        if not self.worker_thread._working:
            self.print("当前没有运行中的任务")
            return
        cfg.stop_requested = True
        self.print("已请求停止任务...")

    def disable_all_buttons(self):
        """禁用所有按钮"""
        if self.settings_interface:
            self.settings_interface.disbale_all_button()
        self.start_summary_button.setEnabled(False)

    def enable_all_buttons(self):
        """启用所有按钮"""
        if self.settings_interface:
            self.settings_interface.enable_all_button()
        self.start_summary_button.setEnabled(True)

    # --------------------------------------------------------------------

    # 文件夹操作方法
    def add_folders(self):
        """添加文件夹"""
        folders = QFileDialog.getExistingDirectory(self, "选择文件夹", options=QFileDialog.DontUseNativeDialog)
        if folders:
            # 检查是否已存在
            existing_folders = [self.folder_list.item(i).text() for i in range(self.folder_list.count())]
            if folders not in existing_folders:
                self.folder_list.addItem(folders)
                self.print(f"添加文件夹: {folders}")
            else:
                self.print(f"文件夹已存在: {folders}")

    def remove_folders(self):
        """移除选中的文件夹"""
        selected_items = self.folder_list.selectedItems()
        if selected_items:
            removed = []
            for item in selected_items:
                removed.append(item.text())
                self.folder_list.takeItem(self.folder_list.row(item))
            self.folder_removed_items.extend(removed)
            self.print(f"移除文件夹: {', '.join(removed)}")

    def undo_remove_folders(self):
        """撤销移除文件夹"""
        if self.folder_removed_items:
            folder = self.folder_removed_items.pop()
            # 检查是否已存在
            existing_folders = [self.folder_list.item(i).text() for i in range(self.folder_list.count())]
            if folder not in existing_folders:
                self.folder_list.addItem(folder)
                self.print(f"恢复文件夹: {folder}")

    def clear_folders(self):
        """清空文件夹列表"""
        self.folder_removed_items.clear()
        self.folder_list.clear()
        self.print("清空文件夹列表")

    # 文件操作方法
    def add_files(self):
        """添加文件"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择MD文件", filter="Markdown Files (*.md)")
        if files:
            # 检查是否已存在
            existing_files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
            for file in files:
                if file not in existing_files:
                    self.file_list.addItem(file)
                    self.print(f"添加文件: {os.path.basename(file)}")
                else:
                    self.print(f"文件已存在: {os.path.basename(file)}")

    def remove_files(self):
        """移除选中的文件"""
        selected_items = self.file_list.selectedItems()
        if selected_items:
            removed = []
            for item in selected_items:
                removed.append(item.text())
                self.file_list.takeItem(self.file_list.row(item))
            self.file_removed_items.extend(removed)
            self.print(f"移除文件: {', '.join([os.path.basename(f) for f in removed])}")

    def undo_remove_files(self):
        """撤销移除文件"""
        if self.file_removed_items:
            file = self.file_removed_items.pop()
            # 检查是否已存在
            existing_files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
            if file not in existing_files:
                self.file_list.addItem(file)
                self.print(f"恢复文件: {os.path.basename(file)}")

    def clear_files(self):
        """清空文件列表"""
        self.file_removed_items.clear()
        self.file_list.clear()
        self.print("清空文件列表")

    # --------------------------------------------------------------------

    def find_md_files(self):
        """从文件夹中寻找MD文件"""
        folders = [self.folder_list.item(i).text() for i in range(self.folder_list.count())]
        if not folders:
            self.print("警告！请先在文件夹选区添加文件夹")
            return

        md_files = []
        for folder in folders:
            if os.path.isdir(folder):
                for root, _, files in os.walk(folder):
                    for file in files:
                        if file.endswith('.md'):
                            md_path = os.path.join(root, file)
                            md_files.append(md_path)

        if not md_files:
            self.print("未找到 MD 文件")
            return

        # 添加到文件列表
        existing_files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        added_count = 0
        for md_file in md_files:
            if md_file not in existing_files:
                self.file_list.addItem(md_file)
                added_count += 1

        self.print(f"找到 {len(md_files)} 个 MD 文件，添加了 {added_count} 个新文件")

    def start_summary_entry(self):
        self.worker_thread.send_task([self.start_summary, []])
        self.print("开始总结...")

    def start_summary(self):
        """开始总结"""
        files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        if not files:
            self.print("警告！文件选区为空，请在文件选区添加 MD 文件")
            return

        # 获取提示词
        prompt = cfg.summary_prompt
        if '{text}' not in prompt:
            self.print("错误！提示词中必须包含 {text} 字段")
            return

        # 读取并合并 MD 文件
        merged_content = []
        for md_file in files:
            try:
                with open(md_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    merged_content.append(f"# 文件: {os.path.basename(md_file)}\n\n{content}\n\n")
                self.print(f"读取文件: {os.path.basename(md_file)}")
            except Exception as e:
                self.print(f"读取文件失败: {os.path.basename(md_file)} - {str(e)}")

        if not merged_content:
            self.print("无法读取任何 MD 文件")
            return

        merged_text = ''.join(merged_content)
        self.print(f"合并完成，总长度: {len(merged_text)} 字符")

        # 更新配置
        # self.update_config()

        # 启动 llama.cpp 服务器（远程模式只做可用性检查）
        if cfg.use_remote_llama_server:
            self.print("使用远程 llama-server，检查可用性...")
            if not utils.check_remote_llama_cpp_address(print=self.print):
                self.print("错误！远程 llama-server 不可用")
                return
        else:
            self.print("启动 llama.cpp 服务器...")
            if not utils.start_llama_server(print=self.print):
                self.print("错误！服务器启动失败")
                return

        # 生成总结（统一走 utils 实现，支持远程/本地）
        self.print("发送到服务器进行总结...")
        summary = None
        try:
            summary = utils.query_llama_server(merged_text, prompt=prompt, print=self.print)
        except Exception as e:
            self.print(f"错误！总结生成失败: {str(e)}")

        # 保存总结
        if summary and cfg.stop_requested:
            self.print("任务已停止，总结未保存")
            summary = None
        if summary is not None and not summary.strip():
            self.print("警告！总结内容为空（模型没有输出内容）")
        if summary:
            output_filename = f'all_{datetime.datetime.now().isoformat().replace(":", '-')}.md'
            output_file = cfg.project_root / 'sum_output' / output_filename
            try:
                output_file.parent.mkdir(parents=True, exist_ok=True)
                with output_file.open('w', encoding='utf8') as f:
                    f.write(summary)
                self.print(f"总结已保存到: {output_file}")
            except Exception as e:
                self.print(f"保存总结失败: {str(e)}")

        # 停止服务器（远程模式无需管理服务器生命周期）
        if not cfg.use_remote_llama_server:
            utils.stop_llama_server(print=self.print)
            self.print("服务器已停止")
        if summary:
            self.print("二阶总结完成！")


    # --------------------------------------------------------------------

    def show_help(self):
        """显示帮助"""
        self.help_dialog.show()
        self.help_dialog.activateWindow()

    # --------------------------------------------------------------------

    def print(self, *values: object, sep: str = " ", end: str = "\n", file = None, flush = False):
        self.log_stream.write(sep.join([str(v) for v in values]) + end)
        print(*values, sep=sep, end=end, file=file, flush=flush)

    def update_log(self):
        """更新日志框"""
        content = self.log_stream.getvalue()
        if content:
            # 清空日志流
            self.log_stream.seek(0)
            self.log_stream.truncate(0)
            # 更新日志
            self.log_text.moveCursor(QTextCursor.MoveOperation.End)
            self.log_text.insertPlainText(content)
            self.log_text.ensureCursorVisible()

    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止llama 服务器
        utils.stop_llama_server(print=self.print)

        cfg.stop_requested = True
        if self.worker_thread:
            self.worker_thread.stop()
            self.worker_thread.wait(5000)

        # 停止日志线程
        self.log_timer.stop()

        event.accept()

    # --------------------------------------------------------------------


# ------------------------------------------------------------
# 主窗口

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('播音终结技')

        self.main_interface = MainInterface()
        self.addSubInterface(self.main_interface, FluentIcon.HOME, '播音与总结', isTransparent=True)

        self.summary_interface = SummaryInterface()
        self.addSubInterface(self.summary_interface, FluentIcon.BUS, '内容二阶导', isTransparent=True)

        self.settings_interface = SettingsInterface()
        self.addSubInterface(self.settings_interface, FluentIcon.SETTING, '设置')

        # 接线：任务运行时由功能界面锁定设置页控件
        self.main_interface.settings_interface = self.settings_interface
        self.summary_interface.settings_interface = self.settings_interface

        self.setResizeEnabled(True)
        self.setGeometry(100, 100, 1200, 800)
        self.show()

        self.load_config()
        print('启动成功')

    def load_config(self):
        utils.load_config()
        self.main_interface.load_config()
        self.settings_interface.load_config()

    def save_config(self):
        utils.save_config()

    def closeEvent(self, event):
        # 需要主动调用close才能完成清理
        self.save_config()

        self.main_interface.close()
        self.summary_interface.close()
        event.accept()


# ------------------------------------------------------------
# 启动

if __name__ == "__main__":
    # 启动后切换到项目根目录
    os.chdir(cfg.project_root)
    # 启动程序
    app = QApplication(sys.argv)
    window = MainWindow()
    sys.exit(app.exec())
