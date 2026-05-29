import sys
from pathlib import Path
import subprocess


# -------------------------------------------------------------------
# 获取项目根目录 (适配打包环境)
if getattr(sys, 'frozen', False):
    # 打包环境：sys.executable 位于 dist/Project/ 根目录
    project_root = Path(sys.executable).parent
else:
    # 源码环境
    project_root = Path(__file__).absolute().parent

# -------------------------------------------------------------------
# BBdown 下载音视频部分
bbdown_exe = r"bbdown.exe"
# BBdown 只下载音频
bbdown_only_audio = False
# BBdown 其他参数
bbdown_other_args = []
# -------------------------------------------------------------------
# qwen3-asr 音视频转文本
qwen3_asr_exe = r"E:\Software\LLM\Qwen3-ASR-GGUF-Transcribe\transcribe.exe"
# qwen3-asr 其他参数
qwen3_asr_other_args = []

# -------------------------------------------------------------------
# qwen3.5 35b a3b q4 大模型
llm_gguf_file = r'E:\Software\LLM\qwen3.6-35b-a3b\Qwen3.6-35B-A3B-APEX-MTP-I-Quality.gguf'
# llama-cpp 服务器
llama_cpp_server = r'E:\Software\LLM\llama-bin-win-cuda-13.1-x64\llama-server.exe'
# llama-cpp 服务器端口
llama_cpp_port = 45124
# llama-cpp 服务器其他参数
llama_cpp_other_args = ['--temp', '0.95', '--top-p', '0.95', '--min-p', '0.0', '--top-k', '30', '--reasoning', 'off', "--ctx-size", '262144']
# 使用远程 llama-server
use_remote_llama_server = False
# 远程 llama-server 地址
remote_llama_server_address = "http://localhost:45124"
# 远程 llama-server 密钥
remote_llama_server_key = ""

# -------------------------------------------------------------------
# 输入输出目录，注意，输入和输出是同一个目录
input_output_dir = r"test_input"

# -------------------------------------------------------------------
# 全局变量
llama_cpp_server_proc: subprocess.Popen | None = None
qwen3_asr_proc: subprocess.Popen | None = None
bbdown_proc: subprocess.Popen | None = None

# -------------------------------------------------------------------
# 字幕转文档 提示词
text2md_prompt = "以下内容来自声音转文字，可能包含错误或内容不完整，可能需要修正。然后帮我总结内容，并提炼出要点和细节，要求输出为md格式。内容如下：\n{text}\n"

summary_prompt = "以下内容是多个MD文件的合并，包含重复信息。请帮我：1. 去除重复内容 2. 总结所有要点 3. 整理成清晰的MD格式。内容如下：\n{text}\n"

_default_text2md_prompt = text2md_prompt
_default_summary_prompt = summary_prompt

# -------------------------------------------------------------------
