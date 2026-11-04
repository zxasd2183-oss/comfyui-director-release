# 吉皮提 V0.9.0 · Fluent 风格与应用内更新

V0.9.1 在 V0.9.0 的 Fluent 界面和更新功能基础上增加下载版本名校验与安装源路径再次核验。此次是界面和发布分发升级，不修改已有 Microsoft 身份认证、一次性配对、Android Keystore 签名、VPS 审批规则或 GPU 电源安全边界。

## 界面

- 使用微软 Fluent 设计语言的视觉思路（**独立原创界面**，不冒充 Microsoft 官方应用）：亮色中性背景、圆角卡片、克制的蓝色按钮、清晰的标题与状态。
- 按用户操作顺序组织：Microsoft 账户 → 安全连接 → 待审批申请 → 设备绑定 → 关于与更新。
- **独立的 Microsoft 登录状态**保留在专门的账户卡片，不被“尚未绑定手机”覆盖。
- 首页和关于区都可查看应用状态；「关于与更新」显示来自 `BuildConfig` 的真实 `versionName` 和 `versionCode`。

## 真实应用内更新工作流

首次从旧的 V0.8.x 升到 V0.9.0，需通过下载 APK 覆盖安装一次。**V0.9.0 起**才具有内置更新功能。

1. 进入「关于与更新」点击「检查更新」。
2. App 只访问公开的 GitHub Releases API：
   `https://api.github.com/repos/zxasd2183-oss/comfyui-director-release/releases`
3. 只认 `jipite-vX.Y.Z` 标签的官方发布、与此标签完全对应的 `Jipite-vX.Y.Z-Microsoft-connected.apk` 发布资产。忽略同仓库的 Glacier Browser 或其他项目。
4. 检查新版本号高于本机版本，且 GitHub 提供 `sha256:...` 资产摘要。
5. 用户明确点击「在应用内下载新版」。经 HTTPS 下载到应用私有缓存，**不会下载到公共 Downloads，也不会请求 Microsoft 登录凭据**。
6. 下载过程中显示进度，并依次校验：文件长度、SHA-256、Android 包名 `cn.borealos.jipite`、版本递增、**签名证书与已安装版本完全一致**。
7. 用户明确点击「安装已验证的新版」，启动 Android 系统安装确认界面。**应用本身不能静默安装**。如系统要求，用户需允许吉皮提作为更新安装来源。
8. 安装完成后，保留已有 App 数据和 Microsoft 登录缓存（以 Android 正常同签名升级行为为准）。

**安全策略：** 任一校验失败直接删除未完成文件并拒绝调用安装器；只允许 `github.com`、`api.github.com` 和用于官方下载重定向的固定 GitHub 资产域名；不允许 HTTP、任意网址、降级版本或证书不一致的 APK。Deb​​ug 版严格离线，不访问更新端点。

## GitHub 自动发布

`.github/workflows/build-jipite-apk.yml` 对受信任 `main` 分支变更生成同一证书签名的联机版 APK，并单独由 `publish` 作业使用受限的 `contents: write` 权限创建：

- Release tag：`jipite-vX.Y.Z`，例如 `jipite-v0.9.1`
- APK asset：`Jipite-vX.Y.Z-Microsoft-connected.apk`
- 发布页：`https://github.com/zxasd2183-oss/comfyui-director-release/releases`

发布前需成功编译并通过 apksigner 校验。CI 不将签名私钥上传到 Release。若同版本 Release 已存在，不覆盖已有版本；后续迭代必须增加 Android `versionCode`、`versionName` 和对应 Release 标签。

## 注意

- Github Releases / API 访问取决于当前网络环境；中国大陆部分网络可能无法直接访问。不能因此关闭 HTTPS 或签名验证。可在后续版本接入自己的可信镜像源。
- 小米国行 Mi Push 的正式审核与真机强生物识别测试仍需单独完成；MuMu 不等于真机硬件认证。
- 即使客户端更新完成，GPU 电源操作仍然要通过 VPS 服务端的现有安全边界和实际审批检查。
