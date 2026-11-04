# 吉皮提 V0.8 RC1：一次性完成部署的实际边界

本仓库已实现离线模拟演示、基于 Microsoft 个人账号的 Android OAuth、设备 P-256 Keystore 公钥绑定、每次强生物识别 ECDSA 签名、VPS 一次性挑战、防重放、关机前状态/队列重新检查、可选推送与手动刷新。V0.8 又增加了客户端签名载荷逐字节绑定检查和操作二次确认。

## 一次性构建与下载

- 无账户版：GitHub Actions `Build Jipite APK on GitHub` 的 `preview` 模式会给出 `Jipite-V0.8-MuMu-safe-preview`，是**严格离线** Debug APK。可在 MuMu 无网使用，不具备真实微软登录、真实 GPU 审批。
- 联机版：`connected` 只使用自己的 Microsoft Client ID 与**稳定的私人 APK 签名证书**，签出 `Jipite-V0.8-Microsoft-connected-signed`。发布前需完成以下本人可授权的三个步骤。

## 用户必须亲自完成（无需把任何私密信息发给 ChatGPT）

**第一步 · Microsoft Entra 应用注册。** 在 https://entra.microsoft.com/ 注册 Android 应用，账户类型选择允许**个人 Microsoft 帐户**，包名 `cn.borealos.jipite`。取得公开的 Application (client) ID。不需要管理员企业账号。OAuth 回调必须和 APK 固定签名的 SHA1 Base64 完全对应。

**第二步 · 一次性生成并保管 APK 私人签名密钥。** 用受信任 Windows 电脑上的 JDK 17 `keytool` 或自己的可信 VPS 上的 `keytool`，执行如下**交互式**命令（密码不写在命令行）：

```bash
keytool -genkeypair -storetype PKCS12 -keystore jipite-signing.p12 -alias jipite -keyalg EC -groupname secp256r1 -validity 3650 -dname "CN=Jipite Android Approval"
```

私钥只由自己保管和备份，不发聊天、不发给第三方、不提交到 Git。将 keystore Base64 内容作为 GitHub **Repository secret**（不要上传原始 p12 到文件仓库），密钥密码只设置到 Secrets；公开 Client ID/alias 则放 Variables。详细设置名称见 [GITHUB_BUILD.md](GITHUB_BUILD.md)。账户需要自己在 GitHub 网页里授权这些操作。

**第三步 · 构建并注册回调。** 在 GitHub Actions 手动 `Run workflow → mode=connected`。该构建会计算签名哈希并放进运行的 Summary。复制**只有公有签名哈希**，回到 Microsoft Entra App Registration 的 Android 平台登记该哈希。然后使用生成的稳定签名 Release APK。**复制签名哈希而非私钥。**

## 服务端接入（需 VPS 管理员执行）

在广州 VPS 使用现有安全部署指引 [MOBILE_V06.md](../vps-control/MOBILE_V06.md)，部署监听 `127.0.0.1:8895` 的 Android API，只由 `jipite.borealos.cn` HTTPS Nginx 代理。用户只在私人 VPS 控制台读取一次性配对码；不要在聊天中发送，也不要输进不可信模拟器。旧 TOTP 回退保持运行。

客户端在 `manualRelease` 中支持不带凭证的 HTTPS 探测，只有收到 `401 microsoft_login_required` 才认为网关要求登录，**不代表**真实账号登录或签名联调已完成。

## 真实设备验收必须通过后才能上线

MuMu 只能验证界面与无网模拟；要在可信小米真机验证：

- Microsoft 个人账号真实登录，确认签名回调一致
- 首次设备绑定，不上传/泄露设备私钥和配对码
- Android BIOMETRIC_STRONG + 不可导出 Keystore + 每次签名；取消和过期操作不能执行
- 未登录、错误设备、改动的签名载荷、重放、过期申请全部被拒绝
- VPS 重新检查 ComfyUI 队列与 GPU 状态，关机时状态不确定即阻断
- 小米通知（审核通过之后）和实际国行系统后台保活
- 在**授权的测试实例**完成状态查询，再由用户决定是否启用正式电源控制

当前 VPS 控制插件仍为 `read_only`，`gpu_control_enabled=false`。源码/CI 成功并不代表服务器已部署或真实 GPU 已受控。未通过上述验收前不打开电源写权限。

## 测试证书说明

`.github/workflows/ci-android-jipite.yml` 现在会在 CI runner 内创建短期一次性签名证书和**假的** Microsoft Client ID，编译并验证签名的 Android Release APK，以测试打包链路。这个 Release 测试文件**不会公开上传**，也不能拿来真实登录。正式 APK 只能通过手动 `connected` 模式和用户自己拥有的稳定签名密钥构建。

**MSAL 个人账户 Authority：** Android 模板明确配置 `PersonalMicrosoftAccount` 且设置 `default: true`，使交互登录与后续静默刷新统一使用消费者账号受众；VPS 仍验证真实个人账户租户 ID 与发行者。见 [微软 MSAL Android 配置说明](https://learn.microsoft.com/en-us/entra/msal/android/msal-configuration)。
