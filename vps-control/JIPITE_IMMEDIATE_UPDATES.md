# 吉皮提：发布成功立即同步到 VPS（保留每小时兜底）

## 更新链路

1. GitHub Actions 为 `main` 分支的新版本构建、正式签名并创建 `jipite-vX.Y.Z` Release。
2. 只有原有 APK 构建工作流**全部成功（含 Release 发布）**，独立的 `jipite-immediate-sync.yml` 才自动启动。
3. GitHub Actions 获得仅数分钟有效的 OIDC 身份 JWT，通过 HTTPS `POST /app-updates/notify` 通知 VPS。
4. VPS 验证 GitHub 公开签名公钥与 JWT 的发行者、audience、不可变仓库所有者/仓库 ID、`main` 分支、工作流路径、事件类型和有效期。**无 SSH 密钥，无长期共享 Token，无 Microsoft/GPU 凭据**。
5. 验证通过后，127.0.0.1:8896 的非 root 服务调用原来的只读同步脚本。该脚本只从 GitHub 官方 Release 下载 APK，先验 SHA-256，再原子更新 `latest.json`。
6. 手机只连接 `https://jipite.borealos.cn/app-updates/`，继续做签名证书、包名、版本号、摘要检查；安装始终由 Android 用户确认。
7. 如果 GitHub 通知被遗漏、证书服务暂时不可用或瞬时网络失败，**原每小时 systemd timer 不变**，继续兜底同步。

同步通常在发布成功后数十秒内开始，但受 GitHub Actions 排队时间、网络和 APK 下载时间影响，不保证零延迟。整个流程不会审批 GPU 操作，也不修改 GPU 电源开关权限。

## VPS 首次升级（唯一需要人工操作的一次）

确保之前 `install-jipite-vps-updates.sh` 已成功，仍然能看到 `jipite.borealos.cn/app-updates/latest.json`。

在自己的 VPS SSH 终端：

```bash
cd ~/comfyui-director-release
git pull --ff-only
sudo bash vps-control/install-jipite-immediate-sync.sh
```

本次脚本只增加一个隔离的 `/app-updates/notify` Nginx 路由和非 root systemd 服务，修改原 Nginx 片段前会备份；任何语法检查失败都会回滚新路由。原本的 `/api/v1/mobile/`（Microsoft 身份验证）和静态 APK 下载路由保持原样。**不需要重新构建或安装吉皮提 APK**。

脚本还会**立即执行一次已有的 APK 同步**，用于更新在首次部署之前就已发布的版本。

## 验收

不需要任何账户凭据的只读/未授权检查：

```bash
sudo systemctl is-active jipite-immediate-notify.service
sudo systemctl is-active jipite-android-update-sync.timer
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' --data '{}' \
  https://jipite.borealos.cn/app-updates/notify
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' --data '{}' \
  https://jipite.borealos.cn/api/v1/mobile/pending
curl -fsS https://jipite.borealos.cn/app-updates/latest.json
```

预期状态：通知服务 `active`、定时器 `active`、**未授权通知 401**、**微软审批接口 401**、更新清单 HTTPS 200 并包含版本号及 SHA-256。

下一次新的吉皮提 APK 发布时，GitHub `Notify Jipite VPS immediately after signed release` 应自动运行，返回 **HTTP 202**。VPS 端日志：

```bash
sudo journalctl -u jipite-immediate-notify.service -n 40 --no-pager
sudo journalctl -u jipite-android-update-sync.service -n 40 --no-pager
```

若即时通知失败，**不要删除定时器或关闭 APK 签名检查**。如果服务的 JWT 校验拒绝通知，先核实仓库 ID 和 GitHub Actions 运行记录，勿为了方便允许未认证的 POST。

## 安全边界

- 只有官方 `workflow_run` 成功通知，不接受任何可由请求方指定的 APK 地址、命令、GPU 任务、配对信息或文件。
- OIDC 授权基于 GitHub Actions **不可变 Owner / Repo ID**（此仓库创建于 2026-11-03）；拒绝名称复用和跨仓库触发。
- 无法验签、令牌过期、GitHub JWKS 故障时拒绝触发，同步定时器仍可独立运行。
- 服务仅监听 VPS 回环接口；Nginx 才有 HTTPS 公网入口，且仅暴露精确的 `/app-updates/notify`。
- VPS 同步仍下载公开 Release，经摘要校验；手机仍核验 APK 证书和版本，不允许静默安装。
- 本阶段没有打开 GPU 电源写权限，也没有改变 TOTP 或 Microsoft 账户审批逻辑。
