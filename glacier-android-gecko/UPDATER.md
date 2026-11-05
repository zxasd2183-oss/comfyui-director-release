# Glacier Android v0.1.3 — 安全自动更新实验

## 已实现

- 只读取本仓库 GitHub API 的 Android 更新 tag：`glacier-android-gecko-network-vX.Y.Z`
- 进入浏览器后自动检查（12 小时节流），「菜单 → 检查更新」可手动检查
- VLESS 模式下，更新请求也经由本地 SOCKS5 代理；断开时不会悄悄改为直连
- 只接受指定发布 tag 与指定 APK 文件名、HTTPS 下载及允许的 GitHub 跳转地址
- 核验 GitHub 记录的 SHA-256、文件大小、升级版本、Android package ID 和与已安装应用**完全相同的签名证书**
- 通过 Android 系统安装器安装，用户必须确认；需要时向系统申请「允许此来源安装」
- 新版发布必须高于旧版，不允许同版本替换 / 降级

## 特别重要：v0.1.2 的临时签名无法无缝覆盖

之前的 v0.1.2 Android APK 在 GitHub Actions 上使用临时 Debug 签名；
不同运行的签名可能不同。它不可能被一个独立稳定证书静默接管。

**必须一次性迁移**：卸载测试版（会清掉该实验版数据），然后首次手动安装
用 Glacier 独立长期密钥签名的 Release APK。以后才能用相同证书连续升级。

**不能把临时 Debug APK 当成正式自动更新 APK。** 代码明确区分两种发布 tag：

- `glacier-android-gecko-debug-v0.1.3`：仅做 UI/代码测试，临时签名，**不会被自动更新识别**
- `glacier-android-gecko-network-v0.1.3`：独立长期签名的正式升级通道，只有在密钥配置就绪并验证成功时发布

## 首次配置长期签名

在 GitHub 仓库 Settings → Secrets and variables → Actions → Repository secrets 配置：

| 密钥名称 | 内容 |
|---|---|
| `GLACIER_ANDROID_KEYSTORE_BASE64` | Glacier Android 独立、长期保管的 PKCS12 签名密钥库 Base64 |
| `GLACIER_ANDROID_SIGNING_STORE_PASSWORD` | 密钥库口令 |
| `GLACIER_ANDROID_SIGNING_KEY_ALIAS` | 固定签名 alias |
| `GLACIER_ANDROID_SIGNING_KEY_PASSWORD` | 该 alias 对应密钥口令 |

**必须在可信设备离线生成并备份密钥库，绝不能放进仓库、Issue、聊天或普通日志。**
不得直接使用 Jipite 的独立产品签名密钥，防止跨应用信任边界共享。
私钥丢失就无法为已经安装的用户签发兼容更新。

构建工作流在没有全部密钥时只会发布标为 Debug 的测试包，不会发布正式更新渠道。
构建后使用 Android SDK `apksigner verify --verbose` 检查正式签名。

## 不能夸大的边界

- 这是「应用进入前台后自动检查、用户确认下载安装」，**不是后台静默安装**。
- 250 MB 量级的 APK 仍会受到 GitHub 下载超时影响，目前无已验证的 CDN/VPS 备用下载。
- 更新元数据经由 GitHub TLS 获取，但当前未另行部署独立签名的 JSON 清单；
  安全最终依靠严格的仓库 URL、SHA-256 和 Android 系统安装签名链，客户端会拒绝签名不匹配的包。
- 还没有真机验证此更新路径，构建成功不代表跨版本升级已实测。
- 仍属未完成安全审计的内核网络实验，不要存放重要账号。

代码位置：`UpdatePolicy.java`、`AndroidUpdater.java`、`MainActivity.java`；
构建工作流：`.github/workflows/glacier-android-geckoview-updater-v013.yml`。
