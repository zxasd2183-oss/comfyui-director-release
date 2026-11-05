# Director Studio V0.9.1 — Microsoft 个人账号网页登录

状态：代码与 CI 自动测试已完成；需要 VPS 所有者在 Microsoft 应用注册中添加 Web 平台、创建客户端凭据，并在 VPS 私人终端执行升级后才算上线。

正式地址：https://jipite.borealos.cn/studio/

## 安全机制

- 复用吉皮提现有 Microsoft 应用的 Client ID。安装器从已有安卓审批设备绑定数据库中只读读取唯一所有者身份标识，将 Studio 权限绑定到同一个 Microsoft 用户。其他 Microsoft 账号一律拒绝。
- 使用 MSAL 授权码流程及 PKCE、state、nonce；使用 Microsoft consumers JWKS 独立验证 ID Token 的 RSA 签名、固定 issuer、audience、tenant ID、nonce、exp 等。不能信任未经签名校验的身份内容。
- 不请求 Graph API 权限，也不请求长期 offline_access 权限。浏览器只有不透明 session Cookie，Secure、HttpOnly、SameSite=Lax、Path=/studio/，不存取微软令牌。Session 2 小时绝对超时，30 分钟空闲超时，重启失效。
- 页面、CSS/JS、生产 API、实时 SSE 全部受保护；会话 POST 有 CSRF 与 Origin 校验。
- Microsoft 不可用或没有配置时，新的公网代理接口只返回拒绝访问/服务不可用，不会自动变成匿名站点。
- 原有 /mcp/、/api/v1/mobile/、/app-updates/、手机指纹电源审批和 GPU 状态系统保持独立。

## 第一步：微软注册设置

在你用于吉皮提的 Microsoft Entra / Azure 应用注册中，找到**原来的应用**（不是重新注册一个不同 Client ID 的应用）：

1. Authentication（身份验证） → Add a platform（添加平台） → Web。
2. 增加精确 Redirect URI：

       https://jipite.borealos.cn/studio/auth/callback

3. 保留原先的个人 Microsoft 账号类型、安卓平台及其回调。
4. Certificates & secrets → New client secret，创建给 Studio 使用的 Web secret。
5. 保留刚显示的 Secret **Value**（不是 Secret ID），只在 VPS 私人终端输入，绝对不要发送到聊天、截图或 GitHub。

这是服务器端 Web 应用，不要把回调配置成 Single-page application (SPA)。

微软官方资料：
https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
https://learn.microsoft.com/en-us/entra/identity-platform/reply-url

## 第二步：在 VPS 安装

如果你还没有安装 V0.8.1 的临时 Basic Auth /studio/ 路由，请先：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/enable-jipite-domain.sh

已有 Basic Auth 站点的可以跳过这一步。然后运行：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/install-microsoft-web.sh

升级器会先运行所有测试、备份旧工作台、安装独立 MSAL/PyJWT 虚拟环境，并在终端不回显地询问 Web Secret Value。凭据由 root 独占文件保存，systemd LoadCredential 只向 Studio 服务提供私有副本。

只有在本地探测确认：未经认证的制作 API 返回 HTTP 401，授权入口正确跳转到 Microsoft 可信服务，并且 Nginx 语法验证通过之后，安装器才会撤掉 /studio/ 的临时 Basic Auth，切到 Microsoft 账号登录。失败则尝试恢复原 Basic Auth，不会开放匿名工作台。

## 第三步：验收

在浏览器打开 https://jipite.borealos.cn/studio/；网页应要求使用你之前绑定吉皮提的同一个 Microsoft 个人账号，登录后看到原来的 GPU 监控和 V0.9 全剧视听工程。错误 Microsoft 账号不得访问。

不需要任何凭据的 VPS 检查：

    curl -sS -o /dev/null -w '%{http_code}\n' https://jipite.borealos.cn/studio/api/v1/production
    sudo systemctl is-active director-studio
    sudo nginx -t
    sudo ss -ltn | grep ':8900'

第一项应是 401，服务应 active，8900 仍只绑定 127.0.0.1。退出登录以后必须失去访问权限；服务重启也应使旧会话失效。

## 重要限制

- 目前网站只读展示制作工程。导演艺术例外批准仍需在 VPS 本地 CLI 进行，不会由网页登录直接执行 GPU 任务。
- 同域不同路径并不隔离 JavaScript origin。如果将来允许直接取消/中断 GPU 工作，应考虑独立管理子域名与额外的操作级确认。
- 真实 Microsoft 网页端到端登录只有在你配置好 App registration 并完成浏览器登录后才能验证；CI 的模拟登录及真实 JWT 签名测试不能代替它。
- 如果 Microsoft JWKS 端点因为网络无法访问，则宁可登录失败，也不禁用签名验证。

## V0.9.1 回调故障修复（Microsoft session_state）

Microsoft 可能返回三个参数：code、state 和 session_state。早期 Studio 回调只接受前两个参数，会误拒绝正常登录并显示 microsoft_login_failed。修复版允许微软的可选 session_state，但仍严格验证浏览器 state Cookie、OAuth state、PKCE、已绑定所有者、JWT 签名与身份。

已经安装 Microsoft SSO 的 VPS 不需要重建应用或新建 Secret，直接运行：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/install-microsoft-web.sh

确认安装成功后，关闭以前失败的 callback 页面，**仅从 https://jipite.borealos.cn/studio/ 重新发起登录**。旧授权码是一次性的，不能使用刷新来重放。

如果仍然提示 microsoft_login_failed，可以在 VPS 的私人终端仅筛选安全分类日志：

    sudo journalctl -u director-studio --since '10 minutes ago' --no-pager | grep 'STUDIO_AUTH_CALLBACK_DENIED' | tail -n 5

只发送该命令的输出，不要发送原始 journalctl 全部日志、浏览器带 code 的回调 URL、客户端 Secret、会话 Cookie 或 ID Token。类别为 oidc_state_invalid、oidc_flow_expired、microsoft_token_exchange_failed、microsoft_token_verification_failed、microsoft_owner_not_authorized 或 oidc_internal_error 等。外部网页仍只显示通用错误，不泄露账号身份或认证信息。

## 回调参数名安全诊断（V0.9.1 补丁）

如果 Microsoft 跳回 /studio/auth/callback 后返回 403 microsoft_login_failed，并且 VPS 日志中出现 invalid_callback，**不代表一定缺少 code**：微软可能另外发送了参数，也可能返回 error/state 组合。仅根据看到的通用错误不能推断确切原因。

此补丁仅在 invalid_callback 记录可信参数名白名单（code、state、session_state、error、error_description、error_uri、iss、client_info）、参数数量、未知参数数量和重复数量；陌生参数名统一标记 other，不记录任意参数名或参数值，也不记录浏览器 URL、授权码、令牌或 Cookie。

已部署 Microsoft SSO 的 VPS，可安全升级代码而无需重建 Web Secret：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/install-microsoft-web.sh

然后只从 https://jipite.borealos.cn/studio/ **重新发起一次登录**，不要刷新旧回调页面或重复使用一次性授权码。失败后仅用下面的私有 VPS 命令看受限诊断日志：

    sudo journalctl -u director-studio --since '10 minutes ago' --no-pager | grep 'STUDIO_AUTH_CALLBACK_DENIED' | tail -n 5

可以把这条筛选输出发到聊天；不要贴完整 systemd 日志或包含 code、state 值的完整回调 URL。例如：

    STUDIO_AUTH_CALLBACK_DENIED invalid_callback param_names=error,error_description,state param_count=3 unknown_count=0 duplicates=0

如果是 microsoft_token_exchange_failed、microsoft_owner_not_authorized、oidc_state_invalid 等其他错误，不添加参数名细节，以避免扩散敏感认证材料。

## Microsoft client_info 回调兼容修复

VPS 已经观测到 Microsoft 回调包含 **code、state、client_info**，先前代码因为未允许 client_info 而错误拒绝登录。修复后的 HTTP 回调解析与身份验证层共同使用同一份允许参数集合：code、state、session_state、client_info。两个可选参数均有长度/字符验证，仍禁止重复、不认识的字段与缺少 code/state 的请求；PKCE、浏览器绑定 state、JWT 验签和原有 Microsoft 所有者匹配均保持强制。

诊断现在区分 **unknown_count**（完全未知的参数名）与 **unsupported_count**（已知但不允许用于认证的参数，比如 error_description）：即使 unknown_count=0，也能准确说明因已知但不支持的字段而拒绝。

已安装登录的 VPS 仍用原命令升级，**不需要新建 Microsoft 应用或重置客户端密钥**：

    cd ~/comfyui-director-release
    git pull --ff-only
    sudo bash studio/install-microsoft-web.sh

升级完成后从 https://jipite.borealos.cn/studio/ 新建登录流程，不要重放旧 callback URL。若仍出错，只提供筛选后的 STUDIO_AUTH_CALLBACK_DENIED 分类日志，不要分享 OAuth 参数值、Cookie 或私钥。
