# Relay Imagegen 本机部署

来源：https://github.com/Ash-ahy/relay-imagegen
版本：当前仓库版本
源码：本仓库目录
安装目录：%USERPROFILE%/.codex/skills/relay-imagegen
运行环境：Python 3.13、openai 2.37.0、Pillow 12.2.0、Tk 8.6。

最简单的部署方式：双击本目录 `install.cmd`。它会自动下载项目、安装依赖，并打开完整配置界面。每一行是一个“渠道 + 模型”组合，列表顺序就是失败切换优先级；可复制组合并混排多个渠道和模型，最后点击“保存配置”。

安装后如需修改配置，双击安装目录中的 `configure.pyw`。单源快速向导可用 `py -3.13 scripts/setup.py gui --quick` 打开。

系统 python 命令指向 Python 3.8，请使用 py -3.13。本目录启动脚本和已安装 Skill 的说明均已适配。

命令行调用（可选）：

    $skill = "$HOME/.codex/skills/relay-imagegen/scripts/relay_imagegen.py"
    py -3.13 $skill --list-sources
    py -3.13 $skill generate --prompt 'A quiet landscape' --size 3840x2160 --name test --dry-run

去掉 --dry-run 会实际调用服务并可能产生费用。输出默认位于当前工作目录 generated/。

安装完成后，使用 `$relay-imagegen` 加具体要求即可。
