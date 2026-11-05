# Director Hub V0.6 — VPS 一体化升级

本次不新建 ChatGPT 插件。保留现有 Director Hub、原域名、原私密 token 和原有 13 个工具，合并 VPS 内部的读状态与电源申请核心。

## 架构

- ChatGPT → jipite.borealos.cn → Hub MCP 8898 / 私密桥 8899：原 13 工具（8 GPU、2 VPS、3 电源申请），Brain Link 启用后共 19 工具。
- 8 个 GPU 只读工具 → SSH -R 本地 18790 → GPU 8790：不变。
- 2 个 VPS 状态查询 + 3 个电源申请工具 → 统一受保护 VPS 核心 **8892**，不再依赖旧独立状态服务 8890。
- 吉皮提 Microsoft 身份、设备绑定、指纹私钥签名 → 原有独立 8895 手机 API：不变；实际电源执行始终需要手机批准和服务器最终安全复核。
- 原 8890/8891 服务可以在正式切换后退役；GPU 关机时不需要为了更新而重新开机。

合并的是逻辑和维护入口，不是把公网 MCP、实际电源执行、手机身份私钥都放在一个高权限进程。

## 第一步：升级与并行验收（无 GPU 计费操作）

在 VPS 私人 SSH 终端执行：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash vps-control/install-hub-v06.sh

脚本检查服务正常和 SQLite 没有正在审批/执行的操作，创建 root-only 备份，然后升级原有 8892 和 Hub 代码、重启两个 MCP 服务，不动吉皮提、不动 Nginx/Hub token，不改手机配对。

自动验收必须满足：8892 精确六工具（两只读状态、三个原申请、一个健康诊断）；Hub 8898 当前为十九工具；两端通过真实 CompShare 状态只读检查；**不调用任何开关机申请或实际电源 API**。验证失败自动尝试还原文件与服务单元。

升级后直接在原 ChatGPT Director Hub 调用 get_gpu_power_status，应该仍看到云端真实状态。GPU 关机时，工作室查询 backend_unavailable 是预期行为。

## 第二步：安全退役旧状态进程（仅第一步成功后）

在 ChatGPT 中验证 Hub 查询正确，确认没有其他客户端使用旧 status.borealos.cn 后，再于 VPS 执行：

    cd ~/comfyui-director-release
    sudo bash vps-control/install-hub-v06.sh --retire-legacy-vps

脚本再次验证核心，禁用旧 director-vps-control 与 director-vps-bridge 服务。遇到仍在运行的旧 Named Tunnel 则拒绝退役，避免破坏其他客户端。不要停止 8892：它是统一核心和吉皮提审批依赖。

## 回滚

脚本输出 root-only 私有备份路径，升级失败时尝试自动还原旧程序/单元并重启 MCP。备份原文件：

- /opt/comfyui-director-power/power_ops.py、power_write_mcp.py
- /opt/comfyui-director-hub/hub_rpc.py、hub_app.py
- /etc/systemd/system/director-hub-mcp.service

恢复 V0.5 时不要改 SQLite、手机号绑定、Hub token 或 HTTPS 配置。如果旧状态服务已退役并需要恢复，请在 VPS 执行：

    sudo systemctl enable --now director-vps-control director-vps-bridge

代码 CI 通过不等于生产 VPS 已部署。V0.6 需在 VPS 真机进行只读链路验收；不为验证代码主动启动 GPU。
