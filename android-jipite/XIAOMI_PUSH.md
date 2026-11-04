# 小米手机专项接入：吉皮提 V0.6 + Mi Push

适配目标：小米 / Redmi 的中国大陆 HyperOS/MIUI 机型。核心原则是小米系统推送只负责通知，而不是直接授权开关机。用户必须在 App 中查看操作与费用风险，亲自按下批准/拒绝，再通过 Android 强生物识别完成设备签名；广州 VPS 验签后仍执行原有云状态和 ComfyUI 队列检查。

**如果手机是国际版系统或所在推送服务区域不在中国大陆，则应使用该地区对应的非中国大陆 SDK、服务器 API，或使用 FCM。当前代码里的小米 REST endpoint 是中国大陆版。**

## 国行小米 APK 构建准备（Windows 优先）

已增加 Windows PowerShell 引导脚本：android-jipite/prepare-xiaomi.ps1。

先在小米官方 SDK 下载页登录，获取**中国大陆版 Mi Push AAR**，保存在电脑，例如 C:\Downloads\MiPush_SDK_Client_xxx.aar；另准备你从小米控制台取得的 Android 客户端 AppId/AppKey。

同时在 Microsoft Entra 注册支持个人账号的 Android App，登记 cn.borealos.jipite 和**要安装 APK 的签名证书 SHA1 Base64 哈希**。Debug APK 和 Release APK 的签名不同，必须分别登记。

在 Windows PowerShell 的仓库 android-jipite 文件夹运行（替换所有示例参数）：

    .\prepare-xiaomi.ps1 -AarPath "C:\Downloads\MiPush_SDK_Client_xxx.aar" -MicrosoftClientId "11111111-2222-3333-4444-555555555555" -MicrosoftSigningHash "ANDROID_SHA1_BASE64" -MiAppId "MY_XIAOMI_APP_ID" -MiAppKey "MY_XIAOMI_APP_KEY"

此脚本只在本机检查 SDK 包内 MiPushClient/PushMessageReceiver、复制 Mi Push AAR，并写入 Microsoft Client ID/真实签名哈希、小米客户端 AppId/AppKey，不要求 Firebase/Google Play 服务，也不会把服务器 AppSecret 放进 APK。

随后用 Android Studio 打开 android-jipite 工程，选择 xiaomiDebug，执行 Build APK(s)。如果 Windows 已装 Gradle 8.10.2/JDK17/Android SDK，也可以给命令增加 -Build 参数自动构建。

构建完成后 APK 预期输出：

    android-jipite/app/build/outputs/apk/xiaomi/debug/app-xiaomi-debug.apk

**当前 GitHub CI 只验证 Google 基线变体，不代表 Xiaomi 变体已有官方 AAR 且完成实机编译。** 仓库当前也没有 Gradle Wrapper JAR，需要 Android Studio 或你本机的 Gradle。微软 Client ID 与 Android AppId 是客户端标识，但在修改本地源文件后仍需检查 git diff，避免误提交其他数据。

## 2026 年小米消息分类、通道和模板

从 2026 年 8 月起，小米消息分类规则已经生效。GPU 审批提醒属于用户主动请求的操作通知，但能否进入特定的私信类型，须由小米审核判定，不应自行宣称属于“设备状态”或其他私信类。

在小米后台申请真实用途对应的消息 channel 和**无变量模板**。通过审核后，获取数字 channel_id / template_id。示例文字：吉皮提 RTX 5090 有待处理的操作申请，请打开手机应用查看。模板最终文案以小米审核通过为准。

在广州 VPS 私人终端保存两份文件（root:root 0600）：

    /etc/comfyui-director-xiaomi-appsecret
    /etc/comfyui-director-xiaomi-channel.json

第二份 JSON 示例（数字仅用于说明格式，不是真实 ID）：

    {"channel_id":"130","template_id":"1002"}

只有两份文件同时存在、格式验证通过，VPS 才启用小米推送。Mi Push HTTP 请求会携带小米要求的 extra.channel_id、extra.template_id 和 extra.template_param={}，并只通知手机用户，绝不授权 GPU。否则仍可在 App 手动刷新待审批申请。

小米官方新规：https://dev.mi.com/xiaomihyperos/documentation/detail?pId=2321

小米官方模板：https://dev.mi.com/xiaomihyperos/documentation/detail?pId=2314

## 第一步：小米开发者平台注册

访问 https://dev.mi.com/ 或 https://admin.xmpush.xiaomi.com/zh_CN 注册应用：

- 应用名称：吉皮提审批器
- Android 包名：cn.borealos.jipite
- 开通 Mi Push，申请适当的通知类别并按 2026 年官方规范完成相关审核
- 取得 AppId、AppKey、AppSecret。其中客户端 AppId/AppKey 可放进本地 Android 工程；**AppSecret 只能存放在自己的广州 VPS**。
- 官方 AAR 下载地址：https://admin.xmpush.xiaomi.com/zh_CN/mipush/downpage

客户端接入官方文档：https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1544

服务端 API 官方文档：https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1559

## 第二步：构建 Xiaomi 版本

GitHub 项目 android-jipite/ 已加入 Google 基线版与 Xiaomi 原生推送版两个 product flavor。

在你自己的电脑从小米官方渠道下载中国大陆 MiPush Client AAR，放到本地路径：

    android-jipite/app/libs/MiPush_SDK_Client.aar

该 AAR 是官方发布的第三方二进制，不随公开仓库分发。缺少它时，Xiaomi APK 无法完成构建。

将模板 android-jipite/app/src/xiaomi/res/values/mipush.xml.example 复制为同目录下的 mipush.xml（已 gitignore），只填写小米客户端 AppId 和 AppKey。请勿将 AppSecret 填入任何 Android 源码。保留已配置的 Microsoft 个人应用 Client ID 和签名 redirect URI。

Android Studio 选择 xiaomiDebug，或运行：

    gradle :app:assembleXiaomiDebug

构建 Xiaomi 版时，不必提供 Firebase 项目或 google-services.json；Google Services 插件仅在传入 enableFirebase=true 时启用。小米原生 Mi Push 接收通知也不要求手机运行 Google Play 服务。源码暂未使用你的真实 Xiaomi SDK AAR 进行 xiaomiDebug 构建验证。

## 第三步：广州 VPS 保存 server AppSecret

在 VPS 私人终端运行：

    sudo install -o root -g root -m 0600 /dev/null /etc/comfyui-director-xiaomi-appsecret
    sudoedit /etc/comfyui-director-xiaomi-appsecret

仅在私有终端填入小米 AppSecret。千万不要贴到聊天、GitHub 或命令行参数里。

原有 vps-control/install-mobile-v06.sh 会从该 root-only 文件通过 systemd LoadCredential 提供给 VPS 的移动审批后端。只在具备此前的 Microsoft App Registration、已安装的 V0.3 旧 TOTP 服务等前提时执行：

    cd ~/comfyui-director-release
    git pull --ff-only
    cd vps-control
    sudo bash install-mobile-v06.sh

本方案不会调用 GPU 的开机/关机 API。Mi Push 服务端使用中国大陆官方 HTTPS v2/message/regid 接口，只向已绑定设备 regId 发提醒。消息不包含生物识别签名、微软 token、申请批准权或云厂商密钥。

## 第四步：真机联调和回退

手机安装自己签名的 APK，允许通知并启用强生物识别。App 登录个人 Microsoft 账号后，在首次绑定时从 VPS 的私密终端读取配对码。小米 SDK 注册成功会将 regId 缓存在手机，下次打开 App 并刷新申请时会安全同步到 VPS。通知到达后，点击并确认真实操作；先测试“拒绝”这一不会执行云操作的安全路径，再经明确许可测试真实开关机。

手机断网、消息过期或推送失败都不会自动开关 GPU。若 Mi Push 不可用，仍可打开 App 主动刷新申请；旧独立 TOTP 审批在移动端链路全面联调完成之前保持原样。小米平台存在应用审核、通知类别和上架政策等要求，未经过真实设备测试不能保证通知送达。

**当前状态：** Xiaomi 适配源码、VPS REST sender 和测试已进入 GitHub；仍待你创建小米推送应用、取得真实凭证、验证第三方 AAR 构建与手机消息投递。
