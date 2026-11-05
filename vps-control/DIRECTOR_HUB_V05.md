# Director Hub V0.5 · 原计划三个插件合成一个

## 核心架构

ChatGPT 只添加一个 MCP 插件：

    https://jipite.borealos.cn/mcp/<Hub 自己的私密令牌>

路径由 VPS 自有 HTTPS Nginx 转到 VPS 回环 8897（私密桥接），进而到 Director Hub 8896。此域名目前已经提供 /api/v1/mobile/ 手机审批和 /app-updates/ APK；安装器仅新增 /mcp/，**不删除、不覆盖**原路径。

Hub 精确公开 13 个 MCP 工具，内部固定分成：

- 8 个 GPU Director V3 只读工具 → VPS 127.0.0.1:18790 经 GPU SSH 反向隧道 → GPU 上现有 Director V3 8790 私有 MCP。
- 2 个 VPS 状态只读工具 → VPS 原有 127.0.0.1:8890/mcp。
- 3 个 Power Requests 工具 → VPS 原有 127.0.0.1:8892/mcp。两个写入工具**仅提交申请**；真正电源 API 只能经独立的吉皮提 Microsoft + 一次性指纹私钥签名和 VPS 最终状态/队列复核后执行。

不通过 Hub 新增 GPU 开关机直接执行工具、不修改手机审批系统、不使用 GPT API、不引入 Cloudflare、不开 ComfyUI 公网端口、不修改 GPU SSH 密钥。

## 部署条件

- 广州 VPS 上已安装并保持运行：director-vps-control、director-power-mcp、director-mobile-v06。
- 原有根目录配置 /etc/comfyui-director-control.env 已配置 DIRECTOR_GPU_MCP_URL=https://director.borealos.cn/mcp/<GPU V3 原有 token>。
- 原 SSH -R 127.0.0.1:18790:127.0.0.1:8790 已安装在 GPU 自动启动脚本中（回连是否已成功要单独实测）。
- Nginx 有唯一 jipite.borealos.cn HTTPS server block，已有证书和手机 HTTPS API 正常。
- **无需开关 GPU 即可安装 Hub**。GPU 离线时 Hub 仍允许读 VPS 状态和创建安全开机申请；GPU 工作室查询会明确返回 backend_unavailable。

## 一次安装

只在 VPS 私人 SSH 终端执行（不是 GPU 终端）。先审核仓库代码：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash vps-control/install-hub-v05.sh

脚本会：

1. 核对三个既有服务，而不改它们。
2. 从 root 0600 控制配置提取 GPU 原有 MCP 私密路径；只把这段路径放进 0640 的 root:directorpower 文件，**不复制云平台 API 密钥**；原路径变化时不会静默替换。
3. 只生成一次新的独立 Hub 64 位十六进制访问令牌，永久存 VPS 私有文件，重复安装会复用，不随升级轮换。
4. 安装两个回环 systemd 服务 8896/8897。
5. 用本地 MCP tools/list 检查精确的 13 个工具，**不会调用开关机申请**。
6. 定位唯一的 jipite.borealos.cn TLS Nginx server block；安装 /mcp/ 路由并 nginx -t、reload，失败自动恢复原配置。保留原三个插件和全部现有 HTTPS 服务。

安装后，在 VPS 私有终端查看仅供插件设置填写的 URL：

    sudo sh -c 'printf https://jipite.borealos.cn/mcp/; cat /etc/comfyui-director-hub.token'

**不要把私密 URL、令牌、Microsoft ID Token、GPU SSH 私钥、配对码发到聊天、截图或 GitHub**。只粘贴到 ChatGPT 自定义 MCP 插件的 Server URL 设置。

## 实测顺序（新旧并行）

1. 在 ChatGPT 注册新插件「Director Hub」，旧三个插件**暂时不要删除**。
2. 新 Hub 连接后先调用 get_gpu_power_status；GPU 即使关机也应该返回真实状态。
3. 调用 get_studio_status、get_queue_summary；如果返回 backend_unavailable，检查 GPU 端是否运行 Director 8790 和 SSH -R 18790，而不是重新注册/换域名。
4. 用 Hub request_gpu_start 创建申请，在吉皮提审批页手动刷新并使用指纹批准，然后再次查询 GPU state。申请会产生潜在 GPU 费用，不作为自动健康检查。
5. 关机前必须完成视频文件持久化校验、确认 ComfyUI 队列为空并可从 VPS 读取；Hub request_gpu_stop 才能创建申请，手机指纹批准后继续查真实 Stopped。**队列不可读时拒绝开关机中的关机操作，禁止绕过。**
6. 等新 Hub 的读、申请、指纹审核、执行和 GPU 自动回连都通过后，才在 ChatGPT 删除旧三个连接。

## 当前部署限制

GitHub 的 CI 测试、代码发布不等于 VPS 部署。当前 ChatGPT 能用的三个旧插件仍然存在，新 Hub 必须在 VPS 运行上面的安装命令，并在 ChatGPT 插件设置里接入。GPU 恢复回连也需要真实运行中检查，不能凭 SSH 脚本存在就声称已修复。

## 离线自检

    python3 -m unittest discover -s vps-control/tests -p 'test_hub_v05.py' -v
    bash -n vps-control/install-hub-v05.sh
    python3 -m py_compile vps-control/hub_app.py vps-control/hub_rpc.py vps-control/hub_bridge.py

不会发送 GPU 开关机申请，也不会启停 GPU。
