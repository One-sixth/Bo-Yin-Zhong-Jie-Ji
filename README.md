# 播音终结技

一个功能强大的播音总结机工具，支持从 B 站视频下载、音频提取、语音识别到内容总结的完整流程。


## 功能特点

- 🎯 **BV 号识别**：自动从文本中提取 B 站视频 BV 号
- 📥 **视频下载**：使用 BBDown 下载 B 站视频，支持只下载音频
- 🎵 **音频提取**：使用 Qwen3-ASR 提取音频为文本
- 📝 **内容总结**：使用 Qwen3.5 大模型生成内容总结
- 🚀 **一键全流程**：从识别到总结的完整流程自动化
- 🎨 **直观界面**：基于 PySide6 的图形界面，操作简单直观


## 使用方法

### 配置
    在 Release 页面可以下载 播音终结技 已构建包
    
    下载其他需要的依赖包，
    BBDown，用于下载B站视频，在 [BBDown](https://github.com/nilaoda/BBDown) 下载
    Qwen3-ASR-GGUF，用于提取音频为文本，需要为我修改后版本，在 [Qwen3-ASR-GGUF](https://github.com/One-sixth/Qwen3-ASR-GGUF/releases) 下载
    llama.cpp，用于大模型推理，在 [llama.cpp](https://github.com/ggml-org/llama.cpp/releases) 下载
    qwen3.5-35B-A3B-GGUF，用于内容总结，在 [qwen3.5-35B-A3B-GGUF](https://www.modelscope.cn/models/unsloth/Qwen3.5-35B-A3B-GGUF) 下载
    若 空间内存不足，也可以换成 qwen3.5-9B-GGUF 版本
    
    解压它们。然后打开 播音终结技 中的 main_ui.exe 程序
    在左下角的配置区，填入上面下载的路径
    然后点击右边的检查环境按钮，检查是否配置正确

### main_ui 界面的使用

#### 播音与总结 界面
    在左上角输入区，直接粘贴B站的视频网址，可以粘贴多个，只要BV号完整即可
    然后在右上区，点击一键全流程按钮，就可以自动下载视频，提取音频，生成字幕，最后生成总结

#### 内容二阶导 界面
    左上角区域可以添加多个文件夹，然后点 文件夹选区寻找MD文件 按钮。文件夹中的MD文件会自动添加到下方 文件选区中
    在文件选区中，可以多选文件，排除不需要的MD文件
    然后点右上区的 开始二次总结按钮，就会对所有的MD文件进行二次总结，生成新的二次总结MD文件，保存在软件所在目录的 sum_output 目录中

### main_cli 命令行使用
    main_cli 与 main_ui 共享配置，使用方法很简单。
    先确保 main_ui 能正常使用。
    然后使用 以下命令，即可将对目标目录里面的所有音视频文件，生成总结MD文档
```shell
main_cli.exe 目标目录
```

## 其他

1. **基本操作**
   - **输入区域**：粘贴 B 站链接或包含 BV 号的文本
   - **识别 BV 号**：点击按钮提取 BV 号到下方列表
   - **下载视频**：选择输出目录，点击下载按钮
   - **提取字幕**：选择输入目录，点击提取字幕按钮
   - **生成总结**：点击全自动总结按钮，等待生成完成
   - **一键全流程**：自动执行识别→下载→提取→总结的完整流程

2. **配置管理**
   - 应用会自动保存配置到 `config.json` 文件
   - 下次启动时会自动加载配置


## 构建项目

1. **克隆仓库**
   ```shell
   git clone https://github.com/one-sixth/播音终结技.git
   cd 播音终结技
   ```

2. **安装依赖**
   ```shell
   pip install -r requirements.txt
   ```

3. **安装 pyinstaller**
   ```shell
   pip install pyinstaller
   ```

4. **打包应用**
   ```shell
   pyinstaller build.spec
   ```

5. **分发应用**
   - 打包完成后，会在 `dist/播音终结技` 目录下生成独立的可执行文件 `main_ui.exe` 和 `main_cli.exe`


## 项目结构

```
├── main_ui.py               # 主界面程序
├── main_cli.py              # 命令行程序
├── utils.py                 # 工具函数
├── config.py                # 配置文件
├── requirements.txt         # 依赖项
└── README.md                # 项目说明
```


## 常见问题

### Q: BBDown 下载失败怎么办？
A: 检查 BBDown 路径是否正确，网络连接是否稳定，是否需要登录，以及 BV 号是否有效。

### Q: 提取字幕失败怎么办？
A: 检查 Qwen3-ASR 路径是否正确，输入文件是否为支持的音频/视频格式，检查音频的码率是否过低，已知 64 kbps AAC 格式的音频识别容易识别错误。

### Q: 总结生成失败怎么办？
A: 检查 llama.cpp 服务器路径和模型路径是否正确，确保有足够的内存和 GPU 资源。


## 许可证

本项目采用 GPLv3 许可证。


## 致谢

- [Qwen3-ASR-GGUF](https://github.com/HaujetZhao/Qwen3-ASR-GGUF) - Qwen3-ASR 模型，用于音频识别为文本
- [BBDown](https://github.com/nilaoda/BBDown) - B站视频下载工具
- [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) - 语音识别工具
- [llama.cpp](https://github.com/ggerganov/llama.cpp) - 大模型推理库
- [PySide6](https://doc.qt.io/qtforpython/) - Qt for Python


## 联系方式

如有问题或建议，欢迎提交 Issue 或联系项目维护者。
