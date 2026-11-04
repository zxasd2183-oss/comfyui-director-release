# 吉皮提 Android V0.8 RC1

**最新统一构建与部署说明：** [V0.8 一次性配置及交付路线](./SHIP_V08.md)；[GitHub Actions 下载指南](./GITHUB_BUILD.md)。

Android Studio Kotlin 项目（Android 11+，API 30+）。手机直接收 GPU 操作推送，点击通知后在 App 中看清开机/关机动作，指纹或强安全等级面容签名批准/拒绝。

## 实施状态

**源码阶段**：已经写好 MSAL 个人账号登录、Android Keystore P-256 密钥、BiometricPrompt、申请刷新、手机端 POST API 和 FCM 接收器。尚未用你的 Microsoft App Registration、Firebase 项目及手机进行真实联调，所以不要把测试构建等同于正式可用 APK。

## 一次性配置

1. 在 Microsoft Entra 应用注册中配置支持个人 Microsoft Account 的 Android 应用，包名 cn.borealos.jipite，获取 Client ID 以及该 APK 签名证书的 redirect URI。
2. 把公开 Client ID、完整 redirect URI 填入 app/src/main/res/raw/msal_config.json。
3. 在 app/src/main/AndroidManifest.xml 的 BrowserTabActivity 中将 android:path 从 REPLACE_SIGNATURE_HASH 改成实际的 Android 签名哈希（不 URL 编码）。
4. 在 Firebase 创建包名相同的安卓 App，放入真实 app/google-services.json（Git 忽略）。如果没有 Google Play Services 或 VPS 到 FCM 出站不可达，主动刷新申请仍然能用，但不能保证通知送达。
5. Android Studio 使用 JDK 17 Gradle Sync，Build / Run。Android API >= 30，手机强生物识别已启用。
6. 确认自己的 VPS 已安装 V0.6 API，并在首次绑定输入从 VPS 私人终端读取的 root-only 配对码。

**千万不要**提交签名私钥、微软账号密码、Microsoft ID Token、Firebase service account JSON、VPS 配对码到 GitHub / ChatGPT。

完整的 VPS 部署和安全说明见 ../vps-control/MOBILE_V06.md 。

## 客户端交互说明

- 用户主动点击微软登录：MSAL 可使用现有个人 Microsoft 登录状态。
- 首次绑定：Microsoft ID Token + VPS 高熵配对码 + 安卓 Keystore 公钥。
- 新申请：若 FCM 可达，弹系统通知（没有直接批准按钮）；点开 App，先从 VPS 查询真实申请类型。
- 审批：用户明确点批准或拒绝 → 强生物识别 → 签署服务器一次性 90 秒挑战 → VPS 验签。回执的 submitted 还不是最终 GPU Running/Stopped。
- 离线或 FCM 失败：用户在 App 点击“刷新待审批”；GPU 不会因为未收到通知而自动启动或关闭。
- 锁屏、设备换脸/指纹或重装导致 Keystore 私钥失效，需在 VPS 端审核后重新安全配对。

## 与 Microsoft Authenticator 的区别

Microsoft Authenticator 没有开放通用的“第三方 GPU 任意操作批准”推送 API。吉皮提审批器利用 Microsoft 登录确认持有人身份，但手机 GPU 审批通知是它自己的 App 通过 FCM（或未来厂商推送）来实现。
