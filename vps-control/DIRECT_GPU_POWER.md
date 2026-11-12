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


## 2026-11-11：已接入免审核入口，但云平台状态读不到

现有私有 Director Hub 暴露 \`start_gpu_now()\`、\`stop_gpu_now()\`，每次操作无需微软、吉皮提、TOTP 或网页确认。它们**只对拥有当前私有 Hub MCP 路由权限的管理员开放**；不能直接把 8892 暴露到公网。

线上读数 \`configured=true, instance_selected=true, gpu_control_enabled=false, mode=read_only\`，并有 \`get_gpu_power_status: provider_request_failed\`。这说明配置字段存在，**不能证明密钥有效、实例仍存在、网络与提供商服务可访问**；不能靠切换一个布尔值消除云平台故障。

### 一次无副作用、无泄密诊断

将 GitHub \`main\` 更新到现有 VPS 仓库目录，然后运行（无需每次操作审批；这是只读健康检查）：

\`\`\`bash
git pull --ff-only
sudo /opt/comfyui-director-control/.venv/bin/python vps-control/diagnose_gpu_direct_power.py
\`\`\`

输出只有限定的 JSON 状态码，无密钥、实例 ID、完整 URL、云服务原始错误或堆栈。不会尝试开机或关机。

| stage / reason | 需要修复的层 |
| --- | --- |
| configuration / credential_or_instance_configuration_invalid | 检查 root-only 凭证原件是否存在、0600、五个必要字段有效；绝不要把密钥粘贴到聊天 |
| dns / provider_hostname_unreachable | VPS 到 \`api.compshare.cn\` 的 DNS |
| tls / provider_https_connection_failed | VPS 到云平台 HTTPS/443 路由、TLS、证书或连接 |
| provider / provider_sdk_auth_or_request_failed | Python UCloud SDK、提供商 API 或账户密钥权限；由 VPS 管理员私下核查 |
| provider / provider_rejected | 云平台拒绝 Describe 请求，核查账户、实例归属及 API 密钥权限 |
| instance / configured_instance_not_found | 选择的 GPU 实例可能已删除、转移、释放，或 Region/Zone 配错 |
| instance / configured_region_zone_mismatch | 现有实例记录与锁定的地域、可用区不符 |
| ready + provider_state | 只读 Describe 成功；之后可通过现有 Hub 直控工具开关机，不需要旧审批链 |

**重要**：诊断 \`ready\` 只证明云平台查询成功，不证明直控已被运行时启用，更不证明 GPU 已启动。确认 \`get_control_center_status.gpu_control_enabled=true\` 和真实云状态后，再用私有 MCP 的 \`start_gpu_now()\`。云平台响应为 accepted 后需要再次检查 Running。关机必须先有可验证的空队列，并确认文件已持久保存；队列当前不可达时仍禁止关机。

保留 VPS 运行时或运营人员施加的停用开关，不因用户免逐次审批的要求自动移除实例安全限制。
