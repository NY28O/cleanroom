# 道具图批量修图

在[项目入口](项目入口.md)查看提示词、运行规则、验收标准和进度。启动时请说明要修改第几组到第几组。按[正常流程](道具图批量改款流程说明.md)保存高清原稿，等比恢复原画布，对同名透明 PNG 验收。

## 从 GitHub 安装

把下面这句话发给 Codex：

> 帮我安装并配置这个道具图修图 Skill：https://github.com/NY28O/cleanroom/tree/main/skill/prop-image-batch 。请安装需要的 Python 依赖，运行安装自检，并告诉我是否已具备出图条件。

如果只提供仓库首页地址，安装目录是 `skill/prop-image-batch`，技能名是 `prop-image-batch`。安装完成后可以在任意工作文件夹使用。例：“原图在 D:\\道具原图，试跑前三组，先给我看代表图。”

只预检不需要服务密钥；实际生成需本机配置兼容图像服务的 `OPENAI_BASE_URL`、`OPENAI_API_KEY`，可用 `PROP_IMAGE_MODEL` 指定模型。密钥留在本机。服务需支持单图编辑、透明 PNG 和目标尺寸。每次只上传当前原图。详见 [Skill](skill/prop-image-batch/SKILL.md)。

## 仓库内运行

首次安装不知道服务地址、模型或密钥在哪里填，可直接问 AI：“我第一次用，请按我的系统带我配置。”具体步骤见[首次配置与常见问题](skill/prop-image-batch/references/setup.md)。

打开仓库根目录，安装 `requirements.txt`，执行 `python -B preflight.py 1 3 --source-dir "原图库"` 只读预检；其余操作见 [流程说明](道具图批量改款流程说明.md)。打包离线版本用 `python -B package_workflow.py`。

## 维护

正式代码在 `skill/prop-image-batch/scripts/`；根目录的四个 Python 命令保留旧用法，调用同一份实现。更新默认规则、提示词与依赖时，同时校对仓库工作区和 Skill 内随包资源。工作区清单的验收进度属于本地数据，不回填到安装模板。

运行 `python -B -m unittest discover -s tests -v`，验证资源一致性和独立安装后的完整流程。`05_历史资料/脚本归档/` 仅供查阅，不是运行入口，不随 Skill 安装。
