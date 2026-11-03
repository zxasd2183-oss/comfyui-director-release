# ComfyUI Director — Ubuntu VPS Control Center (只读试运行)

部署位置：**广州 Ubuntu VPS**（不是优云智算 RTX 5090 容器）。已经连通 ChatGPT 的 GPU Director V3 不改动。

## 已实现
- `get_control_center_status`：读取 VPS 控制中心的配置和版本状态。
- `get_gpu_power_status`：通过优云智算官方 UCloud SDK 的 `DescribeCompShareInstance` 查询实例状态；GPU 关闭后 VPS 仍可以查询。
- 只返回白名单字段，**不返回**优云智算响应里的 `Password`、`FileBrowserPassword`、SSH 信息、IP 或 API 密钥。
- `systemd` 持续运行，默认仅监听 `127.0.0.1:8890`。**没有开机、关机、生成视频的工具**。

## 安装（Ubuntu 22.04 / 24.04）

请在 **VPS 而不是 GPU** 上执行：

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv
git clone https://github.com/zxasd2183-oss/comfyui-director-release.git
cd comfyui-director-release/vps-control
# 审查代码后再运行
sudo bash install-ubuntu.sh
```

安装器会创建单独的 `directorctl` 系统账户、Python 虚拟环境和 systemd 服务；不会修改 GPU 的 ComfyUI 或 8790 端口。

然后**在 VPS 本机**填写优云智算账户中心 API 密钥（不是模型 API Key），以及目标 GPU 实例 ID：

```bash
sudoedit /etc/comfyui-director-control.env
sudo systemctl restart director-vps-control
sudo systemctl status director-vps-control --no-pager
```

配置字段：
- `COMP_PUBLIC_KEY` / `COMP_PRIVATE_KEY`：优云智算账户中心 → API 密钥，**不要发到聊天里或提交到公开 GitHub 仓库**。
- `COMP_UHOST_ID`：要查询的 GPU 实例 ID。
- `COMP_REGION` / `COMP_ZONE`：以实例实际地域、可用区为准；不能因为 VPS 在广州就填广州（该字段对应的是 GPU 实例，不是 VPS）。

## MCP 接入与安全

服务的本地地址是 `http://127.0.0.1:8890/mcp`。本版**没有公网 OAuth 身份认证**，所以**不要直接对公网开放 8890，更不要将匿名 Quick Tunnel 指向它**。下一阶段应配置符合 ChatGPT MCP 要求的 OAuth，或可正确授权的私有隧道，再创建 ChatGPT 插件。

广州 VPS 的跨境访问需要实测；公网域名还需要遵守云厂商要求及适用的中国大陆备案规定。

## 后续

下一步接入安全认证和 HTTPS；再加入经明确授权的 GPU 启停工具。关机前须验证 ComfyUI 队列和视频素材持久化成功；GPU 已离线时可以查询电源状态，但不能直接检查 ComfyUI 内存态。

相关官方文档：
- [优云智算查询实例](https://www.compshare.cn/docs/gpus/instance/describecompshareinstance)
- [优云智算开机](https://compshare.cn/docs/gpus/instance/startcompshareinstance)
- [优云智算关机](https://www.compshare.cn/docs/gpus/instance/stopcompshareinstance)
- [OpenAI 自定义 MCP 服务器](https://developers.openai.com/api/docs/guides/custom-mcp-server)
