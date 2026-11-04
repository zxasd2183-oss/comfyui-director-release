package cn.borealos.jipite

import android.Manifest
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.util.Base64
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.microsoft.identity.client.AuthenticationCallback
import com.microsoft.identity.client.IAuthenticationResult
import com.microsoft.identity.client.IPublicClientApplication
import com.microsoft.identity.client.ISingleAccountPublicClientApplication
import com.microsoft.identity.client.PublicClientApplication
import com.microsoft.identity.client.SilentAuthenticationCallback
import com.microsoft.identity.client.exception.MsalException
import org.json.JSONObject
import java.security.Signature
import java.time.Instant

/** Owner's Android app: Microsoft personal login binds the device.
 * Each GPU request is approved ONLY after an explicit tap and per-use
 * BIOMETRIC_STRONG Keystore ECDSA signature.
 */
class MainActivity : FragmentActivity() {
    private val prefs by lazy { getSharedPreferences("jipite-device", MODE_PRIVATE) }
    private var msal: ISingleAccountPublicClientApplication? = null
    private var cachedIdToken: String? = null
    private var current: JSONObject? = null
    private var hintRequestId: String? = null
    // GitHub preview builds are deliberately offline; real approval must use a signed release.
    // All debug flavors are strictly offline. Only a properly configured, signed release
    // can initialize Microsoft authentication or reach the owner-controlled backend.
    private val isOfflinePreview: Boolean
        get() = BuildConfig.DEBUG
    private lateinit var status: TextView
    private lateinit var detail: TextView
    private lateinit var readiness: TextView
    private lateinit var microsoftState: TextView
    private var loginConfirmedInSession = false
    private lateinit var pairing: EditText
    private lateinit var approveButton: Button
    private lateinit var denyButton: Button
    private lateinit var updateCheckButton: Button
    private lateinit var updateDownloadButton: Button
    private lateinit var updateInstallButton: Button
    private lateinit var updateStatus: TextView
    private lateinit var updateProgress: android.widget.ProgressBar
    private var latestUpdate: SecureUpdater.Release? = null
    private var downloadedUpdate: java.io.File? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        hintRequestId = PushBootstrap.requestIdFromIntent(intent)
        buildUi()
        if (isOfflinePreview) {
            setStatus("V0.8 MuMu 离线演示：不会连接微软、VPS 或 GPU")
            return
        }
        if (!microsoftConfigured()) {
            setStatus("尚未配置真实微软 Client ID：请使用 GitHub Actions connected 签名版")
            return
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 42)
        }
        // Only the chosen product flavor initializes a push SDK.
        // Xiaomi builds NEVER initialize Firebase/Google Play Services.
        PushBootstrap.initialize(this) { pushToken ->
            val existing = prefs.getString("fcm_token", null)
            if (existing != pushToken) {
                prefs.edit().putString("fcm_token", pushToken).apply()
                if (prefs.getString("device_id", null) != null) syncPushToken()
            }
        }
        PublicClientApplication.createSingleAccountPublicClientApplication(
            this, R.raw.msal_config,
            object : IPublicClientApplication.ISingleAccountApplicationCreatedListener {
                override fun onCreated(application: ISingleAccountPublicClientApplication) {
                    msal = application
                    application.getCurrentAccountAsync(object : ISingleAccountPublicClientApplication.CurrentAccountCallback {
                        override fun onAccountLoaded(account: com.microsoft.identity.client.IAccount?) {
                            if (account != null) {
                                cachedIdToken = account.idToken
                                loginConfirmedInSession = true
                                setMicrosoftState("微软账号：已登录（已从安全账户缓存恢复）")
                                if (deviceId() != null) {
                                    refresh()
                                } else {
                                    setStatus("Microsoft 登录状态已恢复。尚未绑定手机；请在小米真机完成首次配对。")
                                }
                            } else if (!loginConfirmedInSession) {
                                setMicrosoftState("微软账号：未登录")
                                setStatus("请先使用 Microsoft 个人账号登录")
                            }
                        }
                        override fun onAccountChanged(
                            priorAccount: com.microsoft.identity.client.IAccount?,
                            currentAccount: com.microsoft.identity.client.IAccount?
                        ) {
                            if (priorAccount?.id != currentAccount?.id) {
                                cachedIdToken = null
                                current = null
                                showRequest(null)
                                if (currentAccount == null) {
                                    loginConfirmedInSession = false
                                    setMicrosoftState("微软账号：未登录")
                                }
                            }
                        }
                        override fun onError(exception: MsalException) {
                            setMicrosoftState("微软账号：读取账户失败（${msalErrorCode(exception)}）")
                            setStatus("请检查网络、微软应用注册以及 Android 回调配置")
                        }
                    })
                }
                override fun onError(exception: MsalException) {
                    setMicrosoftState("微软账号：初始化失败（${msalErrorCode(exception)}）")
                    setStatus("请核对 client_id、Android 签名哈希及网络连接")
                }
            }
        )
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        hintRequestId = PushBootstrap.requestIdFromIntent(intent)
        if (!isOfflinePreview) refresh()
    }

    // Fluent-inspired, original Android UI: quiet neutral canvas, Windows-like
    // surfaces, restrained blue accent, clear typography and accessible spacing.
    private fun buildUi() {
        val bg = android.graphics.Color.rgb(246, 248, 252)
        val ink = android.graphics.Color.rgb(29, 34, 43)
        val subdued = android.graphics.Color.rgb(98, 108, 125)
        val blue = android.graphics.Color.rgb(0, 103, 192)
        val border = android.graphics.Color.rgb(224, 229, 236)
        val white = android.graphics.Color.WHITE
        fun dp(value: Int): Int = (value * resources.displayMetrics.density + 0.5f).toInt()
        fun surface(color: Int, stroke: Int? = null, radius: Int = 16): android.graphics.drawable.GradientDrawable {
            return android.graphics.drawable.GradientDrawable().apply {
                setColor(color)
                cornerRadius = dp(radius).toFloat()
                if (stroke != null) setStroke(dp(1), stroke)
            }
        }
        val scroll = ScrollView(this).apply {
            setBackgroundColor(bg)
            isFillViewport = true
            clipToPadding = false
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(36))
        }
        scroll.addView(root)

        fun text(
            parent: LinearLayout, value: String, sp: Float = 14f,
            color: Int = ink, strong: Boolean = false
        ): TextView {
            val label = TextView(this).apply {
                this.text = value
                textSize = sp
                setTextColor(color)
                typeface = android.graphics.Typeface.create(
                    if (strong) "sans-serif-medium" else "sans-serif",
                    android.graphics.Typeface.NORMAL
                )
                setLineSpacing(dp(2).toFloat(), 1f)
            }
            parent.addView(label)
            return label
        }

        fun section(title: String, subtitle: String): LinearLayout {
            val label = text(root, title, 19f, ink, true)
            label.setPadding(dp(2), dp(24), dp(2), dp(5))
            val sub = text(root, subtitle, 12f, subdued)
            sub.setPadding(dp(2), 0, dp(2), dp(10))
            return LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                background = surface(white, border)
                setPadding(dp(18), dp(18), dp(18), dp(18))
                elevation = dp(2).toFloat()
                root.addView(
                    this,
                    LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                    ).apply { bottomMargin = dp(5) }
                )
            }
        }

        fun spacer(parent: LinearLayout, h: Int) {
            parent.addView(
                View(this),
                LinearLayout.LayoutParams(1, dp(h))
            )
        }

        fun action(
            parent: LinearLayout, title: String, filled: Boolean = false,
            callback: () -> Unit
        ): Button {
            val fill = if (filled) blue else android.graphics.Color.rgb(248, 250, 253)
            val outline = if (filled) blue else border
            val ripple = android.graphics.drawable.RippleDrawable(
                android.content.res.ColorStateList.valueOf(
                    if (filled) 0x33FFFFFF else 0x220067C0
                ),
                surface(fill, outline, 10),
                null
            )
            val button = Button(this).apply {
                text = title
                isAllCaps = false
                textSize = 14f
                typeface = android.graphics.Typeface.create(
                    "sans-serif-medium", android.graphics.Typeface.NORMAL
                )
                setTextColor(if (filled) white else blue)
                background = ripple
                stateListAnimator = null
                minHeight = 0
                minimumHeight = 0
                setPadding(dp(12), dp(12), dp(12), dp(12))
                setOnClickListener { callback() }
            }
            parent.addView(
                button,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(48)
                ).apply { bottomMargin = dp(10) }
            )
            return button
        }

        // Original monogram instead of any Microsoft-owned logo or branding.
        val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val mark = TextView(this).apply {
            text = "J"
            textSize = 26f
            gravity = android.view.Gravity.CENTER
            setTextColor(white)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            background = surface(blue, radius = 14)
        }
        header.addView(mark, LinearLayout.LayoutParams(dp(56), dp(56)))
        val heading = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(4), 0, 0)
        }
        text(heading, "吉皮提", 25f, ink, true)
        text(heading, "GPU 安全审批中心", 13f, subdued)
        header.addView(heading)
        root.addView(header)
        spacer(root, 18)

        val overview = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = surface(android.graphics.Color.rgb(233, 243, 255),
                android.graphics.Color.rgb(202, 223, 247))
            setPadding(dp(18), dp(18), dp(18), dp(18))
        }
        text(overview, if (isOfflinePreview) "安全离线预览" else "账户与设备安全", 13f, blue, true)
        spacer(overview, 8)
        status = text(overview, "正在初始化……", 15f, ink, true)
        spacer(overview, 8)
        text(overview, "每次真实审批都必须单独确认并完成强生物识别。", 12f, subdued)
        root.addView(overview)
        val account = section("Microsoft 账户", "使用个人 Microsoft 账号验证身份")
        microsoftState = text(
            account,
            if (isOfflinePreview) "微软账号：离线演示版不提供真实登录"
            else "微软账号：正在读取登录状态……",
            15f, ink, true
        )
        spacer(account, 14)
        val loginButton = action(account, "使用 Microsoft 账号登录 / 重新验证", true) { signIn() }
        val network = section("安全连接", "VPS HTTPS · Microsoft 身份保护")
        readiness = text(network, "点击诊断按钮查看连接和设备状态。", 13f, subdued)
        spacer(network, 14)
        action(network, "查看连接与安全准备清单") {
            readiness.text = readinessReport()
        }
        if (!isOfflinePreview) {
            action(network, "检测 VPS HTTPS 审批接口") {
                readiness.text = "正在验证 HTTPS 与身份认证保护……"
                MobileApi.probe { result ->
                    runOnUiThread {
                        readiness.text = result.fold(
                            onSuccess = { it },
                            onFailure = { "HTTPS 检测失败：请检查网络或 VPS 接口。" }
                        )
                    }
                }
            }
        }

        val approval = section("待审批申请", "先阅读操作信息，再决定是否允许")
        detail = text(approval, "暂无待审批申请", 16f, ink, true)
        spacer(approval, 14)
        val refreshButton = action(approval, "刷新待审批申请") { refresh() }
        denyButton = action(approval,
            if (isOfflinePreview) "模拟拒绝（不发送）" else "拒绝本次操作"
        ) { requestDecision("deny") }
        approveButton = action(approval,
            if (isOfflinePreview) "模拟批准（不发送）" else "使用指纹 / 面容批准",
            true
        ) { requestDecision("approve") }
        showRequest(null)

        val enrollment = section("设备绑定", "首次配对仅限受信任、具备强生物识别的真机")
        text(enrollment, "一次性 VPS 配对密钥", 13f, subdued, true)
        spacer(enrollment, 8)
        pairing = EditText(this).apply {
            hint = "不要把配对密钥发送给任何人"
            textSize = 14f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            isSingleLine = true
            setTextColor(ink)
            setHintTextColor(subdued)
            background = surface(white, border, 10)
            setPadding(dp(12), 0, dp(12), 0)
        }
        enrollment.addView(
            pairing, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(50)
            )
        )
        spacer(enrollment, 12)
        val enrollButton = action(enrollment, "绑定此手机（仅首次）") { enrollPhone() }
        if (isOfflinePreview) {
            loginButton.isEnabled = false
            loginButton.alpha = 0.45f
            enrollButton.isEnabled = false
            enrollButton.alpha = 0.45f
            refreshButton.isEnabled = false
            refreshButton.alpha = 0.45f
            pairing.isEnabled = false
            val demo = section("离线演示", "本地模拟申请，绝不会连接 Microsoft、VPS 或 GPU")
            action(demo, "模拟开机申请") { showOfflineDemo("start") }
            action(demo, "模拟关机申请") { showOfflineDemo("stop") }
            action(demo, "清除模拟申请") {
                current = null
                showRequest(null)
                setStatus("已清除本地模拟申请")
            }
        }

        val about = section("关于与更新", "应用版本、更新状态与安全安装")
        text(about, "吉皮提 · Version " + BuildConfig.VERSION_NAME, 16f, ink, true)
        spacer(about, 5)
        text(about, "构建编号 " + BuildConfig.VERSION_CODE.toString() +
            "  ·  " + (if (isOfflinePreview) "离线预览版" else "Microsoft 联机版"),
            12f, subdued)
        spacer(about, 14)
        updateStatus = text(about,
            if (isOfflinePreview) "离线演示不下载或安装真实更新。"
            else "可手动检查更新；下载后由 Android 系统确认安装。",
            13f, subdued)
        spacer(about, 10)
        updateProgress = android.widget.ProgressBar(
            this, null, android.R.attr.progressBarStyleHorizontal
        ).apply {
            max = 100
            progress = 0
            visibility = View.GONE
            progressTintList = android.content.res.ColorStateList.valueOf(blue)
        }
        about.addView(updateProgress, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(5)
        ))
        spacer(about, 12)
        updateCheckButton = action(about, "检查更新") { checkForAppUpdates() }
        updateDownloadButton = action(about, "在应用内下载新版") { downloadAppUpdate() }
        updateInstallButton = action(about, "安装已验证的新版", true) { installAppUpdate() }
        updateDownloadButton.isEnabled = false
        updateInstallButton.isEnabled = false
        updateDownloadButton.alpha = 0.45f
        updateInstallButton.alpha = 0.45f
        if (isOfflinePreview) {
            updateCheckButton.isEnabled = false
            updateCheckButton.alpha = 0.45f
        }

        spacer(root, 14)
        text(root, "吉皮提是独立 GPU 审批应用，界面采用 Fluent 风格设计。", 11f, subdued)
        setContentView(scroll)
    }

    private fun checkForAppUpdates() {
        if (BuildConfig.DEBUG) return
        updateCheckButton.isEnabled = false
        updateStatus.text = "正在从官方发布仓库获取版本信息……"
        SecureUpdater.check(this) { result ->
            updateCheckButton.isEnabled = true
            result.fold(
                onSuccess = { release ->
                    latestUpdate = release
                    if (release == null) {
                        updateStatus.text = "当前已是最新版本（" + BuildConfig.VERSION_NAME + "）。"
                    } else {
                        downloadedUpdate = null
                        updateInstallButton.isEnabled = false
                        updateInstallButton.alpha = 0.45f
                        updateDownloadButton.isEnabled = true
                        updateDownloadButton.alpha = 1f
                        updateStatus.text = "发现新版本 " + release.version +
                            " · " + (release.size / 1024 / 1024) + " MB。请点击下载。"
                    }
                },
                onFailure = { error ->
                    updateStatus.text = "检查失败：" + (error.message ?: "网络连接异常") +
                        "。可稍后重试。"
                }
            )
        }
    }

    private fun downloadAppUpdate() {
        val release = latestUpdate ?: return
        updateDownloadButton.isEnabled = false
        updateDownloadButton.alpha = 0.45f
        updateCheckButton.isEnabled = false
        updateProgress.visibility = View.VISIBLE
        updateProgress.progress = 0
        updateStatus.text = "正在通过 HTTPS 下载更新包……"
        SecureUpdater.download(this, release,
            progress = { percent ->
                updateProgress.progress = percent
                updateStatus.text = "正在下载 " + release.version + " · " + percent + "%"
            },
            complete = { result ->
                updateCheckButton.isEnabled = true
                result.fold(
                    onSuccess = { file ->
                        downloadedUpdate = file
                        updateProgress.progress = 100
                        updateStatus.text = "下载成功！SHA-256、包名、版本和 APK 签名全部验证通过。"
                        updateInstallButton.isEnabled = true
                        updateInstallButton.alpha = 1f
                    },
                    onFailure = { error ->
                        updateProgress.visibility = View.GONE
                        updateStatus.text = "更新已阻止：" + (error.message ?: "下载或校验失败")
                        updateDownloadButton.isEnabled = true
                        updateDownloadButton.alpha = 1f
                    }
                )
            }
        )
    }

    private fun installAppUpdate() {
        val file = downloadedUpdate ?: return
        try {
            val version = latestUpdate?.version ?: return
            val started = SecureUpdater.requestInstall(this, file, version)
            updateStatus.text = if (started)
                "已打开 Android 系统安装确认；请核对版本并选择安装。"
            else
                "请在系统设置中允许吉皮提安装更新，然后返回应用再次点击安装。"
        } catch (error: Exception) {
            updateStatus.text = "系统安装被阻止：" + (error.message ?: "请重新下载更新")
            updateInstallButton.isEnabled = false
            updateInstallButton.alpha = 0.45f
        }
    }

    private fun setStatus(message: String) {
        runOnUiThread { status.text = message }
    }

    private fun setMicrosoftState(message: String) {
        runOnUiThread { microsoftState.text = message }
    }

    // MSAL error codes are diagnostic identifiers, not access tokens or credentials.
    private fun msalErrorCode(error: MsalException): String =
        error.errorCode?.take(80) ?: "unknown"

    /** Metadata-only checks; never validates the signing key against Entra or VPS. */
    private fun microsoftConfigured(): Boolean {
        return runCatching {
            val raw = resources.openRawResource(R.raw.msal_config)
                .bufferedReader(Charsets.UTF_8).use { it.readText() }
            val json = JSONObject(raw)
            val clientId = json.optString("client_id")
            clientId.matches(Regex("[0-9a-fA-F-]{36}")) &&
                clientId != "00000000-0000-0000-0000-000000000000" &&
                json.optString("redirect_uri").startsWith("msauth://cn.borealos.jipite/")
        }.getOrDefault(false)
    }

    private fun readinessReport(): String {
        val microsoft = if (microsoftConfigured()) "已写入 Client ID（还需真实登录验证）"
                        else "未配置真实 Client ID"
        val biometric = if (BiometricManager.from(this).canAuthenticate(
                BiometricManager.Authenticators.BIOMETRIC_STRONG
            ) == BiometricManager.BIOMETRIC_SUCCESS) "可检测到强生物识别"
            else "未检测到可用的强生物识别（MuMu 模拟结果不代表硬件安全）"
        val mode = if (isOfflinePreview) "Debug 离线演示：禁用所有真实审批"
                   else "Release 联机模式：仍需登录、配对及 VPS 验签"
        return "当前模式：$mode\n微软应用：$microsoft\n生物识别：$biometric\n" +
            "VPS 后端部署与真实 GPU 操作必须单独验收。"
    }

    private fun deviceId() = prefs.getString("device_id", null)
    private fun present(result: Result<JSONObject>, then: (JSONObject) -> Unit) {
        runOnUiThread {
            result.onSuccess(then)
            result.onFailure { setStatus("请求失败：" + (it.message ?: "网络或登录异常")) }
        }
    }

    private fun signIn() {
        if (isOfflinePreview || !microsoftConfigured()) {
            return setStatus("需要正式签名与 Microsoft 配置才能登录")
        }
        val app = msal ?: return setStatus("MSAL 初始化尚未完成，请重新点击登录")
        setMicrosoftState("微软账号：正在启动 Microsoft 登录……")
        setStatus("请在微软浏览器页面完成登录，授权后将返回吉皮提")
        val callback = object : AuthenticationCallback {
            override fun onSuccess(result: IAuthenticationResult) {
                val token = result.account.idToken
                if (token.isNullOrBlank()) {
                    loginConfirmedInSession = false
                    setMicrosoftState("微软账号：登录回调已完成，但缺少 ID Token")
                    setStatus("暂时无法进行设备绑定，请重新验证微软登录")
                    return
                }
                cachedIdToken = token
                loginConfirmedInSession = true
                setMicrosoftState("微软账号：登录成功 ✓（已取得 Microsoft 身份凭据）")
                if (deviceId() != null) {
                    refresh()
                } else {
                    setStatus("Microsoft 登录成功！此设备尚未绑定 VPS；MuMu 只用于登录测试，请使用小米真机完成配对。")
                }
            }
            override fun onError(exception: MsalException) {
                setMicrosoftState("微软账号：登录失败（${msalErrorCode(exception)}）")
                setStatus("请检查浏览器回调、网络及微软账号授权。不要分享登录令牌。")
            }
            override fun onCancel() {
                setMicrosoftState("微软账号：登录已取消")
                setStatus("已取消 Microsoft 登录，未进行设备绑定")
            }
        }
        app.getCurrentAccountAsync(object : ISingleAccountPublicClientApplication.CurrentAccountCallback {
            override fun onAccountLoaded(account: com.microsoft.identity.client.IAccount?) {
                val scopes = arrayOf("User.Read")
                if (account == null) app.signIn(this@MainActivity, null, scopes, callback)
                else app.signInAgain(this@MainActivity, scopes, null, callback)
            }
            override fun onAccountChanged(
                priorAccount: com.microsoft.identity.client.IAccount?,
                currentAccount: com.microsoft.identity.client.IAccount?) {}
            override fun onError(exception: MsalException) {
                setMicrosoftState("微软账号：读取登录状态失败（${msalErrorCode(exception)}）")
                setStatus("无法确认已登录账号，请稍后重试")
            }
        })
    }

    /** Silent MSAL token renewal; if it fails, require explicit Microsoft login. */
    private fun withMicrosoftToken(next: (String) -> Unit) {
        if (isOfflinePreview || !microsoftConfigured()) return setStatus("本版本未启用真实登录")
        val app = msal ?: return setStatus("请先初始化微软登录")
        app.acquireTokenSilentAsync(
            arrayOf("User.Read"),
            "https://login.microsoftonline.com/consumers",
            object : SilentAuthenticationCallback {
                override fun onSuccess(result: IAuthenticationResult) {
                    val token = result.account.idToken
                    if (token.isNullOrBlank()) setStatus("缺少 ID Token，请重新登录微软账号")
                    else {
                        cachedIdToken = token
                        next(token)
                    }
                }
                override fun onError(exception: MsalException) {
                    setStatus("微软登录已过期，请点击登录/重新验证")
                }
            }
        )
    }

    private fun enrollPhone() {
        val code = pairing.text.toString()
        if (code.length < 32) return setStatus("请输入从 VPS 私人终端读取的配对密钥")
        if (BiometricManager.from(this).canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG)
            != BiometricManager.BIOMETRIC_SUCCESS) {
            return setStatus("手机需要先设置强生物识别（指纹或支持的安全面容）")
        }
        val pub = try { ApprovalKey.publicKeyBase64() }
                  catch (e: Exception) { return setStatus("无法创建 Android Keystore 审批密钥") }
        withMicrosoftToken { token ->
            MobileApi.post("enroll", token, JSONObject()
                .put("pairing_code", code).put("public_key", pub)
                .put("fcm_token", prefs.getString("fcm_token", "") ?: "")) { response ->
                present(response) { json ->
                    prefs.edit().putString("device_id", json.getString("device_id")).apply()
                    pairing.text.clear()
                    setStatus("手机绑定成功。今后只需打开推送并使用生物识别")
                    refresh()
                }
            }
        }
    }

    private fun syncPushToken() {
        val id = deviceId() ?: return
        withMicrosoftToken { token ->
            MobileApi.post("push", token, JSONObject()
                .put("device_id", id)
                .put("fcm_token", prefs.getString("fcm_token", "") ?: "")) { result ->
                result.onFailure { setStatus("通知令牌同步失败，仍可手动刷新") }
            }
        }
    }

    private fun refresh() {
        val id = deviceId() ?: return setStatus("尚未绑定手机，请完成首次配对")
        withMicrosoftToken { token ->
            MobileApi.post("pending", token, JSONObject().put("device_id", id)) { response ->
                present(response) { json ->
                    val array = json.getJSONArray("requests")
                    var chosen: JSONObject? = null
                    for (i in 0 until array.length()) {
                        val item = array.getJSONObject(i)
                        if (chosen == null || item.optString("request_id") == hintRequestId) {
                            chosen = item
                            if (item.optString("request_id") == hintRequestId) break
                        }
                    }
                    current = chosen
                    showRequest(chosen)
                    setStatus(if (chosen == null) "没有待审批的 GPU 操作" else "请检查操作类型、费用和风险")
                    syncPushToken()
                }
            }
        }
    }

    private fun showRequest(item: JSONObject?) {
        if (!::detail.isInitialized) return
        if (item == null) {
            detail.text = "暂无待审批申请"
            approveButton.isEnabled = false
            denyButton.isEnabled = false
            return
        }
        val action = item.optString("action")
        if (action !in setOf("start", "stop")) {
            detail.text = "未知 GPU 操作类型：不允许审批"
            approveButton.isEnabled = false
            denyButton.isEnabled = false
            return
        }
        val title = if (action == "start") "启动 GPU 实例" else "关闭 GPU 实例"
        val warning = if (action == "start") "审批后可能产生 GPU 租赁费用"
                      else "请先确认任务结束、文件已保存到持久化存储"
        detail.text = title + "\n" + warning + "\n申请：" +
            item.optString("request_id") + "\n有效期：到 " +
            Instant.ofEpochSecond(item.optLong("expires_at")).toString()
        approveButton.isEnabled = true
        denyButton.isEnabled = true
    }

    /** In a debug manual build, no production identity, key, or network API is used. */
    private fun showOfflineDemo(action: String) {
        if (!isOfflinePreview || action !in setOf("start", "stop")) return
        current = JSONObject()
            .put("request_id", "DEMO-" + System.currentTimeMillis())
            .put("action", action)
            .put("expires_at", System.currentTimeMillis() / 1000 + 300)
        showRequest(current)
        setStatus("本地模拟申请已生成：仅用于查看界面和审批确认，不会操作 GPU")
    }

    private fun confirmOfflineDecision(decision: String) {
        if (!isOfflinePreview) return
        val item = current ?: return setStatus("没有模拟申请")
        if (System.currentTimeMillis() / 1000 >= item.optLong("expires_at")) {
            current = null
            showRequest(null)
            return setStatus("模拟申请已过期，请重新生成")
        }
        val verb = if (decision == "approve") "批准" else "拒绝"
        val action = if (item.optString("action") == "start") "开机" else "关机"
        AlertDialog.Builder(this)
            .setTitle("离线模拟：$verb$action")
            .setMessage("仅用于 MuMu 模拟器测试。不进行真实指纹验证，不向 VPS 发送数据，不执行 GPU 开关机。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认模拟") { _, _ ->
                current = null
                showRequest(null)
                setStatus("已模拟$verb$action。没有发送请求，GPU 状态未被本应用改变。")
            }
            .show()
    }

    /**
     * The bytes received from the VPS must be exactly the canonical payload
     * for the action that was displayed. Never sign arbitrary server-provided
     * Base64, even over HTTPS.
     */
    private fun challengeMatches(
        challenge: JSONObject, item: JSONObject, decision: String, deviceId: String
    ): Boolean {
        val requestId = item.optString("request_id")
        val action = item.optString("action")
        val expiry = challenge.optLong("expires_at")
        val now = System.currentTimeMillis() / 1000
        val nonce = challenge.optString("nonce")
        if (requestId.length !in 20..80) return false
        if (action !in setOf("start", "stop") || decision !in setOf("approve", "deny")) return false
        if (!nonce.matches(Regex("[A-Za-z0-9_-]{24,96}"))) return false
        if (expiry <= now || expiry > now + 90 || expiry > item.optLong("expires_at")) return false
        if (challenge.optString("request_id") != requestId ||
            challenge.optString("action") != action ||
            challenge.optString("decision") != decision) return false
        val canonical = (
            "JIPITE-V0.6\n" + requestId + "\n" + action + "\n" + decision +
                "\n" + nonce + "\n" + expiry + "\n" + deviceId
        ).toByteArray(Charsets.US_ASCII)
        val received = try {
            Base64.decode(challenge.getString("payload_b64"), Base64.DEFAULT)
        } catch (_: Exception) { return false }
        return received.contentEquals(canonical)
    }

    private fun requestDecision(decision: String) {
        if (isOfflinePreview) return confirmOfflineDecision(decision)
        if (!microsoftConfigured()) return setStatus("未配置正式微软身份，禁止审批")
        val item = current ?: return setStatus("没有待审批申请")
        val requestId = item.optString("request_id")
        val action = item.optString("action")
        if (action !in setOf("start", "stop") || decision !in setOf("approve", "deny") ||
            requestId.length !in 20..80) {
            return setStatus("操作信息异常，禁止审批")
        }
        val id = deviceId() ?: return setStatus("设备未绑定")
        if (System.currentTimeMillis() / 1000 >= item.optLong("expires_at")) {
            return setStatus("申请已过期，请重新刷新")
        }
        val verb = if (decision == "approve") "批准" else "拒绝"
        val operation = if (action == "start") "启动 GPU（可能计费）" else "关闭 GPU（可能丢失数据）"
        AlertDialog.Builder(this)
            .setTitle("确认$verb$operation？")
            .setMessage("请核对申请编号：$requestId\n下一步需使用强生物识别签名，取消不会执行操作。")
            .setNegativeButton("取消", null)
            .setPositiveButton("继续验证") { _, _ ->
                // Fetch a fresh challenge only after a deliberate confirmation.
                withMicrosoftToken { token ->
                    MobileApi.post("challenge", token, JSONObject()
                        .put("device_id", id)
                        .put("request_id", requestId)
                        .put("decision", decision)) { response ->
                        present(response) { challenge ->
                            if (!challengeMatches(challenge, item, decision, id)) {
                                return@present setStatus("挑战内容、时效或操作信息不一致，拒绝签名")
                            }
                            val signature = try { ApprovalKey.signatureForBiometric() }
                                            catch (_: Exception) {
                                                return@present setStatus("审批密钥不可用，请检查生物识别状态")
                                            }
                            askBiometric(signature, challenge, token, id, decision)
                        }
                    }
                }
            }.show()
    }

    private fun askBiometric(signature: Signature, challenge: JSONObject, token: String,
                             id: String, decision: String) {
        val action = challenge.optString("action")
        val verb = if (decision == "deny") "拒绝" else "批准"
        val title = if (action == "start") "启动 GPU 实例" else "关闭 GPU 实例"
        val prompt = BiometricPrompt(
            this, ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    super.onAuthenticationSucceeded(result)
                    try {
                        val payload = Base64.decode(challenge.getString("payload_b64"), Base64.DEFAULT)
                        val unlocked = result.cryptoObject?.signature
                            ?: error("Missing authenticated signing operation")
                        unlocked.update(payload)
                        val signed = Base64.encodeToString(unlocked.sign(), Base64.NO_WRAP)
                        MobileApi.post("decision", token, JSONObject()
                            .put("device_id", id)
                            .put("request_id", challenge.getString("request_id"))
                            .put("nonce", challenge.getString("nonce"))
                            .put("decision", decision)
                            .put("signature", signed)) { response ->
                            present(response) { resultJson ->
                                setStatus("审批结果：" + resultJson.optString("state") +
                                    "；云平台最终状态请在 ChatGPT 查询")
                                current = null
                                showRequest(null)
                            }
                        }
                    } catch (e: Exception) {
                        setStatus("生物识别签名失败，不会提交开关机")
                    }
                }
                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    super.onAuthenticationError(errorCode, errString)
                    setStatus("未完成生物识别；申请尚未批准")
                }
            }
        )
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("吉皮提：$verb$title")
            .setSubtitle(if (action == "start") "可能开始计费" else "确认所有工作已保存")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
            .setNegativeButtonText("取消")
            .build()
        prompt.authenticate(info, BiometricPrompt.CryptoObject(signature))
    }
}
