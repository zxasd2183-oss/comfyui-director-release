# Director Studio · 签名自动更新运行说明

## 目的与界限
- Studio 的程序/UI 与原有 Windows Worker、UE Hub 分别维护更新通道。Studio 固定 35 个受信任文件，不包含数据库、上传素材、角色母版、登录凭证、Nginx 或 systemd 主服务配置。
- 使用现有根目录只读 Ed25519 **公钥**验证，但用独立的 `director-studio-code-signed-v1` 消息域隔离 Worker/Hub 签名；签名**私钥仅在 GitHub Actions**，不会进入 VPS。
- PR 合并后，还必须等待 **main 分支**的 `Director Studio realtime workbench CI` 成功，才会发布不可覆盖的 `director-studio-v0.10.0.zip` 并推进 `studio-updates/channel.json`。其他分支及失败检查不能发布。
- 已 bootstrap 的 VPS 通过 `director-studio-signed-update.timer` 每约 5 分钟拉取。所有下载固定 GitHub HTTPS 主机白名单与 VPS 本机 CONNECT 代理 127.0.0.1:1081，校验签名、压缩包 SHA256、文件清单、源代码语法、版本单调性。
- 正常发布只重启 `director-studio.service`；部署前后必须检查 `/api/v1/production` 的审计链和项目/剧集/镜头/资产计数，并核实新进程返回精确 `studio_code_version`。否则备份还原、重启旧版并留下审计状态。
- 当前 Hub/Director_VPS 连接没有执行 VPS shell 或安装 systemd 服务的写权限。**任何 GitHub 代码合并都不能绕过这个首次安装前提。**

## VPS 首次安装（仅一次）

需要已有 root 管理员在当前实际 VPS 的、已检出的 GitHub `main` 仓库中运行：

```bash
git pull --ff-only
sudo bash studio/install-studio-signed-updater.sh
```

要求：Studio 服务原本已启用，根权限可读现有 `/etc/director-ue-hub-update.pub` 公钥，`/opt/comfyui-director-control/.venv/bin/python` 中已有 `cryptography`，且 VPS 本机 1081 代理可到达 GitHub。安装脚本拒绝覆盖已安装服务、状态与公钥，不会主动升级或改动运行中 Studio。

## 后续自动更新和实际回执

1. 开发者合并通过审核的 Studio 改动，提升 `STUDIO_CODE_VERSION`。
2. GitHub 验证签名及固定包内容、发布不可变 Release，最后才更新签名通道。
3. VPS 定时器自动验证、备份、升级或回滚；成功后写入 root-only 更新记录，并将简化的状态写入 Studio 程序目录 `signed-update-status.json`。
4. ChatGPT 可使用现有 Director Hub 的 `get_production_dashboard` 读取其 `studio_signed_update` 字段，检查是否报告 `upgraded` 或 `already_current` 及版本号。该字段只在 Studio v0.10.0 实际运行后出现。
5. Studio 当前业务数据库版本 `0.9.0` 与独立程序更新版本 `0.10.0` 是不同概念，不应混淆。

## 不能被绕过的条件

- 没有第一次安装的定时服务，GitHub 发版不等于 VPS 自动升级。
- 审批过的角色/场景仍须走 Studio 既有审核；更新器不会批准母版、生成 EP01、打开 GPU 或修改电源权限。
- 审计链无效、Studio 进程不健康、上传资料计数变动、版本不匹配、来源不是签名白名单、原文件被改为符号链接时，停止安装并回滚。
