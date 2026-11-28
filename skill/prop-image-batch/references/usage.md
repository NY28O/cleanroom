# 从安装到验收入库

**准备。** 下载或解压后保留完整的 `prop-image-batch` 目录，无需开发仓库。以下 PowerShell 命令中的目录、组号和文件名都是示例；用自己的路径、明确指定的起止组号和实际代表图替换。工作区、Skill 安装目录和只读原图库分开。

```powershell
$skill = "D:\技能\prop-image-batch"
$cli = Join-Path $skill "scripts/batch.py"
$work = "D:\修图工作区"
$src = "D:\道具原图"
python -m pip install -r (Join-Path $skill "requirements.txt")
python -B $cli check-install
python -B $cli --workspace $work preflight --start 20 --end 21 --source-dir $src
```

**生成代表图。** 按[环境配置](setup.md)在本机填写服务地址、密钥和受支持的模型。先执行 `doctor`，配置检查通过后才按授权试跑。每次只上传当前道具的高清副本，画风由提示词控制；本地风格示例不上传。

```powershell
python -B $cli doctor
python -B $cli --workspace $work init --start 20 --end 21 --source-dir $src
$batch = Read-Host "粘贴 init 输出的批次路径"
python -B $cli --workspace $work submit $batch --first-only
python -B $cli --workspace $work restore $batch
Invoke-Item (Join-Path $batch "复核.html")
```

**看样。** 在浅底、深底对照原图与恢复稿，检查摆放、支点、款式、材质和孔洞。请求记录的 `upload_size`、`settings.size`、`raw_size` 分别是上传、请求、实际返回尺寸；恢复核验的 `exported_size` 是最终文件尺寸。2048×2048 是请求值。先检查套用原图 Alpha 前的对位，再验原尺寸和最终 Alpha；技术通过仍待人工判断。

**按组推进。** 只有代表图通过才能继续该组。同一批次下次接着做：先按原范围、原图库重新预检，用同一工作区和批次路径查 `status`，有原稿先恢复；不要重新 `init`。请求结果不明先查记录，不自动重发。

```powershell
python -B $cli --workspace $work accept $batch 20-1.png
python -B $cli --workspace $work submit $batch
python -B $cli --workspace $work restore $batch
python -B $cli --workspace $work checkpoint $batch --group 20
```

首组全检至少 90% 通过；后续组按编号分散抽 20 张，至少 19 张通过，不足 20 张全检且至少 90% 通过。额外异常逐张处理。按实际结果逐张 `accept` 或 `reject $batch 文件名 --reason "原因"`。人工确认无共性问题后执行 `checkpoint $batch --group 20 --no-common-issue`，再按相同步骤处理下一组。明确要求入库时运行 `publish $batch 文件名`，只写已放行、可核验的稿，不覆盖已有同名成品。以上子命令均使用同一 CLI 并带 `--workspace $work`。
