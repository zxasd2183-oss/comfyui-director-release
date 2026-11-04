# 吉皮提 V0.6 Android 原生审批器

这是已提交 GitHub 的源码和部署工程，**不是已在手机或 VPS 安装好的正式 APK**。日常使用不需要审批网页。旧 V0.3 手机 TOTP 审批网页先保留作为故障恢复入口，直到 V0.6 真正验证通过。

## 操作流程

ChatGPT 通过现有 MCP 创建 5 分钟申请 -> 广州 VPS 的 V0.6 worker 通过 FCM 向安卓推送通知 -> 用户点击通知打开吉皮提 App -> App 从 VPS 重新获取申请类型/风险 -> 用户按下“批准”或“拒绝”并通过 Android BIOMETRIC_STRONG -> Android Keystore 使用不可导出的 P-256 私钥签署一次性挑战 -> VPS 用首个绑定设备的公钥校验 -> 再进行云实例状态和 ComfyUI 队列预检查 -> 提交一次实际云 API -> ChatGPT 通过只读工具核验最终状态。

Microsoft 个人账号只用于首次绑定及手机 API 身份校验。**Microsoft Authenticator 不能直接接收任意自定义 GPU 审批推送**；推送通知属于吉皮提 App。

## 安全边界

- 用户需 Microsoft 个人 ID Token 和一份 VPS root-only 的一次性高熵配对码才能首次绑定手机。
- 只允许一个首次绑定的账号和设备；不能用另外的微软账号绕过已有绑定。
- 每次批准都要求 Android Keystore + 强生物识别，在服务器端绑定 request_id、action、decision、nonce、expires、device_id 并验签。
- 签名不可重放。VPS 先将申请原子标记执行中，才在重新验证实例和队列后调用云 API；关机队列无法验证时绝不关机。
- 手机绝不保存云 GPU 电源 API 密钥、MCP 秘密 URL 或 SSH 私钥。
- 推送只是提醒，点通知不会直接操作 GPU。App 也支持手动“刷新待审批”。
- 安卓需要 API 30+ 且有 BIOMETRIC_STRONG。部分人脸识别方案不满足 strong 要求。
- FCM 需要 Google Play 服务和 VPS 能访问 Google FCM；中国大陆网络和部分国产安卓可能不稳定。**不能承诺实际推送成功**，没有 FCM 时仍可从 App 手动刷新。未来可增加国产推送。
- 旧的 TOTP 网页作为临时故障回退保留，不在本次改造中移除。

## A. 注册 Microsoft 个人账号 Android 应用

到 https://entra.microsoft.com 注册应用，Supported account types 选择支持个人微软账号的选项（Accounts in any organizational directory and personal Microsoft accounts）；客户端程序类型 Android，包名 cn.borealos.jipite。记录微软生成的公开 Application (Client) ID，并在 Android 平台登记**实际 APK 的签名证书哈希**与 redirect URI。Android debug 签名和 release 签名不同。

编辑 Android 工程：
- android-jipite/app/src/main/res/raw/msal_config.json 的 client_id 和 redirect_uri
- android-jipite/app/src/main/AndroidManifest.xml 中 BrowserTabActivity 的 android:path，填写**未 URL 编码**的 signing hash
- Microsoft Graph delegated User.Read scope 用于 MSAL 单账户登录
- MSAL authority 为 consumers；VPS 仅接受真正的个人账号身份租户 9188040d-6c67-4c5b-b112-36a304b66dad

**不需要 Microsoft 365 企业许可**，也不会在服务器保存微软账号密码。

官方文档：https://learn.microsoft.com/en-us/entra/msal/android/

## B. 可选：启用真正的 Firebase Cloud Messaging 推送

在 https://console.firebase.google.com/ 建立 Firebase 项目，注册 package cn.borealos.jipite，将真实 Android google-services.json 放到自己的 android-jipite/app/google-services.json（已 gitignore，不能提交）。启用 Firebase Cloud Messaging。

Firebase 服务端专用 service-account JSON 放在自己的广州 VPS：
    /etc/comfyui-director-firebase-service-account.json

需要 root:root 所有、0600 权限，不能交给聊天或 GitHub。VPS 的安装脚本检测到此文件才添加 systemd LoadCredential=firebase 并安装 Firebase Admin SDK。若 VPS 无法访问 FCM，Android 可以手动查看待审批清单。

官方文档：https://firebase.google.com/docs/cloud-messaging/send/admin-sdk

## C. 在广州 VPS 安装移动审批服务（8895 localhost）

前提：Microsoft App Registration Client ID 已准备。GPU V0.3 和旧 TOTP 服务保持运行。

    cd ~/comfyui-director-release
    git pull --ff-only
    cd vps-control
    sudo bash install-mobile-v06.sh
    sudo systemctl is-active director-mobile-v06
    curl -fsS http://127.0.0.1:8895/health

安装器首次提示输入 Microsoft Client ID，并生成 /etc/comfyui-director-mobile-pairing（root-only 0600）。在你自己的 VPS 私人 SSH 终端查看配对码，将其填入 Android App **一次**。别把配对码发给 ChatGPT。

只有 8895 localhost 服务，不打开 VPS 的 8895 入站防火墙，也不修改旧审批网页和云 GPU 运行状态。

## D. 加入现有的 Nginx jipite HTTPS 站点

不要重新签发证书或覆盖正在使用的 /etc/nginx/certs/borealos-new/。

    sudo install -o root -g root -m 0644 \
      vps-control/nginx-alidns/jipite-mobile.conf \
      /etc/nginx/snippets/jipite-mobile.conf

在现有 jipite.borealos.cn HTTPS server {} 里（不能加到 HTTP 301 块）增加：

    include /etc/nginx/snippets/jipite-mobile.conf;

再执行：

    sudo nginx -t && sudo systemctl reload nginx

五个原有站点和 200 占位页面都能保留。App 专用 HTTPS 接口为 https://jipite.borealos.cn/api/v1/mobile/ 。无 Microsoft bearer token 时应返回授权错误，不能匿名批准。

## E. Android Studio 构建与安装

在 Android Studio 中打开 android-jipite/ 目录，JDK 17，Gradle Sync，使用正确的微软 Client ID、签名哈希和真实 Firebase google-services.json 构建安装 APK 到自己的 Android 11+ 手机。

GitHub 的 Android CI 用无法访问真实账户的虚拟 Firebase 配置**只做编译测试**；没有实际的 Azure 注册配置和 Firebase credentials 不能投入生产。正式发版要安全保存签名密钥，APK 签名哈希需与 Microsoft Entra 应用注册一致。

## F. 联调与回退

1. 手机打开吉皮提 App，登录 Microsoft 个人账号，输入私人 VPS 一次性配对密钥，注册设备公钥；不需要审批网页。
2. ChatGPT 创建一张新的开机或关机申请；原申请 5 分钟过期。
3. 如果 FCM 可达，手机会收到通知；否则打开 App 点击“刷新待审批”。
4. 看清设备、动作、计费/数据风险后再选择“批准”或“拒绝”，完成一次强生物识别。
5. ChatGPT 查询 get_power_request_status 和 get_gpu_power_status，确认云平台真正完成。状态 submitted 只证明 API 已接受。
6. 未经真实设备测试和错误场景验证前不关闭旧 TOTP 备份，也不移除已有可以连接的 MCP 插件。

## 代码路径

- vps-control/mobile_v06_core.py：设备 enrollment、签名 challenge、验证、数据库原子消费
- vps-control/mobile_v06_api.py：Microsoft ID Token 验证、REST、FCM worker
- vps-control/install-mobile-v06.sh：VPS 安全安装
- vps-control/director-mobile-v06.service：systemd 限权 127.0.0.1:8895
- vps-control/nginx-alidns/jipite-mobile.conf：Nginx 路由
- android-jipite：Android Studio Kotlin 工程
- vps-control/tests/test_mobile_v06.py：离线安全测试
