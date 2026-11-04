# Director VPS V0.3 — ChatGPT 申请 + 独立网页二次审批

本模块已经加入 GitHub。**GPU 目前保持关机，不需要为开发而开机。**

## 已验证的事实

- 原有 `Director VPS` 只读 MCP（V0.1）继续运行在 `127.0.0.1:8890`，旧桥接服务 `8891` 不修改。
- V0.2 的 `director-powerctl` 交互式本地开关机已经在实际优云智算 GPU 上验证。
- V0.3 用新的独立 MCP 处理**申请**，使用单独的、需手机动态码的网页处理**最终审批**。
- ChatGPT **不能**通过 MCP 工具直接调用启动/停止 API。写入工具只插入 5 分钟有效的申请。
- 所有服务默认只绑定 VPS `127.0.0.1`；公网接入要另配 HTTPS/访问控制。以下临时隧道仅用于测试，长期请配置 OAuth / Cloudflare Access 等强身份认证。

## 在广州 Ubuntu VPS 上安装

在已安装 V0.2 的 VPS 上：

```bash
cd ~/comfyui-director-release
git pull --ff-only
cd vps-control
sudo bash install-power-v03.sh
sudo systemctl is-active director-power-mcp director-power-approval director-power-bridge
```

预期三项均为 `active`。该安装器创建：

| 本地端口 | 服务 | 作用 |
|---|---|---|
| 8890/8891 | 既有只读 MCP + 桥 | **原样保留** |
| 8892 | 独立 Power Requests MCP | 创建申请、查询申请状态 |
| 8893 | 审批网页 | 在浏览器输入 TOTP 验证码 + 确认短语 |
| 8894 | 新的隐私路径 MCP 桥 | 仅用于将 8892 安全地接入测试隧道 |

**安装期间不会调用任何实际开关机接口。**

## 一次性设置手机验证器

V0.3 首次安装自动在 VPS 生成私密 TOTP 种子文件，永远不要发给 ChatGPT、提交 GitHub、截图、转发或记录到日志。

只有在 VPS 本地输入下列命令时，才会显示用于手机验证器配对的种子：

```bash
sudo python3 - <<'PY'
from urllib.parse import quote
seed = open('/etc/comfyui-director-otp.seed', encoding='ascii').read().strip()
print('账户名称: Director VPS GPU')
print('类型: TOTP / 基于时间 / 6位 / 每30秒')
print('手动输入密钥:', seed)
print('或复制 otpauth URI 到受信任的验证器:')
print('otpauth://totp/Director%20VPS:GPU?secret='+seed+'&issuer=Director%20VPS')
PY
```

使用你自己的手机验证器添加该 TOTP 账户。**验证码只在独立审批网页输入，不要在 ChatGPT 中发送。**

需要准确的 VPS 系统时间；建议启用 NTP 时间同步。

## 测试 ChatGPT 能否调用写入 MCP 工具

在 VPS 另开终端运行：

```bash
cloudflared tunnel --url http://127.0.0.1:8894
```

记录它给出的 `https://mcp-xxxx.trycloudflare.com`，同时在 VPS **本地**查看新桥接令牌：

```bash
sudo cat /etc/comfyui-director-power-mcp.token
```

在 ChatGPT → Plugins → Add custom MCP server，新建 **Director Power Requests**。填写 Server URL：

```text
https://mcp-xxxx.trycloudflare.com/mcp/<V0.3新随机令牌>
```

该地址不是旧 `Director VPS` 的 URL。**只在 ChatGPT 插件设置里填写，不要把完整 URL 发到聊天或 GitHub。**

新 MCP 有三个工具：

- `request_gpu_start`：明确标注为 **write**，只创建开机申请（不启动 GPU）
- `request_gpu_stop`：明确标注为 **write**，只创建关机申请（须预检查队列）
- `get_power_request_status`：**read-only**，查询申请进度

由于目前 GPU 已关机，可以先在 ChatGPT 中测试 `request_gpu_start`，只要**不打开审批网页批准，GPU 就不会启动、不会触发新的计算任务**。申请 5 分钟后自动失效。ChatGPT 如果不能连接写入工具，说明当前账户/连接权限没有放行，**不可改造或误标注只读来绕过**。

## 独立审批网页

在 VPS 再开一个终端，单独建立测试用 HTTPS 隧道：

```bash
cloudflared tunnel --url http://127.0.0.1:8893
```

本地查自己的审批路径密钥：

```bash
sudo cat /etc/comfyui-director-approval-route
```

在**自己电脑/手机浏览器**打开：

```text
https://approve-xxxx.trycloudflare.com/approve/<审批路径密钥>
```

用 ChatGPT 返回的 `request_id` 查询审批申请，页面会展示即将执行的操作。**输入手机 TOTP 动态码、准确的操作短语，并勾选风险确认**，VPS 才会重新检查实例和队列，然后向优云智算发送操作。

- 预期开机用户输入：`START GPU`（可能开始计费）
- 预期关机用户输入：`STOP GPU`（须确认所有数据持久化）
- 请求 ID 为高熵随机值；验证码最多尝试 5 次；成功用过的 30 秒窗口验证码不能复用。
- 同一时刻最多有一张待审批申请；有效期 5 分钟；数据库记录不可重试的操作结果和脱敏审计事件。
- 即使审批通过，响应中的 `submitted` **只代表云平台接收请求**；最终必须再通过 `Director VPS.get_gpu_power_status` 查询 `Running` 或 `Stopped`。
- 如果提交后的云 API 超时，系统标记 `error` / `provider_request_uncertain_check_status`，禁止同一申请再次调用。这时**先查询真实状态，不要直接重复启动/关机**。
- 若 GPU 运行中但 Director V3 队列不可达，新的关机申请会被拒绝（fail-closed）。

## 当前测试环境的限制

- **只允许短期试用**：Quick Tunnel 的域名随机，不保证长期可达。当前试验使用随机 MCP 路径和独立网页 TOTP；长期公开服务应采用符合 MCP/ChatGPT 要求的 OAuth 和独立的 Cloudflare Access/登录认证。
- 所有本地服务默认只监听 `127.0.0.1`。不要打开 VPS 的 `8890~8894` 端口，也不要把 `8892` 原始 MCP 或 `8893` 原始 HTTP 明文公网化。
- 当前 **独立审批服务** 需要额外 HTTPS 隧道；Cloudflare Named Tunnel + 稳定域名是后续优化，不要把临时隧道当成正式的自动化运行链路。
- 现有 `Director VPS` 插件保持只读，不会静默变成写入工具。
- UCloud SDK 日志已在 `power_ops.py` 和 `api.py` 关闭，避免实例响应的敏感字段出现在日志。但其他程序（如 `compshare` CLI）仍需你单独检查日志配置。
- 不论 SDK、ChatGPT 还是浏览器返回什么，**不要把 OTP、密钥、完整私密 MCP URL 粘贴到聊天里**。

## 相关官方文档

- [ChatGPT 自定义 MCP 服务器（读写工具）](https://developers.openai.com/api/docs/guides/custom-mcp-server)
- [ChatGPT MCP 连接及写入确认](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)
- [优云智算开机 API](https://www.compshare.cn/docs/gpus/instance/startcompshareinstance)
- [优云智算关机 API](https://www.compshare.cn/docs/gpus/instance/stopcompshareinstance)
