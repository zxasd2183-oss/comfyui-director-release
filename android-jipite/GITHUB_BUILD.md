# GitHub Actions 直接构建 APK（不需要 Android Studio）

入口：[Build Jipite APK on GitHub](https://github.com/zxasd2183-oss/comfyui-director-release/actions/workflows/build-jipite-apk.yml)

### 现在就能用：preview

在 GitHub 仓库里打开 Actions -> Build Jipite APK on GitHub -> Run workflow -> mode=preview。自动打包并通过 Android apksigner 检查签名，在本次运行的 Artifacts 处得到 Android 11+ 的 app-manual-debug.apk。

**V0.7 Beta Preview APK 仅用于 MuMu 离线模拟和联机准备检查**。构建产物名为 `Jipite-V0.7-MuMu-readiness-preview`，内部 APK 为 `app-manual-debug.apk`。其微软 Client ID 仍是占位值，无法真实微软登录或审批 GPU。

现在可在本地按钮模拟开机/关机申请、查看风险提示、模拟批准/拒绝并查看联机配置检查结果；所有 Debug 变体均严格离线，完全不调用 Microsoft、VPS、GPU 或 Android Keystore，不需要小米 SDK、Firebase、Android Studio。详细步骤见 [V0.7 联机准备指南](./CONNECTED_V07.md) 和 [MuMu 测试清单](./MUMU_TEST.md)。

### 微软真实登录：connected（仅需一次性配置）

必须有一份**稳定的 APK 签名密钥**。GitHub 自动生成的临时 debug keystore 在不同 Runner 上不同，会破坏与微软后台注册的 SHA1 签名哈希关联，因此真实登录版本采用 GitHub Secrets 注入的私有签名证书。

GitHub 仓库 Settings -> Secrets and variables -> Actions 中，配置：

Repository variables（公开应用元数据）：
- JIPITE_MS_CLIENT_ID：Microsoft Entra 中支持个人账号 Android App 的 Application (client) ID
- JIPITE_SIGNING_KEY_ALIAS：你自己创建的签名密钥别名，如 jipite

Repository secrets（不得贴到 ChatGPT、GitHub 源码或截图）：
- JIPITE_KEYSTORE_BASE64：你自有的 Android 签名 PKCS12 keystore 文件的 Base64 内容
- JIPITE_SIGNING_STORE_PASSWORD：keystore 密码
- JIPITE_SIGNING_KEY_PASSWORD：密钥密码；PKCS12 可能与 store password 相同

若尚无签名证书，可以在自己的可信 Linux/VPS 或电脑的 JDK 17 keytool 下生成一次（命令中不出现密码，交互输入，请谨慎保管私钥及备份）：

    keytool -genkeypair -storetype PKCS12 -keystore jipite-signing.p12 -alias jipite -keyalg EC -groupname secp256r1 -validity 3650 -dname "CN=Jipite Android Approval"

生成后对 keystore 做 Base64 编码，仅保存到 GitHub Actions Repository Secret。千万不要上传到仓库、公开 Artifacts、聊天或放在 Android APK 中。若私钥丢失，未来更新 APK 无法沿用同一签名。GitHub Actions 构建期间从 Secrets 解码到临时 Runner 的隔离路径，运行结束后不会随 Artifacts 上传。

然后 GitHub Actions 选 mode=connected，自动从该证书生成准确的 SHA1 Base64 签名哈希，并填入 MSAL client config / AndroidManifest，使用配置的稳定密钥签名 Release APK。**该签名哈希会显示在构建摘要**，你只需将它连同包名 cn.borealos.jipite 添加到 Microsoft Entra App Registration 的 Android 平台。签名哈希是公开标识，不是私钥。

审核中的小米 Mi Push 与此流程独立：connected APK 目前为**无系统推送的手动刷新审批版**，但能在已部署的广州 VPS V0.6 API 上完成真实微软身份登录、设备绑定、强生物识别签名；手机端仍必须在生物识别后，VPS 才能对云 GPU 执行已审批动作。旧 TOTP 安全审批保持有效。

以上均不需要你本机安装 Android Studio。唯一需要用户本人完成的是**Microsoft App Registration、稳定签名密钥的安全保管、GitHub Secrets 设置，以及真实安卓手机的登录/绑定**。助手不会向你索取任何私人密码或 keystore。

GitHub Actions 的 Artifacts 是临时文件，会按工作流中 retention-days 自动过期；完成测试后可由你决定正式发版与保留期限。
