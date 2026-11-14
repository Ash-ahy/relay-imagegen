# Relay Imagegen 本机部署

来源：https://github.com/Ash-ahy/relay-imagegen
版本：当前仓库版本
源码：本仓库目录
安装目录：%USERPROFILE%/.codex/skills/relay-imagegen
安装器会下载固定的 Python 3.13.17 完整私有运行时（包含 pip 和 Tkinter）、openai 2.x、Pillow 和 certifi，用户电脑不需要预装 Python，也不会改动系统 Python 或 PATH。

最简单的部署方式：双击本目录 `install.cmd`。它会自动下载项目、安装依赖，并打开完整配置界面。每一行是一个“渠道 + 模型”组合，列表顺序就是失败切换优先级；可复制组合并混排多个渠道和模型，最后点击“保存配置”。

安装后如需修改配置，双击安装目录中的 `configure.cmd`。单源快速向导可用 `runtime\python.exe -s scripts/setup.py gui --quick` 打开。

安装器不依赖系统 Python；命令行调用时优先使用安装目录中的 `runtime\python.exe -s`。

命令行调用（可选）：

    $skill = "$HOME/.codex/skills/relay-imagegen/scripts/relay_imagegen.py"
    py -3.13 $skill --list-sources
    py -3.13 $skill generate --prompt 'A quiet landscape' --size 3840x2160 --name test --dry-run

去掉 --dry-run 会实际调用服务并可能产生费用。输出默认位于当前工作目录 generated/。

安装完成后，使用 `$relay-imagegen` 加具体要求即可。
