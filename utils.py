import config as cfg
import os, re, time, subprocess, json, requests
from pathlib import Path
from openai import OpenAI, NotFoundError


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
    'llama_cpp_server',
    'llama_cpp_port',
    'llama_cpp_other_args',
    'use_remote_llama_server',
    'remote_llama_server_address',
    'remote_llama_server_key',
    'llm_temperature',
    'llm_max_tokens',
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

    with config_file.open('r', encoding='utf8') as f:
        data = json.load(f)
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

    pending = b''
    while True:
        if cfg.stop_requested:
            print('收到停止请求，正在终止下载...')
            cfg.bbdown_proc.terminate()
            break

        li = cfg.bbdown_proc.stdout.read(4096)
        if li:
            # 按 \r\n / \r / \n 行边界切分解码，避免多字节字符被截断；
            # BBDown 用 \r 刷新进度条，这里统一按换行输出
            parts = re.split(b'(\r\n|\r|\n)', pending + li)
            pending = parts.pop()
            for part in parts:
                print(_auto_decode(part).replace('\r\n', '\n').replace('\r', '\n'),
                      sep='', end='', flush=True)
            continue

        if cfg.bbdown_proc.poll() is None:
            time.sleep(0.25)
            continue
        break

    if pending:
        try:
            text = _auto_decode(pending)
        except Exception:
            text = pending.decode('utf8', errors='replace')
        print(text, sep='', end='', flush=True)
    cfg.bbdown_proc.wait()
    return (not cfg.stop_requested) and cfg.bbdown_proc.returncode == 0


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
        elif cfg.qwen3_asr_proc.poll() is not None:
            break

        if cfg.stop_requested:
            print('收到停止请求，正在终止转录...')
            cfg.qwen3_asr_proc.terminate()
            break

        time.sleep(0.25)

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


def stop_all_tasks(print=_print):
    """停止所有运行中的下载/转录子进程（不影响 llama-server 生命周期）"""
    if cfg.bbdown_proc is not None and cfg.bbdown_proc.poll() is None:
        cfg.bbdown_proc.terminate()
        print("已终止 BBDown 进程")
    if cfg.qwen3_asr_proc is not None and cfg.qwen3_asr_proc.poll() is None:
        cfg.qwen3_asr_proc.terminate()
        print("已终止 qwen3-asr 进程")


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
    command.extend(cfg.llama_cpp_other_args)

    command = [str(c) for c in command]

    print(f"启动 llama.cpp 服务器，模型路径: {cfg.llm_gguf_file}，端口: {cfg.llama_cpp_port}")
    # 实际执行时，可能需要在后台运行
    # 重定向标准输出和错误，以便捕获启动信息
    cfg.llama_cpp_server_proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    print("等待服务器启动（health 检查）...")
    local_base_url = f"http://127.0.0.1:{cfg.llama_cpp_port}"
    start_time = time.time()
    timeout = 120
    while time.time() - start_time < timeout:
        if cfg.llama_cpp_server_proc.poll() is not None:
            print("服务器启动失败，进程已退出")
            return False
        if check_remote_llama_cpp_address(base_url=local_base_url, print=lambda *_: None):
            print("服务器启动成功！")
            return True
        time.sleep(1)

    # 超时
    print("服务器启动超时")
    cfg.llama_cpp_server_proc.terminate()
    cfg.llama_cpp_server_proc = None
    return False


def stop_llama_server(print=_print):
    """停止 llama.cpp 服务器"""

    if cfg.llama_cpp_server_proc is not None:
        cfg.llama_cpp_server_proc.terminate()
        print("llama.cpp 服务器已停止")


def _normalize_llama_base_url(address: str) -> str:
    """归一化 llama-server 地址：剥掉末尾的 / 与 /v1，统一为 host[:port] 形式"""
    address = address.strip().rstrip('/')
    while address.endswith('/v1'):
        address = address[:-3].rstrip('/')
    return address


_model_id_cache = {}


def _get_first_model_id(api_base: str, api_key: str, print=_print) -> str:
    '''探测服务器可用模型 id（取 /v1/models 第一个），失败时退回 default；结果按 api_base 缓存'''
    if api_base in _model_id_cache:
        return _model_id_cache[api_base]
    try:
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        r = requests.get(f'{api_base}/models', headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json().get('data') or []
        if data and data[0].get('id'):
            _model_id_cache[api_base] = data[0]['id']
            return data[0]['id']
    except Exception as e:
        print(f"探测模型 id 失败（{api_base}/models），使用 default: {e}")
    return 'default'


def check_remote_llama_cpp_address(base_url=None, print=_print):
    """检查 llama.cpp 服务器地址是否可用（支持本地和远程）"""
    try:
        if base_url is None:
            base_url = cfg.remote_llama_server_address
            api_key = cfg.remote_llama_server_key
        else:
            # 本地启动检测场景不使用密钥
            api_key = ""
        # llama.cpp 官方健康端点是 /health（免认证）；地址兼容带或不带 /v1 的填法
        url = _normalize_llama_base_url(base_url) + "/health"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # 检查HTTP状态码
        data = response.json()
        return data.get("status") == "ok"
    except Exception as e:
        print(f"检查 llama.cpp 服务器失败: {e}")
        return False


def query_llama_server(text: str, prompt=None, print=_print) -> str:
    """向 llama.cpp 服务器发送查询，生成总结"""

    if prompt is None:
        prompt = "以下内容来自声音转文字，可能包含错误或内容不完整，可能需要修正。然后帮我总结内容，并提炼出要点和细节，要求输出为md格式。内容如下：\n{text}\n"
    else:
        assert '{text}' in prompt, "提示模板中必须包含 {text} 占位符"

    if cfg.use_remote_llama_server:
        # 地址兼容带或不带 /v1 的填法
        api_base = _normalize_llama_base_url(cfg.remote_llama_server_address) + '/v1'
        api_key = cfg.remote_llama_server_key
    else:
        # api_base = f'http://localhost:{cfg.llama_cpp_port}/v1'
        api_base = f'http://127.0.0.1:{cfg.llama_cpp_port}/v1'
        api_key = ''

    # 创建 OpenAI 客户端
    client = OpenAI(
        base_url=api_base,
        api_key=api_key or "not-needed"  # 本地服务器可能不需要 key
    )

    # 使用流式输出；模型 id 失效（服务器更换模型/重启）时清缓存重探一次
    response = None
    for _attempt in range(2):
        # 探测真实模型 id（新版 llama.cpp 服务器会校验模型名）
        model_name = _get_first_model_id(api_base, api_key, print=print)
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "你是一个强大的AI助手"},
                    {"role": "user", "content": prompt.replace('{text}', text)}
                ],
                temperature=cfg.llm_temperature,
                max_tokens=cfg.llm_max_tokens,
                stream=True,
                extra_body={
                    "enable_thinking": False  # 关闭Qwen思考过程
                }
            )
            break
        except NotFoundError:
            if _attempt > 0:
                raise
            _model_id_cache.pop(api_base, None)
            print(f"模型 id '{model_name}' 已失效（服务器可能更换了模型），重新探测...")

    msg = []
    for chunk in response:
        if cfg.stop_requested:
            print('\n[收到停止请求，中断生成]', sep='', end='', flush=True)
            break
        content = chunk.choices[0].delta.content
        if content:
            msg.append(content)
            print(content, sep='', end='', flush=True)

    msg = ''.join(msg)
    return msg


def summarize_subtitles(subtitle_file: Path, output_summary_file: Path, prompt=None, print=_print) -> bool:
    """总结字幕内容。任务被停止时返回 False（不写输出文件）"""

    print(f"正在处理字幕文件: {subtitle_file}")

    tmp_output_summary_file = output_summary_file.with_suffix('.md_tmp')

    # 读取字幕内容
    with open(subtitle_file, 'r', encoding='utf-8', errors='ignore') as f:
        subtitle_content = f.read().strip()

    # 发送到 llama.cpp 服务器进行总结
    summary = query_llama_server(subtitle_content, prompt=prompt, print=print)

    if cfg.stop_requested:
        print(f"任务已停止，未保存: {subtitle_file}")
        return False

    with open(tmp_output_summary_file, 'w', encoding='utf8') as f:
        f.write(summary)
    tmp_output_summary_file.replace(output_summary_file)

    print(f"结果已保存: {output_summary_file}")
    return True


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
