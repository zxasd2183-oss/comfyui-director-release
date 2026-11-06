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
