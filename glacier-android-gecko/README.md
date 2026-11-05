# Glacier Android — GeckoView 内核真机实验版 v0.1

这个项目是原生 Android 应用，实际嵌入 **Mozilla GeckoView 159 Stable**，不是 Android WebView，也不是完整 Chromium。

## 本次测试范围
- URL 输入 / 搜索、后退、前进、刷新、多个标签页
- 私人 / 工作两个持久隔离的 GeckoView Session Context（Cookie / localStorage）
- 切换账号空间并保留当前进程中的标签页会话
- 内核内部版本页面 `about:buildconfig`、ChatGPT、GitHub 等网站显示和兼容性

## 未实现，不能误认为已支持
- VLESS / 全局网络 fail-closed。**当前是设备默认网络连接**。如果你必须代理才能访问某些网站，应先在系统级 VPN 中处理。不能把这个版本当成安全代理浏览器。
- 密码保险箱、接码 API、账号云同步、下载管理
- 书签、永久标签恢复、权限提示和可靠的文件上传/下载
- 真机自动化验证、Google OAuth 和 ChatGPT 登录兼容性保证
- Play Store 正式签名与长期更新密钥

**暂时不要使用真实重要账号测试。** 建议仅用测试网站和非关键测试账号验证引擎能力。

## 安装 / 构建
GitHub Actions 构建 Android ARM64 Debug APK。调试签名会随 runner 变化，下一次安装不同构建可能需要卸载旧测试版；这也会清除该测试版账号空间的数据。

从源码本地构建：

```bash
gradle -p glacier-android-gecko :app:assembleDebug --no-daemon
```

官网文档：
- https://mozilla.github.io/geckoview/consumer/docs/geckoview-quick-start
- https://mozilla.github.io/geckoview/javadoc/mozilla-central/org/mozilla/geckoview/GeckoSessionSettings.Builder.html
