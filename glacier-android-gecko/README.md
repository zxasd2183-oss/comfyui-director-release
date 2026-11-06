# Glacier Android · v0.2.0 M02

移动版浏览器主线，使用 Mozilla GeckoView 159 和嵌入式 sing-box 1.14.4。

## M01 已通过（小米真机反馈）
- VLESS 节点仅在用户勾选时保存至 Android Keystore（AES-GCM）
- 冷启动自动恢复 VLESS；连接失败不自动回退直连
- Google 登录由用户在小米真机确认可用
- 可重新导入或删除保存在本地的 VLESS 节点

## M02 UI
- 冰川浅色配色与 Chrome 风格移动端布局
- 顶部品牌标识与独立私人／工作空间切换
- 圆角搜索／网址栏，后退、前进和打开网址
- 底部主页、刷新、添加标签、标签计数和菜单
- 紧凑网络状态提示，点击可打开原有网络诊断
- 保留之前的文件上传下载、Cookie/localStorage 隔离与调试回归测试

## 已知尚未完成
- M03 标签持久恢复、完整标签管理
- M04 书签、浏览历史、下载管理列表
- M05 固定签名及应用内更新
- 账户资料弹窗、验证码 API、跨设备同步属于后续桌面版及同步阶段

## 使用范围
仍是实验 Debug APK；不同构建可能采用不同临时签名。不要在签名冲突时直接卸载以免丢失浏览数据。
浏览器内置的 VLESS 代理只保护 GeckoView 浏览器流量，并不是 Android 全局 VPN。
内核/代理回归测试通过不等于完整安全审计。

## CI
移动版分支：`feature/glacier-android-browser-v020`
独立工作流：`.github/workflows/glacier-android-browser-v020.yml`
M02 发布标签：`glacier-android-browser-v0.2.0-m02`

## M03 标签持久恢复与页面预览
- Android Keystore AES-GCM 加密保存私人／工作空间的标签列表、Gecko 会话状态与缩略图；位于应用私有 no-backup 目录。
- 支持进程结束后恢复最近标签，重新附着到原账号空间。登录状态仍由 GeckoView 的持久隔离存储处理。
- 标签卡片通过 GeckoView capturePixels 展示真实网页截图；未生成预览时显示冰川占位图。
- 最多恢复 25 个标签，不会保存仅用于本地测试的 HTTP 页面。
- M03 模拟器回归包含 Android force-stop 后的双账号空间标签恢复和加密存储校验。
- 浏览器仍是 Debug 测试 APK，不提供云同步或正式安全审计。

## M04 书签、历史记录与下载管理
- 当前空间的书签添加、取消收藏、打开、管理删除；仅可保存 HTTP(S) 网页，排除本机 CI 端口与危险链接。
- 使用 Gecko 成功完成页面加载后的网址和标题填充历史记录，支持各空间独立查看、清空。
- 用户通过 Android 文件选择器保存完成的真实下载将被记录在所属空间；可尝试打开已保存文档，若文档权限被回收则显示提示。
- 所有记录（含文档 content URI）仅在应用私有 no-backup 目录，Android Keystore AES-GCM 加密，不上云；私人／工作记录严格按 GeckoSession 所属空间写入。
- 不保存下载文件的第二份副本；清除下载记录不删除用户保存的文件。
- Android 15 模拟器测试覆盖收藏、历史、文件下载记录、强制关闭后保留，以及额外一项加密库完整性和空间分离测试。

## M05 固定签名与安全更新（开发分支）
- 正式更新从官方 GitHub Releases 获取符合 `glacier-android-browser-vX.Y.Z` 且名称匹配 `GlacierAndroid-vX.Y.Z-ARM64-x86_64-release.apk` 的固定签名资产；忽略其他项目及调试标签。
- 应用在启动时自动查询新版（可关闭，最短间隔 6 小时），由用户明确选择下载；安装交由 Android 系统确认，不静默安装。
- 下载前核实标签／名称／SHA-256 发布记录，下载完成后验证完整 SHA-256、长度、Android 包名／版本及与本机相同的 APK 签名证书，安装前重复校验。
- VLESS 模式仅通过本地 SOCKS5 向代理发送目标域名并建立 TLS；失败绝不退回直连，所有跳转保持受限 HTTPS 主机白名单。仅用户明确选择直连时允许直接 HTTPS。
- 固定签名需要独立的 `GLACIER_ANDROID_*` GitHub Actions 签名密钥秘密，**不能**重用吉皮提的签名私钥；缺少时禁止发布稳定 Release。
- M05 是第一个正式固定签名基线。M01–M04 仅为历史 Debug 版本，不设置旧版兼容发布门禁；旧 Debug APK 不可保证覆盖安装，卸载将清除旧应用本地资料，需用户自行确认。M06 及后续正式版必须沿用 M05 签名。
- M05 Debug 包仅测试本地解析、证书验证逻辑和界面门禁，不访问 GitHub 在线更新源。
