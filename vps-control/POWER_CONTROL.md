# Director VPS 电源控制 V0.2（本地确认版）

> 适用：广州 Ubuntu VPS 控制优云智算上海二 `cn-sh2 / cn-sh2-01` RTX 5090。**不改变**已通过 ChatGPT Plus 验证的只读 MCP 工具，也不修改 GPU 上的 Director V3。
>
> 本版只通过 **VPS 本地交互终端**发送启动和停止指令。**没有公网写入接口。** ChatGPT Plus 的自定义 MCP 已验证只读访问，尚未验证或获得写入权限，不会伪装成只读工具执行关机。

## 安装

在 **广州 VPS** 上（不在 GPU 上）：

```bash
cd ~/comfyui-director-release
git pull --ff-only
cd vps-control
sudo bash install-powerctl.sh
```

如仓库克隆在别的目录，请用实际路径。此脚本只把 `power_ops.py` 与 `powerctl.py` 部署至 `/opt/comfyui-director-control` 并安装系统管理员命令 `director-powerctl`，不会重启任何服务、改动 SSH/防火墙、也不会执行 GPU 电源操作。

## 两步操作

查询 GPU 真实电源状态：

```bash
sudo director-powerctl status
```

在 GPU 已关机的情况下查看开机计划（不会产生开机费用）：

```bash
sudo director-powerctl plan-start
```

需要实际启动时，在 **VPS 上的交互终端**运行：

```bash
sudo director-powerctl apply-start
```

它会要求你输入精确确认短语 `START GPU AND ACCEPT BILLING`，然后再次查询状态，只在 GPU 为 `Stopped` 时调用 `StartCompShareInstance`。这可能开始新的 GPU 计费。API 返回 `accepted` 只代表云平台接收请求，不代表开机已完成；随后再次运行 `status` 检查。

## 安全关机必须能查到 ComfyUI 队列

**推荐直接复用 GPU 上 Director V3 的只读 MCP**，不需要把 ComfyUI 8188 暴露公网。在 VPS 上以 root 权限编辑：

```bash
sudoedit /etc/comfyui-director-control.env
```

增加一行（只保存在该 0600 文件；实际地址不要发到聊天、GitHub 或截图）：

```ini
DIRECTOR_GPU_MCP_URL=https://你的Director-V3-HTTPS域名/mcp/你的随机访问密钥
```

该地址必须可由广州 VPS 访问，并指向**GPU 上真实的 Director V3**，且 V3 可调用 `get_queue_summary`。不要把 `127.0.0.1:8790` 直接填到广州 VPS 的配置里——那个地址在 VPS 上指向 VPS 自己。

也可设置 `DIRECTOR_GPU_QUEUE_URL=https://经过认证的队列只读端点/queue` 作为备选，但切勿暴露未经认证的 ComfyUI 8188 端口。若同时配置，以 MCP URL 为准。

先预检查：

```bash
sudo director-powerctl plan-stop
```

只有 **GPU 为 Running、不是抢占式实例、队列通过可信 HTTPS 查询且 running/pending 均为0** 时，才会返回 `allowed:true`。若无法访问、JSON 格式异常、队列非空或状态不符，则拒绝继续。

确认 ComfyUI 输出文件、模型和素材**确实已保存至持久化存储**之后，才执行：

```bash
sudo director-powerctl apply-stop
```

再次检查队列与状态，然后要求精确输入 `STOP GPU - OUTPUTS VERIFIED SAVED`。这不是自动持久化验证；确认文件已保存仍由操作者负责。调用成功只代表已发送停机请求，完成状态由 `sudo director-powerctl status` 再查。

若无法访问 GPU 队列，**自动拒绝关机，没有绕过参数**。此时请通过优云智算控制台手动关机，或修复队列连接；不要为了省钱移除安全检查。

## 测试和版本状态

GitHub Actions：20 项隔离模拟测试已通过，包括异常、红线与重检查；**没有在你的付费 RTX 5090 上实际执行开/关机试验**。

<https://github.com/zxasd2183-oss/comfyui-director-release/actions>

## 下一步：真正从 ChatGPT 控制电源

必须另行实现**强身份认证、一次性本地批准、短期有效授权票据、操作审计、幂等/限流**等措施，并先确认 ChatGPT Plus 是否支持对自定义 MCP 的写入工具。不能把 `powerctl.py` 通过当前只读桥接器直接开放公网，更不能通过伪装只读 MCP 工具执行开关机。

官方 API：
- [StartCompShareInstance](https://www.compshare.cn/docs/gpus/instance/startcompshareinstance)
- [StopCompShareInstance](https://www.compshare.cn/docs/gpus/instance/stopcompshareinstance)
