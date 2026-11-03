import sys
# 设置默认的错误处理策略为 'ignore'
sys.stdin.reconfigure(encoding='utf8', errors='ignore')
sys.stdout.reconfigure(encoding='utf8', errors='ignore')
sys.stderr.reconfigure(encoding='utf8', errors='ignore')
# ------------------------------------------------------------

import config as cfg
from argparse import ArgumentParser
from utils import *


def main(input_output_folder):

    load_config()
    print_config()

    # 当前配置
    print(f"当前配置: {cfg.__dict__}")

    # 创建输出文件夹
    os.makedirs(input_output_folder, exist_ok=True)

    # 1. 查找媒体文件
    print("查找媒体文件...")
    media_files = find_media_files(input_output_folder)
    print(f"找到 {len(media_files)} 个音视频文件")

    # 2. 转换为字幕
    print("\n转换媒体文件为字幕...")
    tasks = []

    # 遍历每个媒体文件
    for media_file in media_files:
        media_file = Path(media_file)

        # 输出的文本
        out_txt_file = media_file.with_suffix('.txt')
        # 输出的 asr_complete_file 标记
        out_asr_complete_file = media_file.with_suffix('.complete_asr')
        # 输出的 md 文档
        out_md_file = media_file.with_suffix('.md')
        # 输出的临时 md 文档
        out_md_file_tmp = media_file.with_suffix('.md_tmp')

        # 跳过有 md 文档输出的
        if out_md_file.exists():
            print(f"{out_md_file} 已存在，跳过")
            continue

        # 有 asr_complete_file 标记的跳过音频转文字
        elif out_asr_complete_file.exists():
            tasks.append([out_txt_file, out_asr_complete_file, out_md_file, out_md_file_tmp])

        # 需要进行音频转文字
        else:
            is_ok, tmp = convert_to_subtitle(media_file)
            assert tmp == out_txt_file
            if is_ok:
                # 标记为已处理
                out_asr_complete_file.touch()
                tasks.append([out_txt_file, out_asr_complete_file, out_md_file, out_md_file_tmp])

    if len(tasks) == 0:
        print("没有需要处理的字幕文件")
        return

    # 3. 启动 llama.cpp 服务器
    print("\n启动 llama.cpp 服务器...")
    start_llama_server()

    # 4. 总结字幕内容
    print("\n总结字幕内容...")
    failed = []
    for out_txt_file, out_asr_complete_file, out_md_file, out_md_file_tmp in tasks:
        if out_txt_file.stat().st_size == 0:
            print(f"{out_txt_file} 的转录为空，疑似无人声的音频。跳过该文件的 LLM 总结")
            continue

        try:
            is_ok = summarize_subtitles(out_txt_file, out_md_file_tmp)
            if is_ok:
                out_asr_complete_file.unlink(missing_ok=True)
                out_md_file_tmp.replace(out_md_file)
            else:
                failed.append(out_txt_file)
        except Exception as e:
            print(f"处理失败 {out_txt_file}: {e}")
            failed.append(out_txt_file)

    # 5. 停止 llama.cpp 服务器
    print("\n停止llama.cpp 服务器...")
    stop_llama_server()

    if failed:
        print(f"\n以下 {len(failed)} 个文件未处理完成（重跑 main_cli 可续传）:")
        for f in failed:
            print(f"  {f}")

    print("\n所有操作完成！")


if __name__ == "__main__":
    # 配置参数
    parser = ArgumentParser(description="播音总结机")
    parser.add_argument("input_output_folder", type=str, help="输入输出文件夹路径")
    args = parser.parse_args()

    assert os.path.isdir(args.input_output_folder), f"输入文件夹不存在: {args.input_output_folder}"

    main(args.input_output_folder)
