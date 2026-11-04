# 吉皮提 V0.7 · Microsoft 联机准备与安全联调

适用于 MuMu 预览以及未来的个人 Microsoft 账号 + 小米真机正式审批。

## 已经实现

- V0.6.1 在 MuMu 上通过 6/6 项离线交互测试（人工测试，非真实 GPU 控制）。
- V0.7 Debug 安装包在所有 push flavor 下强制离线：不会初始化 MSAL、Push SDK 或联系 VPS。
- MuMu Debug 版增加“查看 V0.7 接入准备清单”，仅查看本地应用标识、强生物识别能力和模式。
- 正式签名的 **manualRelease connected** 增加“检测 VPS HTTPS 审批接口”：
  - 不发送身份令牌、配对码、设备 ID 或签名。
  - 只向 `https://jipite.borealos.cn/api/v1/mobile/pending` POST 空 JSON。
  - 仅当得到 `401 {"reason":"microsoft_login_required"}` 时报告网关可达且要求登录。
  - **HTTPS 探测成功不等于微软登录成功，更不代表 GPU 操作已准备好。**

## 需要仓库所有者自己完成的一次性配置

**必须在自己的受信任电脑或 VPS 上操作；不要发送到 ChatGPT。**

1. Microsoft Entra (https://entra.microsoft.com) 注册支持**个人 Microsoft 账号**的 Android 应用。包名固定为 `cn.borealos.jipite`。保存 *Application (client) ID*（公开应用标识）。
2. 生成并长期备份稳定的 Android PKCS12 签名密钥（安全持有密码，绝不可提交源码或聊天）。可以参考 [GITHUB_BUILD.md](./GITHUB_BUILD.md) 中的 `keytool` 交互式命令。
3. GitHub 仓库 Settings → Secrets and variables → Actions：
   - **Repository variables:** `JIPITE_MS_CLIENT_ID` 和 `JIPITE_SIGNING_KEY_ALIAS`。
   - **Repository secrets:** `JIPITE_KEYSTORE_BASE64`、`JIPITE_SIGNING_STORE_PASSWORD`、`JIPITE_SIGNING_KEY_PASSWORD`。
4. GitHub Actions → **Build Jipite APK on GitHub** → **Run workflow** → `mode=connected`。
5. 本次构建会从稳定签名证书生成 **Base64 SHA-1 Android Signature Hash**，写入 Actions 运行摘要。将包名和这个**公有签名哈希**登记到 Microsoft Entra App Registration 的 Android 平台（而不是把 Base64 keystore 或密码上传到 Entra）。
6. 下载 `Jipite-V0.7-Microsoft-connected-signed` 产物里的 `app-manual-release.apk`。先验证 Microsoft 个人账号能登录，以及无凭证的 HTTPS 连通性预检。

> 第 4 步如果缺少 GitHub Variables/Secrets 会**明确构建失败**，不会退化成用临时 Debug 签名或占位 Client ID 的冒牌联机版。

## 真正的 VPS / GPU 连接尚需另外验收

- 当前连接的 VPS 控制中心报告为 `mode=read_only`、`gpu_control_enabled=false`（2026-11-03 聊天读取结果）；不能据此声称已经可以执行电源操作。
- 有关 VPS V0.6 API 的部署准备、旧 TOTP 回退以及只开放内部 `127.0.0.1:8895` 的操作，请看 [MOBILE_V06.md](../vps-control/MOBILE_V06.md)。**源码提交或 CI 通过不代表 VPS 已部署**。
- 初次绑定需在**真实的受信任 Android 手机**中输入仅在个人 VPS 私人终端出现的一次性配对码。**不要把生产配对码输入 MuMu 模拟器**。
- MuMu 的生物识别模拟能力不能证明 StrongBox/TEE/Android Keystore 的真实硬件保护；生产批准、锁屏通知和小米 Mi Push 必须在小米真机上完成最终验证。
- 后端测试通过模拟身份、模拟设备 P-256 签名和本地 SQLite 检查授权、拒绝、重放与原子消费；**测试不会调用真实云 GPU API**。

## 下一轮 MuMu 测试（V0.7 preview）

- [ ] 打开应用看到 `0.7.0-beta1`（通过系统应用信息）和“离线演示 / MuMu 测试”。
- [ ] “查看 V0.7 接入准备清单”有响应，明确显示 Debug 离线模式。
- [ ] 微软登录/绑定/真实刷新不可用，模拟开关机仍可批准/拒绝，且不会离开应用。
- [ ] 断网后，准备检查与模拟审批仍可用。
- [ ] 无论从通知或模拟器快捷方式返回，均不会触发真实 `jipite.borealos.cn` API。

## 唯一可变更的在线部分

此阶段只更新 GitHub 源码/构建工作流和只在内存中的探测操作。未触及生产 VPS、既有 TOTP 网站、云 API 或设备电源设置。
