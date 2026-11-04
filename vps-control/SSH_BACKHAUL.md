# Director GPU -> 广州 VPS：固定 SSH 反向回连（无 Cloudflare）

这是 borealos.cn 五站点 Nginx HTTPS 已生效后，director.borealos.cn 真正连上 GPU 的下一步。**GPU 当前 Running（Postpay）可能持续产生费用。**

目标：GPU 的 127.0.0.1:8790 通过独立的 SSH -R 隧道，只映射到**自有广州 VPS 的 127.0.0.1:18790**。Nginx 的 director.borealos.cn 私密 MCP 路由再转给本地 18790。GPU 无须公网入站端口，也不需要托管域名。实例关机断连、开机在 /start.d 自动重连，ChatGPT 地址不变。

## 1. GPU：生成专用公私钥

在优云智算 GPU 的 root 终端：

    install -d -m 0700 /root/.ssh
    test -f /root/.ssh/director_backhaul_ed25519 || ssh-keygen -t ed25519 -N '' -f /root/.ssh/director_backhaul_ed25519 -C director-gpu-backhaul
    chmod 0600 /root/.ssh/director_backhaul_ed25519
    cat /root/.ssh/director_backhaul_ed25519.pub

只把**公钥**复制到你自己的 VPS。私钥不要给 VPS、ChatGPT 或 GitHub。无口令私钥仅用于无人值守连接，靠 root 文件权限与 VPS 专用账户限制保护；GPU 被回收时务必撤销旧公钥。

## 2. 自有广州 VPS：创建最小权限 SSH 账户

在 VPS 已经建立的管理员 SSH 会话：

    sudo id directorlink >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /home/directorlink --shell /usr/sbin/nologin directorlink
    sudo passwd -l directorlink
    sudo install -d -o directorlink -g directorlink -m 0700 /home/directorlink/.ssh
    sudo touch /home/directorlink/.ssh/authorized_keys
    sudo chown directorlink:directorlink /home/directorlink/.ssh/authorized_keys
    sudo chmod 0600 /home/directorlink/.ssh/authorized_keys
    sudoedit /home/directorlink/.ssh/authorized_keys

添加一行，用 GPU 第 1 步的真实 Ed25519 **公钥**替换示例：

    restrict,port-forwarding,permitlisten="127.0.0.1:18790" ssh-ed25519 AAAA... director-gpu-backhaul

务必在 VPS 的有效 sshd_config 末尾为此用户配置专用 Match User（如果已有 Match 条件，请核实匹配优先级）：

    Match User directorlink
        PubkeyAuthentication yes
        PasswordAuthentication no
        KbdInteractiveAuthentication no
        AllowTcpForwarding remote
        PermitListen 127.0.0.1:18790
        GatewayPorts no
        X11Forwarding no
        AllowAgentForwarding no
        PermitTTY no
        MaxSessions 0

不要在修改过程中断开当前管理员 SSH 连接。验证：

    sudo sshd -t
    sudo sshd -T -C user=directorlink,host=127.0.0.1,addr=127.0.0.1 | grep -E '^(allowtcpforwarding|permitlisten|gatewayports|passwordauthentication|kbdinteractiveauthentication|maxsessions) '
    sudo systemctl reload ssh

有效配置必须只允许 remote forwarding，监听 127.0.0.1:18790，禁止密码与会话。不要在防火墙开放 18790；它是回环端口。

## 3. GPU：核对 VPS host key，创建 SSH 配置

先从**可信 VPS 管理会话**取得 VPS 的 SSH 主机 Ed25519 公钥指纹：

    sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub

在 GPU 终端（替换你实际的 VPS 公网 IP 与 SSH 端口）：

    ssh-keyscan -p VPS_SSH_PORT -t ed25519 VPS_PUBLIC_IP > /root/.ssh/director_backhaul_known_hosts
    chmod 0600 /root/.ssh/director_backhaul_known_hosts
    ssh-keygen -lf /root/.ssh/director_backhaul_known_hosts

**严格比对 GPU 获取的指纹与 VPS 可信会话读出的指纹**。不能因为 ssh-keyscan 成功就认为可信，更不可以关闭 StrictHostKeyChecking。

在 GPU 私有文件 /root/.ssh/director_backhaul_config 写入以下内容并 chmod 0600：

    Host director-backhaul
        HostName VPS_PUBLIC_IP
        Port VPS_SSH_PORT
        User directorlink
        IdentityFile /root/.ssh/director_backhaul_ed25519
        IdentitiesOnly yes
        UserKnownHostsFile /root/.ssh/director_backhaul_known_hosts
        StrictHostKeyChecking yes
        BatchMode yes
        ExitOnForwardFailure yes

## 4. 先验证 SSH 反向隧道，再安装自动回连

在 GPU：

    curl -fsS http://127.0.0.1:8790/health

如已安装的 V3 supervisor 没启动，可以在 GPU 使用：

    bash /root/.comfyui-director/controller/start.sh

不要启动第二个 ComfyUI，不要停 Slink 8765。

GPU 终端运行下面的命令（命令保持前台不退出，是正常的）：

    ssh -F /root/.ssh/director_backhaul_config -NT \
      -o ExitOnForwardFailure=yes \
      -R 127.0.0.1:18790:127.0.0.1:8790 director-backhaul

**另一个 VPS 终端**验证：

    curl -fsS http://127.0.0.1:18790/health
    sudo ss -ltn | grep 18790

必须看到 V3 0.3.0 health 数据，且 VPS 监听地址只能是 127.0.0.1。手动验证完成后退出该 GPU 端 SSH 命令，安装正式开机钩子：

    mkdir -p /root/director-backhaul
    curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/gpu-ssh-backhaul.sh -o /root/director-backhaul/gpu-ssh-backhaul.sh
    curl -fsSL https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main/scripts/install_gpu_ssh_backhaul.sh -o /root/director-backhaul/install_gpu_ssh_backhaul.sh
    bash /root/director-backhaul/install_gpu_ssh_backhaul.sh
    bash /start.d/90-director-gpu-backhaul.sh

这会启动自动重连程序；GPU 开机时 /start.d 再执行。脚本只连接已安装的 V3，不运行云 GPU 开关机 API 或 ComfyUI 视频生成。必须实测 GPU 停机后数据和 /start.d 持久化是否保留；不要为测试持久化而无谓重复付费开机。

## 5. 一次性更新插件 URL、VPS 安全队列入口

ChatGPT 插件使用如下正式 Server URL，仅替换域名，原随机密钥路径保持不变：

- Director V3: https://director.borealos.cn/mcp/GPU_ORIGINAL_PRIVATE_TOKEN
- Director VPS: https://status.borealos.cn/mcp/VPS_ORIGINAL_READONLY_TOKEN
- Director Power Requests: https://power.borealos.cn/mcp/VPS_ORIGINAL_POWER_TOKEN
- 审批网页（需要额外 Basic Auth + 手机 TOTP）: https://approve.borealos.cn/approve/ORIGINAL_PRIVATE_ROUTE

真正的私密 token 不得发到 ChatGPT 聊天或 GitHub。首先通过正式插件重新查询 GPU 状态、V3 工作室状态、VPS Power Health；**不要先关闭旧 cloudflared 临时隧道**。

在 VPS 用 sudoedit 编辑 /etc/comfyui-director-control.env，设置 DIRECTOR_GPU_MCP_URL 为上面 Director V3 的真实 HTTPS 私密 MCP URL（文件仍应 root 拥有、mode 0600），然后：

    sudo systemctl restart director-power-mcp director-power-approval

这一项保留了关机前必须确认 ComfyUI 队列为空的 fail-closed 安全限制。固定域名不等于免审批，继续使用独立手机 TOTP。

## 6. acme.sh 证书自动续期 / Nginx Reload 核查

你已配置好五个域名 HTTPS 与 acme.sh cron，无需重签证书。

在最初安装 acme.sh 的 VPS 用户下：

    ~/.acme.sh/acme.sh --list
    ~/.acme.sh/acme.sh --info -d CERT_MAIN_DOMAIN

CERT_MAIN_DOMAIN 应为 acme.sh 列出的证书主域名（五域名 SAN 证书不一定以 director 为主域名）。本地查看 Le_RealKeyPath、Le_RealFullChainPath 是否匹配 Nginx 当前实际路径 /etc/nginx/certs/borealos-new/，以及 Le_ReloadCmd 是否为成功更新后执行 nginx -t 和 systemctl reload nginx 或等效命令。

如果缺失 reloadcmd，应使用已有证书**准确的** key-file 与 fullchain-file 路径重做 acme.sh --install-cert 配置，不要猜测文件名、不要强制重新签发证书。参考 https://github.com/acmesh-official/acme.sh#3-install-the-certificate-to-apachenginx 。

手动语法检查并安全重载当前 Nginx（这不会触发证书续签）：

    sudo nginx -t && sudo systemctl reload nginx

## 7. 关掉真正的旧临时隧道（NOT 服务本身）

正式 ChatGPT MCP 连接验证成功以后，在 VPS 检查：

    ps -eo pid,args | grep '[c]loudflared.*tunnel.*--url'

只停止经过确认的旧 Quick Tunnel PID。**不要 pkill cloudflared**，不要 stop director-vps-bridge、director-power-bridge、director-power-approval；本地 8891/8894/8893 正是 Nginx 的后端，必须保持运行。

参考：OpenSSH PermitListen / AllowTcpForwarding remote https://man.openbsd.org/sshd_config ，CompShare /start.d https://compshare.cn/docs/operation/gpufaq 。
