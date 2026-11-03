# ComfyUI Director · 官方发布仓库

[![V3](https://img.shields.io/badge/Director-0.3.0-blue)](./bootstrap/install-v3.sh)

面向优云智算 GPU 上的 **ComfyUI + MiniMax H3**。这是已连接 ChatGPT Plus 的 Director **只读 MCP 网关**的发布源，不包含用户的模型权重、任务历史、MCP URL 密钥、云 GPU 密码或 API 凭证。

## 当前真实状态

- ✅ V3 **首次安装包**已发布到 `bootstrap/director-v0.3.0-bootstrap.tar.gz.b64`。
- ✅ [一键下载/校验/安装脚本](./bootstrap/install-v3.sh) 已发布；安装**不会停止 V1，也不会自动启动新网关**。
- ✅ [签名发布 GitHub Actions](./.github/workflows/publish.yml) 已配置，编排离线测试、Ed25519 签名和 GitHub Pages 部署。
- ⏳ **尚未启用自动更新**：需要仓库所有者设置签名密钥 Secret、启用 GitHub Pages，并在 GPU 上首次安装和绑定公钥。
- ⏳ V3 尚未在优云智算实机测试/切换；此前成功连接的 V1 仍独立运行。

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
   curl -fsS http://127.0.0.1:8765/health
   cat ~/.comfyui-director/status.json
   ```

以后若发布 **V3.1 或更高版本**，更新 GitHub 仓库内源代码归档及其 SHA256 校验值、调整 V3 工作流构建配置，并通过 GitHub Actions 生成新的签名清单。已运行的 Supervisor 仅在 ComfyUI 队列持续空闲后升级，失败会自动回滚。**Supervisor 本身不远程自更新**，以保留独立信任根。

## 安全边界

本发布包只读：不提供 GPU 启停、视频生成、删除任务、执行 Shell 命令等 MCP 写操作。不要把 `8188` 端口暴露公网；仅向 ChatGPT 暴露受控 HTTPS MCP 网关。初版通过随机 URL 密钥授权，只适合短期测试；正式公网部署应使用更强的身份认证并限制访问。

源代码目前采用压缩归档 + base64 形式托管，**不是可直接浏览的逐文件源代码仓库**；归档内容均可本地解压审查。下一版会改成逐文件源码管理，以便审核及持续集成。
