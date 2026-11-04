# 小米审核期间先做吉皮提 Android 手动审批版

这个方案不需要 Xiaomi SDK、AppId/AppKey、FCM 或 Google Play 服务。Android 构建渠道叫 manualDebug。没有自动弹系统通知，但 App 可以手动刷新待审批申请并执行 Microsoft 个人账号认证与生物识别签名。

## 1. Windows 电脑上先生成 Debug APK 的证书

在电脑下载 GitHub 仓库最新源码，打开 Android Studio -> android-jipite/，选择 Build Variant manualDebug，Build APK(s) 一次。这会创建本地用户的 ~/.android/debug.keystore。

然后打开 PowerShell，切换到 android-jipite/ 目录：

    .\prepare-manual.ps1 -ShowHashOnly

终端会打印 Android package cn.borealos.jipite 和当前 Debug 签名证书的 Microsoft Android Signature Hash（SHA-1 Base64）。每台电脑/每套 debug.keystore 的 hash 可能不同。不要换签名私钥，否则必须更新微软后台的 Android 平台 hash。

## 2. 注册微软个人账号 Android 登录应用

进入 https://entra.microsoft.com 的 App registrations，创建支持个人 Microsoft Account 的应用。Android 平台登记：
- 包名 cn.borealos.jipite
- Signature Hash：本地脚本刚输出的值

复制微软 Application (client) ID。不要创建客户端密码，不要提供 Microsoft 账号密码。你需要有能创建 app registration 的 Entra 租户/权限。

官方指引：https://learn.microsoft.com/en-us/graph/auth-register-app-v2

## 3. 配置并构建本地可登录 APK

在 PowerShell 的 android-jipite/ 目录：

    .\prepare-manual.ps1 -MicrosoftClientId "这里填你的 Application client ID"

脚本自动写入 MSAL 配置 Client ID、redirect URI 与 AndroidManifest 对应的签名路径。使用 Android Studio 再构建 manualDebug；输出路径为：

    app/build/outputs/apk/manual/debug/app-manual-debug.apk

安装到国行小米手机上。不需要提供小米任何推送凭证。这是手动刷新版；它不是 Xiaomi 自动推送版。

## 4. 在 VPS 部署手机审批 API

使用 ../vps-control/MOBILE_V06.md 中的安装流程，现有独立手机 TOTP 审批保留不变，确认：
- VPS loopback 服务 127.0.0.1:8895 健康
- 现有 jipite.borealos.cn HTTPS Nginx server 新增 /api/v1/mobile/ 路由
- Microsoft Client ID 与安卓应用注册一致
- 高熵配对码只在 VPS 私人终端查看，首次输入 App，不要贴到 ChatGPT

## 5. 优先测试不影响 GPU 的拒绝路径

用 Microsoft 个人账号在 App 登录并完成设备首次绑定。ChatGPT 创建一张 5 分钟有效的申请，App 点击“刷新待审批申请”查看，先选择“拒绝”并通过指纹或强生物识别验证。拒绝不应执行任何 GPU 云电源 API。

只有你明确同意真实付费 GPU 启停操作时，再测试批准。停机前必须独立确认 ComfyUI 队列为空；出错则 fail closed。

## 小米审核通过之后

用 XIAOMI_PUSH.md 中的方式，将小米官方中国大陆 Mi Push SDK AAR 放进本地 android-jipite/app/libs/，拿到客户端 AppId/AppKey 和 VPS server-only AppSecret，并取得小米审核通过的消息通道与模板编号。切换到 xiaomiDebug，加入系统自动通知。原来的 Microsoft 绑定、生物识别签名和 GPU 关机安全限制不用重做。

注意：CI 自动产出的 UI-only Debug APK 使用占位微软 Client ID，仅供观察应用界面；真实登录与审批必须由自己的 Microsoft app registration + 本地签名生成 APK，并经 VPS 部署后真机联调。
