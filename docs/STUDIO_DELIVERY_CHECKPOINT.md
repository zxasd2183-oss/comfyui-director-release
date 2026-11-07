# Director Studio · 核心交付状态（对话接续唯一索引）

更新时间：2026-11-06（GitHub 主线代码状态；不是 VPS 实机验收结果）

## 当前真正已写进代码的功能

- Studio 冰川界面、Microsoft 所有者登录、项目／角色／场景／镜头规划、媒体素材库。
- 角色/场景素材审核、镜头生产计划和版本冻结、31 镜头整集导出。
- 视频 MP4 接收校验、断点续传、审核；音频、字幕、剪辑、成片和私有 QC 回执。
- VPS 私有管理员入口 \`start_gpu_now / stop_gpu_now\`：无需独立 TOTP/手机逐次审批。仍需原有私有 Hub 凭据/Studio Microsoft 所有者会话。
- Studio 首页 GPU 开关机按钮；关机时必须先确认 ComfyUI 无任务，云平台接受不代表实际电源完成。
- GPU 本机 CLI \`video-pipeline/director_video.py run-episode\`：逐镜头 ComfyUI H3 提交、等待、真实 MP4 下载、校验与中断恢复。
- Studio 剧集级短期 GPU 自动回传凭据；GPU 经单独 HTTPS Bearer 通道自动将实际 MP4 回传为 \`in_review\`，不自动审片。
- Nginx 独立 \`/studio/api/v1/gpu-return/\` 路由仅转发 Bearer，上传约 1MB 的 JSON 分块；其他 /studio 路径继续执行原 Microsoft 登录且清空 Authorization。

## 当前实际运行状态与不能宣称完成的事项

2026-11-06 最近一次由 Director Hub 读取：优云智算 \`cn-sh2\` RTX 5090
**Stopped**，ComfyUI/H3 **backend_unavailable**；已部署 Hub V0.6
仍报告 \`gpu_control_enabled:false\`。这意味着新 GitHub 直接开机接口
**尚未部署**，不能在此时声称实际 GPU 已启动或真镜头已生成。

Studio WaitingOffice/EP01：《待回答事务所》《谁才是真正的AI？》，
**31 镜头 / 160 秒**，规划草稿 revision 2。源项目没有真实已审核
镜头视频；若源图、角色母版、场景和 H3 API workflow 未经完成/通过，
\`prepare-studio-batch\` 的严格前置条件会阻止真实生成，这是正确的。

**当前绝不应宣称完整成品**。真实项目完成标准：GPU Running、
H3 实际执行并自动回传全部 31 镜头、Studio 可播放，艺术审核、
字幕/音频混合、160 秒整片真实导出和可下载成片、VPS 实机验收。

## 一次性 VPS 部署入口

在 **VPS 当前 GitHub clone**，以普通 sudo 用户执行：

\`\`\`bash
cd ~/comfyui-director-release
bash scripts/deploy-director-all-once.sh
\`\`\`

脚本 fast-forward 拉取、部署 Hub、Studio，升级独立上传 Nginx 位置，
保留 DB/旧 Microsoft 登录，运行已有发布防护。不会自动开关 GPU。
如 VPS 运行脚本不在该路径，以真实 clone 路径执行。

升级后重新连接/刷新 ChatGPT 自定义 Director Hub 的工具注册，
新 \`start_gpu_now\` 应可直接启动 GPU，无独立审批。
Studio 首页 Microsoft 所有者登录后提供开/关机按钮。

## GPU 上一次性本地执行器安装

GPU 真正启动后，在 **GPU 本机** 获取仓库并执行：

\`\`\`bash
bash video-pipeline/install-on-gpu.sh /你的持久化目录/director-video
\`\`\`

准备审核后的 episode handoff、真实 H3 API workflow 和绑定，
使用 \`prepare-studio-batch\` 生成整集计划。在 Studio 视频制作页
下载 48 小时的剧集回传密钥并安全复制到 GPU 私有文件（0600）。
GPU 侧执行：

\`\`\`bash
python3 /你的持久化目录/director-video/director_video.py run-episode \
  --plan /你的文件/episode-plan.json \
  --db /你的文件/episode-runs.sqlite \
  --results /你的文件/collected-videos \
  --studio-return-token /你的私有目录/gpu-return.token \
  --execute --acknowledge-gpu-cost
\`\`\`

如出现不确定生成/网络超时，按状态恢复，不得重复排队盲目计费。
若 GPU 工作流不可用，需要先确认实际 H3 节点映射与源素材，
不能伪造视频或以离线模拟结果冒充生产成片。

## 开发接续指令

- GitHub 仓库：\`zxasd2183-oss/comfyui-director-release\`，主分支 \`main\`。
- 一切以 GitHub 最新 HEAD、GitHub CI 和 Director Hub/VPS 真正状态为准。
- 优先完成 **真实 H3 导演工作流 → GPU 生成 → 自动回传 → EP01 成片**，
  不再扩大外围功能或宣称“测试通过就是项目完成”。
- 未有用户另行明确要求不得篡改已有 EP01 31 镜头规划、160 秒时长。
- 避免将私钥、TOTP、MCP 私有完整 URL、OAuth Token、剧集级回传 Bearer 写入 GitHub 或聊天。
