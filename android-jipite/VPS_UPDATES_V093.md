# 吉皮提 v0.9.3 · VPS 应用内更新

> 目标：安卓手机不需要访问 GitHub。APK 通过自己的 `https://jipite.borealos.cn/app-updates/` 分发，安全审批仍独立使用 `/api/v1/mobile/`。

## 当前架构

```text
GitHub Actions (用原来的正式签名证书构建 APK)
    -> GitHub Releases (公开、版本不可覆盖)
    -> VPS 每小时同步（只读拉取、SHA-256 校验）
    -> /var/lib/jipite-updates/ （静态文件，无敏感数据）
    -> Nginx HTTPS /app-updates/ （公网）
    -> 吉皮提 v0.9.3（仅连接自己的 VPS）
    -> APK 二次校验签名、包名、版本、SHA-256
    -> Android 系统安装器，必须本人确认
```

手机不需要 Microsoft Token、VPS 配对码或 GPU 权限即可获取公开更新元数据和 APK。VPS 无需获得 APK 私钥（签名只在现有受信任的 GitHub Actions 构建中完成）。

## VPS 所有者只需执行一次

在**自己的 VPS SSH 终端**：

```bash
cd ~/comfyui-director-release
git pull --ff-only
sudo bash vps-control/install-jipite-vps-updates.sh
```

首次部署会：

1. 检查现有的 `director-mobile-v06` 和 `director-power-approval` 都是 active；
2. 创建不可登录的 `jipiteupdate` 系统用户、`/var/lib/jipite-updates` 静态发布目录；
3. 从 GitHub Releases 的**官方仓库公开资产**获取最新 `jipite-vX.Y.Z`，验证公布的 SHA-256、大小、URL 和标签，再原子写入 APK 与 `latest.json`；
4. 保留现有 `jipite-mobile.conf` 的 **/api/v1/mobile/** 审批规则，只增加独立的 `/app-updates/` Nginx 静态下载片段。修改前备份、`nginx -t` 后 reload，失败回滚；
5. 启用一个独立的只读同步服务及**每小时更新检查** timer。不会重启审批 API、关闭或打开 GPU，也不会暴露 Microsoft / GPU 密钥。

安装结束后，应看到：

```text
VPS APK mirror health: HTTP 200 (expected 200)
Hourly timer: active
```

如果 VPS 无法连接 GitHub，初次同步会失败，安装会在**修改 Nginx 前**停止。此时可先通过可信电脑把公开 APK 拷到 VPS，再按官方 SHA-256 校验，之后补齐镜像同步方案；**不要跳过签名或 HTTPS 检查**。

## 检查公网更新源

无需登录或配对：

- <https://jipite.borealos.cn/app-updates/latest.json>
- `https://jipite.borealos.cn/app-updates/Jipite-v0.9.3-Microsoft-connected.apk`（仅镜像包含该版本时有效）

`latest.json` 必须包含 `schema=1`、`version`、`asset`、`size`、`sha256`。Android 客户端**不相信任意 URL**：下载地址仅从固定域名和验证通过的版本号构造；APK 还要匹配当前已安装的签名证书、包名及严格递增版本。Nginx 使用固定路径和 HTTPS，不允许未授权的上传。

## 从旧版本过渡

- 已安装 v0.9.0–v0.9.2 的客户端仍连接 GitHub API，不会因服务器部署而自动改变原来的更新地址。
- **只需要一次手动安装 v0.9.3**，可用这里的 VPS 链接（先完成上面的 VPS 部署），或者通过 ChatGPT 获得已签名 APK 并覆盖安装。
- v0.9.3 以后，进入「设置 → 应用更新 → 检查更新」会从 **VPS** 查询；「启动时自动检查更新」也只访问 VPS。
- 即使 VPS 镜像被误配置，App 仍验证 APK SHA-256、版本、包名和与当前安装版本相同的签名证书；验证失败时拒绝安装。

## 故障排查（只读命令）

```bash
sudo systemctl status jipite-android-update-sync.timer --no-pager
sudo journalctl -u jipite-android-update-sync.service -n 40 --no-pager
curl -sS -i https://jipite.borealos.cn/app-updates/latest.json
sudo nginx -t
```

如果同步失败，Android 依旧可以登录 Microsoft、刷新审批申请。同步程序不会写入 GPU 相关目录。审批器的 VPS 真实操作权限依旧由原来的服务端控制规则决定。
