# ComfyUI Director · 官方发布仓库

[![V3](https://img.shields.io/badge/Director-0.3.0-blue)](./bootstrap/install-v3.sh)

面向优云智算 GPU 上的 **ComfyUI + MiniMax H3**。这是已连接 ChatGPT Plus 的 Director **只读 MCP 网关**的发布源，不包含用户的模型权重、任务历史、MCP URL 密钥、云 GPU 密码或 API 凭证。

## 当前真实状态

- ✅ V3 **首次安装包**已发布到 `bootstrap/director-v0.3.0-bootstrap.tar.gz.b64`。
- ✅ [一键下载/校验/安装脚本](./bootstrap/install-v3.sh) 已发布；安装**不会停止 V1，也不会自动启动新网关**。
- ✅ [签名发布 GitHub Actions](./.github/workflows/publish.yml) 已配置，编排离线测试、Ed25519 签名和 GitHub Pages 部署。
- ⏳ **尚未启用自动更新**：需要仓库所有者设置签名密钥 Secret、启用 GitHub Pages，并在 GPU 上首次安装和绑定公钥。
- ⏳ V3 尚未在优云智算实机测试/切换；此前成功连接的 V1 仍独立运行。

## V0.6 · 吉皮提安卓原生推送审批器（源码已提交，尚未部署）

[安卓工程](./android-jipite/README.md) ｜ [VPS 移动审批后端和安全部署手册](./vps-control/MOBILE_V06.md)

个人 Microsoft 账号登录用于初次绑定手机；Firebase Cloud Messaging（可用时）负责推送开关机申请；Android Keystore + 强生物识别对本次申请签名；VPS 验签之后才重新检查 GPU 状态与 ComfyUI 队列并执行一次 API。旧的独立 TOTP 网页先保留为灾难恢复备用。无需日常打开审批网站，也无需修改 `borealos.cn` 五个固定域名。

**注意：Android 构建 CI 使用虚拟 Firebase 项目，仅做源码编译检查；必须先完成你自己的微软 Android App Registration、签名回调和 Firebase 项目配置，才可在真实手机上推送审批。部署前没有任何新代码实际操作 GPU 电源。**

## 固定域名 borealos.cn（推荐，不再重复配置）

[一次性配置阿里云 DNS + 自有 VPS HTTPS + GPU 出站 SSH 反向隧道](./FIXED_DOMAIN.md)：
`director.borealos.cn`、`status.borealos.cn`、`power.borealos.cn`、`approve.borealos.cn`。
这四个 DNS 主机名应在阿里云 DNS 配置为指向自有广州 VPS 的 A 记录，**不是出租 GPU**；并先确认中国内地服务器的 ICP 备案要求。原 Cloudflare Named Tunnel 提议已弃用，当前方案不依赖 Cloudflare。DNS/HTTPS/SSH 反向隧道尚未真正部署，不能只修改文档。

## GPU 再次开机后：一键恢复 V3 连接

GPU 开关机由广州 VPS 的 Director Power Requests 独立审批；**运行中的 GPU 与连通的 ComfyUI MCP 是两回事**。之前在 GPU 内启动的 Cloudflare Quick Tunnel 会随着 GPU 关机而消失，其临时 HTTPS 域名不会自动恢复。

在**优云智算 GPU 终端**执行（不是广州 VPS）：

```bash
curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/recover_gpu_v3.py -o ~/recover_gpu_v3.py
python3 ~/recover_gpu_v3.py --tunnel
```

工具只检查本机 ComfyUI 8188 和 Director V3 8790；若 Supervisor 未响应，尝试运行**已安装**的 `~/.comfyui-director/controller/start.sh`。它不会安装软件、运行视频任务、重启 ComfyUI 或调用 GPU 开关机 API。只有在 V3 自检通过时才运行新临时 HTTPS Tunnel。Cloudflared 必须已经安装。

将 GPU 终端最后输出的**完整私密 MCP URL**只填入 ChatGPT 的 `ComfyUI Director V3` 自定义连接设置（若不可修改则重新添加该插件）。**不要把私密 URL 或 `/mcp/<token>` 复制到聊天、GitHub、截图或日志。** 运行后可以在这里请求 `get_studio_status` 验证。

**必须同步 VPS 关机安全校验入口：** 在**广州 VPS** 用 `sudoedit /etc/comfyui-director-control.env` 将 `DIRECTOR_GPU_MCP_URL` 更新为刚得到的 GPU 端新 MCP URL，保持原始文件 root 拥有且权限 0600，然后执行：

```bash
sudo systemctl restart director-power-mcp director-power-approval
```

若不更新，V0.3 的安全关机申请将因为旧的队列地址不可达而被拒绝；绝不可因连不上队列就绕过安全检查。

上述方案属于短期联调：每次 GPU 重启 Quick Tunnel 都会换地址。长期无人值守需要固定域名的认证隧道（Cloudflare Named Tunnel / 等效方案），并在 GPU 启动环境中配置持久化服务；是否有 systemd 和持久化目录需要在 GPU 本机确认后再安装启动项。

## 当前实例的重要端口说明（2026-11-03）

**优云智算 Slink 使用 8765，ComfyUI Director V3 实际监听 8790。** 不要再用 `8765/health` 测试 Director，也不要停止 Slink。V3 已由实例上的 `director_supervisor.py` 管理；默认安装脚本中的 8765 仅是通用默认值，不适用于此实例。

### 不上传 ZIP，验证和连接 ChatGPT Plus

先验证 V3 和 8 个 MCP 工具是否已经可以在本地使用（不会生成视频）：

```bash
curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/connect_v3.py \
  -o ~/connect_v3.py
python3 ~/connect_v3.py
```

如果输出显示 `version: 0.3.0`、`port: 8790`、`Tools: 8`，创建一条新的临时 Cloudflare HTTPS 隧道：

```bash
python3 ~/connect_v3.py --tunnel
```

脚本会将完整的含私密 `/mcp/<secret>` 路径的 HTTPS URL 只显示在**你的终端**。**不要把该地址发到聊天、GitHub、截图或日志**。请在 ChatGPT 中**新建自定义 MCP 插件** `ComfyUI Director V3` 并填写完整 Server URL。创建新插件而不是刷新旧 V1，是为了强制新一轮工具发现；成功后应当出现 8 个工具，其中包含 `get_upgrade_readiness`、`audit_h3_workflow`、`get_h3_node_inputs`。旧插件在成功前可以保留。

本流程只读，不会修改 ComfyUI、执行视频生成或关闭 GPU。Quick Tunnel 仅用于短期测试，生产环境应改为具有正式身份认证的稳定 HTTPS 地址。

## 云端首次安装（无需手动上传 ZIP）

在**优云智算 GPU 终端**运行：

```bash
curl -fsSLo ~/director-install-v3.sh \
  https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/bootstrap/install-v3.sh
# 建议先查看脚本
less ~/director-install-v3.sh
bash ~/director-install-v3.sh
```

安装脚本会下载源码归档、验证归档 SHA256、解压、运行 19 项离线测试，然后安装 V3 到 `~/.comfyui-director/`。它会要求你在终端**隐藏输入**现有 ChatGPT 插件的 `/mcp/<secret>` 路径（不要发到聊天里）。安装过程中**不会终止正在运行的 V1 服务**，以免连接意外中断。

归档可信校验值（SHA256）：

```text
a4ceaf17af06c09a0ef3b18a568e6d100f196d9519701c4d31cffc104f84f204
```

注意：签名自动更新的公钥验签需要 GPU 上的 Python 环境能够导入 `cryptography`；如脚本提示缺失，请运行 `python3 -m pip install cryptography`。只读网关本身不依赖这个库。\n\n成功安装后再停掉旧 V1 Python 进程，并运行 `~/.comfyui-director/controller/start.sh` 切换到 V3；保留原有 Cloudflare Tunnel 连接，若域名没变就不需要在 ChatGPT 重建插件。

**请注意：** GPU 实例关机后，运行在 GPU 内的 Supervisor 也会停止；需要根据你实例的持久化与启动方式配置自动启动，不能只依靠 nohup。

## 配置真正的自动更新（一次性）

1. 在**个人可信电脑**上，用归档里的 `release_tools.py` 运行 `python3 release_tools.py keygen --private-file ~/director_signing.hex`（需先 `python3 -m pip install cryptography`）。**私钥只留在你的电脑，不上传 GPU、不发给 ChatGPT、不提交到此公开仓库**。
2. 在此仓库 **Settings → Secrets and variables → Actions** 新建 Secret：`DIRECTOR_SIGNING_PRIVATE_HEX`，值为私钥 HEX 字符串。将公钥文件 `director_signing.pub.hex` 上传到 GPU（公钥可公开）。
3. 在 **Settings → Pages → Build and deployment** 选择 **GitHub Actions**，然后在 Actions → `Publish signed ComfyUI Director to GitHub Pages` → `Run workflow`，版本填 `0.3.0`。
4. 确认 Pages 上已出现 `https://zxasd2183-oss.github.io/comfyui-director-release/manifest.json` 与 `manifest.json.sig`。
5. 在 GPU 配置发布源：
   ```bash
   python3 ~/.comfyui-director/controller/configure_updates.py \
     --manifest-url 'https://zxasd2183-oss.github.io/comfyui-director-release/manifest.json' \
     --public-key-file ~/director_signing.pub.hex
   ```
6. 启动 Supervisor 后检查：
   ```bash
   curl -fsS http://127.0.0.1:8790/health # 当前实例；其他实例以 config.json 的 port 为准
   cat ~/.comfyui-director/status.json
   ```

以后若发布 **V3.1 或更高版本**，更新 GitHub 仓库内源代码归档及其 SHA256 校验值、调整 V3 工作流构建配置，并通过 GitHub Actions 生成新的签名清单。已运行的 Supervisor 仅在 ComfyUI 队列持续空闲后升级，失败会自动回滚。**Supervisor 本身不远程自更新**，以保留独立信任根。

## 安全边界

本发布包只读：不提供 GPU 启停、视频生成、删除任务、执行 Shell 命令等 MCP 写操作。不要把 `8188` 端口暴露公网；仅向 ChatGPT 暴露受控 HTTPS MCP 网关。初版通过随机 URL 密钥授权，只适合短期测试；正式公网部署应使用更强的身份认证并限制访问。

源代码目前采用压缩归档 + base64 形式托管，**不是可直接浏览的逐文件源代码仓库**；归档内容均可本地解压审查。下一版会改成逐文件源码管理，以便审核及持续集成。
