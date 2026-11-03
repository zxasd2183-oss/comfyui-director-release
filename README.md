# ComfyUI Director — Signed Release Channel

这是 **ComfyUI Director** 的自动更新发布仓库，供优云智算 GPU 上的 Director Supervisor 检查已签名版本。当前部署仍为只读 MCP 网关，不会远程执行生成或开关 GPU。

## 安全架构

- GitHub Actions 从固定版本的 `runtime_vX.Y.Z.b64` 构建发布 ZIP。
- 发布时使用 GitHub Actions Secret `DIRECTOR_SIGNING_PRIVATE_HEX` 进行 **Ed25519 签名**。
- GPU 的 Supervisor 使用你安装时锁定的**公钥**验证 `manifest.json` 的签名，校验 ZIP SHA256，在队列持续空闲时升级网关，健康检查失败则回滚。
- **严禁提交私钥、MCP 访问密钥、ComfyUI 配置和素材。** 本仓库为 Public。

## 首次配置（尚未完成）

1. 在你信任的电脑上，用先前 V3 安装包内的 `release_tools.py` 创建 Ed25519 密钥对：`python3 release_tools.py keygen --private-file ~/director_signing.hex`。需要 `pip install cryptography`。
2. 到仓库 Settings → Secrets and variables → Actions，创建 **`DIRECTOR_SIGNING_PRIVATE_HEX`**，粘贴私钥十六进制字符串。不在聊天中发送私钥。
3. 到 Settings → Pages → Build and deployment，选择 **GitHub Actions**。
4. 版本经审核后，在 GitHub 推送标签 `v0.3.0`，触发 `Publish signed Director release`。
5. 发布成功后，HTTPS 清单预计位于 `https://zxasd2183-oss.github.io/comfyui-director-release/manifest.json`。以 GitHub Pages 页面实际地址为准。
6. 在优云智算运行 V3 安装程序，并通过 `configure_updates.py` 指定上述清单 URL 和**公钥文件**。

## 重要限制

本仓库目前只管理网关更新；Supervisor 本身不远程自更新。首次部署需你操作服务器一次；签名私钥必须由你掌握。**在签名 Secret 和 Pages 配置完成前，请勿认定自动更新已经上线。**
