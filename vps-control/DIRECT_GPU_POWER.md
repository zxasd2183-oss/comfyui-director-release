# Director GPU：管理员直接开关机

此版本将两项即时电源工具加入 **已有的私有 Director Hub MCP**：
- \`start_gpu_now()\`：调用优云智算开机接口，**不再等待网页 TOTP / 吉皮提指纹审批**。
- \`stop_gpu_now()\`：只在 ComfyUI 任务队列**可验证且为空**时发送关机指令，不需要逐次审批。关机前要确保生成文件已保存到持久存储。
- \`get_gpu_power_status()\`：查询真实状态。云平台接受命令不代表机器已经完成开/关机。

**授权边界**：仅现有高强度私有 MCP 路由认证的管理员可调用；VPS 8892 只监听 \`127.0.0.1\`。不要将 8892 开放公网，或泄露 Hub 私有 MCP URL。系统不会给匿名外部 API 开放直接开关机权限。

行为约束：操作之前检查真实云端状态；关机额外核验 ComfyUI 队列；真正提交前再次检查；SQLite 原子锁、防并发、90 秒防重、事件审计。云平台响应不确定时不自动重试。旧 \`request_gpu_start / request_gpu_stop\` 保留兼容但不再是必须流程。

## 一次性部署

在已有 Director Hub V0.6 的 VPS 上执行：

\`\`\`bash
cd ~/comfyui-director-release
git pull --ff-only
sudo bash vps-control/install-hub-v06.sh
\`\`\`

安装脚本不执行电源动作，升级完刷新 ChatGPT 中 Director Hub 工具列表，就能使用 \`start_gpu_now\`。若旧申请仍在 \`pending\` 或 \`executing\`，升级器会要求先等待状态完成/过期，不会抢占已有操作。

此变更**没有部署到 VPS、没有替用户自动开机**，仅提交 GitHub 后才能安装。旧手机和网页审批组件原样保留以兼容历史记录，不需要使用。

对于实时渲染，后续仍需接好 H3 真正的任务提交和自动回传服务。
