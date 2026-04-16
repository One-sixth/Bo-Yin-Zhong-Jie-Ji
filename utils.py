import config as cfg
import os, re, time, subprocess, json
from pathlib import Path
from llama_index.llms.openai_like import OpenAILike
from llama_index.core.llms import ChatMessage, MessageRole


# -------------------------------------------------------------------
_print=print
# -------------------------------------------------------------------
# 应对奇怪的编解码问题
def _auto_decode(text: bytes) -> str:
    try:
        return text.decode('utf8')
    except Exception:
        return text.decode('gbk')


# -------------------------------------------------------------------
# 配置处理

config_names = (
    'input_output_dir',
    'bbdown_exe',
    'bbdown_only_audio',
    'bbdown_other_args',
    'qwen3_asr_exe',
    'qwen3_asr_other_args',
    'llm_gguf_file',
    'mmproj_gguf_file',
    'llama_cpp_server',
    'llama_cpp_port',
    'llama_cpp_other_args',
    'text2md_prompt',
    'summary_prompt',
)
config_file = cfg.project_root / 'config.json'


def print_config(print=_print):
    """打印配置"""
    print('------------------------------------------------------------')
    for name in config_names:
        print(f"{name}: {getattr(cfg, name)}")
    print('------------------------------------------------------------')


def load_config(print=_print):
    """加载配置"""
    if not config_file.exists():
        return

    data = json.load(config_file.open('r', encoding='utf8'))
    for name in config_names:
        setattr(cfg, name, data.get(name, getattr(cfg, name)))

def save_config(print=_print):
    """保存配置"""
    data = {name: getattr(cfg, name) for name in config_names}
    # 使用原子写入的方法，避免配置文件损坏
    config_file_tmp = config_file.with_suffix('.json_tmp')
    with config_file_tmp.open('w', encoding='utf8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    config_file_tmp.replace(config_file)


# -------------------------------------------------------------------
# bbdown 下载音视频部分


def recognize_bv_ids(text: str, print=_print) -> list[str]:
    """识别 BV 号"""

    # 使用正则表达式识别 BV 号
    # BV 号格式：BV + 10 位字符（大小写均可）
    bv_pattern = r'BV[0-9A-Za-z]{10}'
    bv_matches = re.findall(bv_pattern, text)

    # 去重并提取 BV 号部分（去掉 "BV" 前缀）
    unique_bv_ids = []
    seen = set()
    for match in bv_matches:
        bv_id = match[2:]  # 去掉 "BV" 前缀
        if bv_id not in seen:
            seen.add(bv_id)
            unique_bv_ids.append(bv_id)

    return unique_bv_ids


def check_bbdown_exe(print=_print):
    """检查 bbdown 是否可用"""

    try:
        # 尝试执行 bbdown --help 命令
        r = subprocess.run(
            [cfg.bbdown_exe, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            # encoding='utf8',
        )
        is_ok = '哔哩' in _auto_decode(r.stdout)
        return is_ok

    except Exception:
        return False


def download_video(bv_id: str, output_dir: str, audio_only: bool, print=_print):
    """下载视频"""

    if cfg.bbdown_proc is not None and cfg.bbdown_proc.poll() is None:
        print('已有bbdown进程在运行，无法开始新下载')
        return False
    else:
        cfg.bbdown_proc = None

    os.makedirs(output_dir, exist_ok=True)

    command = [cfg.bbdown_exe, f"BV{bv_id}", *cfg.bbdown_other_args]

    # 如果指定了输出目录，添加目录参数
    if output_dir:
        command.extend(["--work-dir", output_dir])

    # 如果只下载音频，添加 --audio-only 参数
    if audio_only:
        command.append("--audio-only")

    cfg.bbdown_proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
        # encoding='utf8',  # 因为奇怪的编码问题，后面用 _auto_decode 来解码
        # errors='ignore',
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    while True:
        li = cfg.bbdown_proc.stdout.read()
        if li:
            li = _auto_decode(li)
            print(li, sep='', end='', flush=True)
            continue

        if cfg.bbdown_proc.poll() is None:
            time.sleep(0.25)
            continue

        else:
            break

    cfg.bbdown_proc.wait()
    return cfg.bbdown_proc.returncode == 0


def stop_download_video(print=_print):
    """停止下载视频"""
    if cfg.bbdown_proc is not None and cfg.bbdown_proc.poll() is None:
        cfg.bbdown_proc.terminate()


# -------------------------------------------------------------------
# 音视频转文字


def find_media_files(folder: str, print=_print) -> list[Path]:
    """查找文件夹中的视频和音频文件"""
    supported_exts = ('.mp4', '.avi', '.mkv', '.mov', '.wmv', '.wav', '.m4a', '.mp3', '.aac', '.flac', '.ogg')
    media_files = []
    for root, _, files in os.walk(folder):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in supported_exts:
                media_files.append(Path(os.path.join(root, file)))
    return media_files


def check_qwen3_asr_exe(print=_print):
    """检查 qwen3-asr 程序是否可用"""
    try:
        r = subprocess.run(
            [cfg.qwen3_asr_exe, '--help'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf8'
        )
        return r.returncode == 0 and '高精度转录' in r.stdout

    except Exception:
        return False


def convert_to_subtitle(media_file: Path, print=_print):
    """使用命令行工具将媒体文件转换为字幕"""

    if cfg.qwen3_asr_proc is not None and cfg.qwen3_asr_proc.poll() is None:
        print('已有qwen3-asr进程在运行，无法开始新转换')
        return False
    else:
        cfg.qwen3_asr_proc = None

    # 这里使用您指定的转换工具，例如 ffmpeg + 语音识别工具
    # 示例命令，实际使用时需要根据您的工具调整
    command = [cfg.qwen3_asr_exe, media_file, '-njson', *cfg.qwen3_asr_other_args]

    # 注意：实际执行时需要处理管道，这里只是示例
    print(f"提取文字 {media_file}")
    cfg.qwen3_asr_proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf8',
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    while True:
        li = cfg.qwen3_asr_proc.stdout.readline()
        if li:
            print(li, sep='', end='', flush=True)
            continue

        if cfg.qwen3_asr_proc.poll() is None:
            time.sleep(0.25)
            continue

        else:
            break

    cfg.qwen3_asr_proc.wait()
    cfg.qwen3_asr_proc = None

    out_file = Path(media_file).with_suffix('.txt')
    is_ok = out_file.exists()

    # 是否成功，输出文件路径
    return is_ok, out_file


def stop_qwen3_asr(print=_print):
    """停止 qwen3-asr 进程"""
    if cfg.qwen3_asr_proc is not None and cfg.qwen3_asr_proc.poll() is None:
        cfg.qwen3_asr_proc.terminate()


# -------------------------------------------------------------------
# 文字转总结


def check_llama_cpp_exe(print=_print):
    """检查 llama.cpp 程序是否可用"""
    # if not os.path.isfile(cfg.llama_cpp_server):
    #     return False

    try:
        r = subprocess.run(
            [cfg.llama_cpp_server, '--help'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        return r.returncode == 0
    except Exception:
        return False


def start_llama_server(print=_print):
    """启动 llama.cpp 服务器"""

    if cfg.llama_cpp_server_proc is not None:
        cfg.llama_cpp_server_proc.terminate()
        cfg.llama_cpp_server_proc = None

    command = [
        cfg.llama_cpp_server,
        '--model', cfg.llm_gguf_file,
        '--port', cfg.llama_cpp_port,
    ]
    if cfg.mmproj_gguf_file is not None and len(cfg.mmproj_gguf_file) > 0:
        command.extend(['--mmproj', cfg.mmproj_gguf_file])

    command.extend(cfg.llama_cpp_other_args)

    command = [str(c) for c in command]

    print(f"启动 llama.cpp 服务器，模型路径: {cfg.llm_gguf_file}，端口: {cfg.llama_cpp_port}")
    # 实际执行时，可能需要在后台运行
    # 重定向标准输出和错误，以便捕获启动信息
    cfg.llama_cpp_server_proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,  # 捕获标准输出
        stderr=subprocess.STDOUT,  # 合并标准错误到标准输出
        text=True,  # 以文本模式读取
        bufsize=1,  # 行缓冲
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # 等待启动成功的标志
    start_time = time.time()
    timeout = 120  # 120秒超时
    success_patterns = [
        'server is listening on',
    ]

    print("等待服务器启动...")
    while time.time() - start_time < timeout:
        if cfg.llama_cpp_server_proc.poll() is not None:
            # 进程已退出，启动失败
            print("服务器启动失败，进程已退出")
            return False

        # 读取一行输出
        line = cfg.llama_cpp_server_proc.stdout.readline()
        if line:
            print(line, sep='', end='', flush=True)  # 打印服务器输出
            # 检查是否包含成功启动的标志
            for pattern in success_patterns:
                if pattern in line:
                    print("服务器启动成功！")
                    return True

        time.sleep(0.1)  # 短暂睡眠，避免CPU占用过高

    # 超时
    print("服务器启动超时")
    cfg.llama_cpp_server_proc.terminate()
    cfg.llama_cpp_server_proc = None


def stop_llama_server(print=_print):
    """停止 llama.cpp 服务器"""

    if cfg.llama_cpp_server_proc is not None:
        cfg.llama_cpp_server_proc.terminate()
        print("llama.cpp 服务器已停止")


def query_llama_server(text: str, prompt=None, print=_print) -> str:
    """向 llama.cpp 服务器发送查询，生成总结"""

    if prompt is None:
        prompt = "以下内容来自声音转文字，可能包含错误或内容不完整，可能需要修正。然后帮我总结内容，并提炼出要点和细节，要求输出为md格式。内容如下：\n{text}\n"
    else:
        assert '{text}' in prompt, "提示模板中必须包含 {text} 占位符"

    gw = OpenAILike(
        api_base=f'http://localhost:{cfg.llama_cpp_port}/v1',  # 指向国产模型平台
        api_key='',
        model="qwen3.5",                # 千问3.5
        temperature=0.9,                # 精准输出控制
        context_window=128 * 1024,      # 超长上下文支持
        max_tokens=128 * 1024,          # 单次响应最大token
        is_chat_model=True,             # 必须开启聊天模式
        max_retries=5,                  # 自动重试次数
        timeout=10,                     # 网络超时宽容
        additional_kwargs={
            "extra_body": {
                "enable_thinking": True  # 关闭Qwen思考过程
            }
        }
    )

    # 使用流式输出
    response = gw.stream_chat(messages=[
            ChatMessage(role=MessageRole.SYSTEM, content="你是一个强大的AI助手"),
            ChatMessage(
                role=MessageRole.USER,
                content=prompt.format(text=text)
            )
        ]
    )

    msg = []
    for chunk in response:
        msg.append(chunk.delta)
        print(chunk.delta, sep='', end='', flush=True)

    msg = ''.join(msg)
    return msg


def summarize_subtitles(subtitle_file: Path, output_summary_file: Path, prompt=None, print=_print):
    """总结字幕内容"""

    print(f"正在处理字幕文件: {subtitle_file}")

    tmp_output_summary_file = output_summary_file.with_suffix('.md_tmp')

    # 读取字幕内容
    subtitle_content = open(subtitle_file, 'r', encoding='utf-8', errors='ignore').read().strip()

    # 发送到 llama.cpp 服务器进行总结
    summary = query_llama_server(subtitle_content, prompt=prompt, print=print)
    open(tmp_output_summary_file, 'w', encoding='utf8').write(summary)
    tmp_output_summary_file.replace(output_summary_file)

    print(f"结果已保存: {output_summary_file}")


# -------------------------------------------------------------------
# 二阶总结部分


# def find_md_files(folder):
#     """查找文件夹中的md文件"""
#     supported_exts = ('.md',)
#     md_files = []
#     for root, _, files in os.walk(folder):
#         for file in files:
#             ext = os.path.splitext(file)[1].lower()
#             if ext in supported_exts:
#                 md_files.append(Path(os.path.join(root, file)))
#     return md_files


# def summarize_summary(input_output_dir, output_summary_file):
#     """总结总结内容"""
#     md_files = find_md_files(input_output_dir)
#
#     md_all = []
#     for md_file in md_files:
#         md_all.append(open(md_file, 'r', encoding='utf-8', errors='ignore').read().strip())
#
#     md_all = '\n\n'.join(md_all)
#     print(f'总字数: {len(md_all)}')
#
#     is_ok = start_llama_server()
#     if not is_ok:
#         return
#
#     prompt = "以下内容来自声音转文字内容的总结，帮我去除重复内容，再次精炼和总结，要求输出为md格式。内容如下：\n{text}\n"
#     summary = query_llama_server(md_all, prompt=prompt)
#
#     stop_llama_server()
#
#     open(output_summary_file, 'w', encoding='utf8').write(summary)
#     print(f"结果已保存: {output_summary_file}")
