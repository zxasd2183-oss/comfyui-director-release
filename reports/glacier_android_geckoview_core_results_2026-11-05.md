# Glacier Android GeckoView 159 v0.1.2 — 实测记录（2026-11-05）

## 范围

只测试内核与网络实验版，不新增浏览器功能，不使用真实用户账号或私有 VLESS 节点。运行 Android 15 / x86_64 GitHub Actions 模拟器（Google APIs 和 AOSP ATD 镜像），APK 包内经校验包含 GeckoView 159 及 sing-box 1.14.4 的 x86_64 与 ARM64 原生核心。结果不等于真实小米 Android 设备表现。

## 有证据支持的 PASS

1. APK 构建、VLESS 配置单元测试和双 ABI 原生库检查通过。多个 Actions 运行重复验证。
2. 真实模拟器选择显式直连后成功显示 GeckoView，访问 `https://example.com/`，可从 UI XML 读取 “Example Domain” 正文；GitHub 页面可从 UI XML 读取标题、导航及网站正文。
3. Android 15 AOSP ATD：第二标签页、私人→工作→私人空间切换、切到 HOME 并返回、进程存活和显示均通过。对应记录：`42033507240` 和 `42034716659`。这些仅证明 UI/会话切换，并非 Cookie 安全性结论。
4. **实际 HTTP Cookie 隔离 PASS**：使用 `https://httpbin.org/cookies/set` 和 `/cookies`，私人空间写入 `private001`，工作空间不能读取；工作空间写入 `work002`，切回私人空间仅能读取 `private001`。完整成功运行： https://github.com/zxasd2183-oss/comfyui-director-release/actions/runs/42034792511
5. **远端不可达时未观察到直连回退 PASS（限单 URL 场景）**：测试专用的 RFC5737 `203.0.113.1:443` 假 VLESS 节点，内置 sing-box 启动且本地 SOCKS 就绪；随后 GeckoView 未出现 `Example Domain` 内容。记录： https://github.com/zxasd2183-oss/comfyui-director-release/actions/runs/42035750158 。**不能把这当成真实 VLESS 已连通或所有 DNS/WebRTC/IP 泄露路径已排除**。

## 未完成 / 有限制 / 已知问题

- **真实 VLESS 出口和 DNS 不泄漏**：无可用测试节点及远端出口验证，所以没有端到端 PASS。仅验证本地 SOCKS 能启动及远端不可达时单一 HTTPS 页面未发生可观察直连回退。
- **登录与 OAuth**：不能凭 GitHub 首页加载推断 ChatGPT、Google OAuth 登录成功；未输入个人账号。
- **文件上传下载**：v0.1.2 宿主代码未设置 `GeckoSession.PromptDelegate.onFilePrompt` 和 `GeckoSession.ContentDelegate.onExternalResponse` 的处理，因此是应用嵌入层缺口；不能据此断言 GeckoView 引擎本身不支持。
- **重网页压力下模拟器间歇失去 ADB 响应**：Google APIs 镜像出现过 `Pixel Launcher isn't responding`；AOSP ATD 镜像在打开后续网站时也发生 `adb shell screencap` 超时，脚本被判失败。不把这些等同于 GeckoView Java 崩溃，但也不能给长期稳定性满分。
- **视频**：用户报告普通 MP4 正常而 YouTube 黑屏；用户选择暂时跳过。不是 PASS。
- **持久性**：HOME→返回通过，长时间运行、低内存杀进程后标签恢复、真机耗电没有充分实测。

## 结论

**GeckoView 可以继续作为 Glacier Android 的候选内核；尚未达到宣布生产合格或淘汰 Chromium 对照测试的证据水平。**

最有价值的证据是可实际加载真实网页、持久身份 Cookie 隔离成功，以及一次远端不可达的 VLESS 不直连行为测试。下一阶段应继续解决嵌入层文件处理、真实节点出口验证和重网页稳定性，而不是添加书签、云同步、完整 UI 或自动更新。

## 关联 CI

- 真实网页 + 初次模拟器运行（含截图）：https://github.com/zxasd2183-oss/comfyui-director-release/actions/runs/42031553263
- 真实标签页/空间/后台测试（轻量模拟器）：https://github.com/zxasd2183-oss/comfyui-director-release/actions/runs/42033507240
- Cookie 隔离 PASS：https://github.com/zxasd2183-oss/comfyui-director-release/actions/runs/42034792511
- 不可达 VLESS 不直连 PASS：https://github.com/zxasd2183-oss/comfyui-director-release/actions/runs/42035750158

测试仅存在于 `experiment/glacier-android-core-ci` 分支；未改动 v0.1.2 已发布 APK 内核。
