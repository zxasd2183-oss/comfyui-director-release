# Glacier Android M05 · 固定签名上线清单

> 这是独立于吉皮提 (Jipite) 的 Glacier Android APK 证书。严禁共享、复用或提交吉皮提的签名私钥。

## 当前状态

- M05 已实现固定签名 Release 的构建步骤及应用内安全更新客户端。
- 普通提交仅测试临时 Debug APK；**不会**发布可自动升级的 Release。
- 真正稳定 Release 需要新建、永久离线备份 Glacier 专用签名证书，并在 GitHub Actions 中配置独立 Secrets。
- GitHub 连接不支持读取／写入 Actions Secrets，因此设置须由拥有该仓库设置权限的人在 GitHub 页面中完成；脚本不得把密码、密钥或 keystore 输出到 CI 日志。

## 一次性生成专用签名密钥

在可信任的离线或个人 Windows 设备上使用 Java JDK 的 `keytool`：

```powershell
keytool -genkeypair -storetype PKCS12 -keystore GlacierAndroid-release.p12 -alias glacier-android-release -keyalg RSA -keysize 3072 -sigalg SHA256withRSA -validity 7300
```

根据提示设置强密码。**切勿将 `GlacierAndroid-release.p12` 或密码提交到 GitHub、上传聊天或发给第三方。** 在独立安全位置进行加密备份，永久保留。

从同一 keystore 导出**仅包含公钥的证书**：

```powershell
keytool -exportcert -storetype PKCS12 -keystore GlacierAndroid-release.p12 -alias glacier-android-release -file GlacierAndroid-public.cer
(Get-FileHash -Algorithm SHA256 .\GlacierAndroid-public.cer).Hash.ToLowerInvariant()
```

此 SHA-256 是公有签名证书指纹，不是密码。

## GitHub Actions 设置

在仓库的 **Settings → Secrets and variables → Actions** 中配置：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Repository secret | `GLACIER_ANDROID_KEYSTORE_BASE64` | `GlacierAndroid-release.p12` 完整二进制文件的 Base64（不换行） |
| Repository secret | `GLACIER_ANDROID_SIGNING_STORE_PASSWORD` | keystore 密码 |
| Repository secret | `GLACIER_ANDROID_SIGNING_KEY_PASSWORD` | 该 alias 的私钥密码，PKCS12 通常与 store 密码一致 |
| Repository variable | `GLACIER_ANDROID_SIGNING_KEY_ALIAS` | `glacier-android-release` |
| Repository variable | `GLACIER_ANDROID_CERT_SHA256` | 上面公钥证书 SHA-256（64 位十六进制，无冒号） |

Windows PowerShell 可本地生成 Base64 以粘贴进 GitHub Secret：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path .\GlacierAndroid-release.p12)))
```

以上输出包含完整私钥，**仅粘贴到 GitHub Repository Secret**；不要保存到仓库或聊天记录。

首次签名发布：在 GitHub Actions 中运行 `Glacier Android Mobile v0.2.1 M05 stable signing and verified updates` 的 **Run workflow**，选择分支 `feature/glacier-android-m05-updates`，将 `publish_signed` 设为 `true`。

发布门禁将强制检查：全部 Android 15 回归、keystore 密码与 alias、实际 APK 签名、公钥 SHA-256 固定指纹、APK 文件大小、唯一版本标签。正式发布标签 `glacier-android-browser-v0.2.1` 一旦存在不可覆盖，后续版本必须递增 versionCode、versionName。

## 重要：M04 → 首个稳定版的数据迁移

M01–M04 的 CI Debug APK 由临时 Debug 密钥签名。**新固定签名可能无法直接覆盖安装旧 Debug APK**。Android 会阻止不同签名覆盖同一 package，卸载旧 App 将删除本机 Android Keystore 加密密钥及已保存的 VLESS 节点、标签、账号 Cookie、历史记录等。不能保证普通文件复制恢复加密数据。

因此在安全迁移机制和设备侧备份验证完成前，**不要为了安装首个 M05 固定签名版而卸载现有 M04**。M05 的“签名自动更新”仅保证在**首次固定签名版安装完成后**，未来同签名版本可升级并保留数据；旧 Debug → 固定签名的迁移需另行处理。

## 网络与安装约束

- 更新检查默认在启动后进行，至少间隔 6 小时，可在应用菜单关闭。
- VLESS 模式走本地 SOCKS5 (ATYP=domain) 和 HTTPS；代理故障时拒绝更新，绝不自动直连。
- 只信任官方 GitHub Glacier Release 约定的标签、资产和受限 HTTPS 主机；SHA-256、包名、版本递增、签名证书均必须匹配。
- 用户必须确认下载与 Android 系统安装；没有静默安装权限。
- Debug APK 永远不能联网下载正式更新，也不会被当作自动更新源。
