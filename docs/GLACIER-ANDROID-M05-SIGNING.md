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

## M05 是第一代正式签名基线

- M01–M04 属于历史 Debug 实验包，不再为其签名和迁移专门设置发布门禁。
- M05 首次采用 Glacier 专属、长期保管的稳定签名；M06 及以后必须沿用同一签名证书。
- 旧 Debug APK 因签名不同不能覆盖正式版；有旧安装时，Android 可能要求先卸载。**卸载会清除旧应用的私有数据和 Keystore 密钥**，请明确知悉后自行决定，不可静默卸载。
- 不能把 GitHub Actions 自动生成的临时 Debug 证书作为长期生产签名，也不能复用吉皮提的证书。
- 正式版是否已发布，只以 GitHub Actions 成功执行、签名指纹校验通过及 Release 资产存在为准。

## 网络与安装约束

- 更新检查默认在启动后进行，至少间隔 6 小时，可在应用菜单关闭。
- 更新源检索最近 100 条 GitHub Release，并忽略 draft / prerelease；该共享仓库如果超过 100 条其他项目发布，仍可能需要后续升级为 Glacier 专用更新索引。
- VLESS 模式走本地 SOCKS5 (ATYP=domain) 和 HTTPS；代理故障时拒绝更新，绝不自动直连。
- 只信任官方 GitHub Glacier Release 约定的标签、资产和受限 HTTPS 主机；SHA-256、包名、版本递增、签名证书均必须匹配。
- 用户必须确认下载与 Android 系统安装；没有静默安装权限。
- Debug APK 永远不能联网下载正式更新，也不会被当作自动更新源。
