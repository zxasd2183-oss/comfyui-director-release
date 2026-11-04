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
    private lateinit var selftestButton: Button
    private lateinit var selftestStatus: TextView
    private var selftestBusy = false
    private val notificationPollHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val foregroundNotificationPoll = object : Runnable {
        override fun run() {
            if (!isOfflinePreview && VpsNotifications.enabled(this@MainActivity) &&
                deviceId() != null && loginConfirmedInSession && !selftestBusy) {
                val id = deviceId()
                if (id != null) {
                    withMicrosoftToken { token ->
                        MobileApi.post("pending", token, JSONObject().put("device_id", id)) { result ->
                            result.onSuccess {
                                VpsNotifications.onPendingResponse(applicationContext, it)
                            }
                        }
                    }
                }
            }
            notificationPollHandler.postDelayed(this, 45_000L)
        }
    }
    private lateinit var updateCheckButton: Button
    private lateinit var updateDownloadButton: Button
    private lateinit var updateInstallButton: Button
    private lateinit var updateStatus: TextView
    private lateinit var updateProgress: android.widget.ProgressBar
    private lateinit var homePage: LinearLayout
    private lateinit var requestsPage: LinearLayout
    private lateinit var settingsPage: LinearLayout
    private lateinit var pageScroll: ScrollView
    private lateinit var homeTab: TextView
    private lateinit var requestsTab: TextView
    private lateinit var settingsTab: TextView
    private var latestUpdate: SecureUpdater.Release? = null
    private var downloadedUpdate: java.io.File? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        hintRequestId = PushBootstrap.requestIdFromIntent(intent)
        buildUi()
        if (!isOfflinePreview) VpsNotifications.configureJob(this)
        if (!isOfflinePreview && prefs.getBoolean("auto_update_check", false)) {
            // Opt-in: metadata check only; never download or install automatically.
            checkForAppUpdates()
        }
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
                                // MSAL account-change callbacks may run off the main thread.
                                // Never touch an Android TextView or approval button there.
                                runOnUiThread {
                                    cachedIdToken = null
                                    current = null
                                    showRequest(null)
                                    if (currentAccount == null) {
                                        loginConfirmedInSession = false
                                        setMicrosoftState("微软账号：未登录")
                                    }
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

    override fun onResume() {
        super.onResume()
        notificationPollHandler.removeCallbacks(foregroundNotificationPoll)
        if (!isOfflinePreview) {
            VpsNotifications.configureJob(this)
            notificationPollHandler.postDelayed(foregroundNotificationPoll, 8_000L)
        }
    }

    override fun onPause() {
        notificationPollHandler.removeCallbacks(foregroundNotificationPoll)
        super.onPause()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        hintRequestId = PushBootstrap.requestIdFromIntent(intent)
        if (hintRequestId != null) showPage("requests")
        if (!isOfflinePreview) refresh()
    }

    /**
     * Compact three-tab Fluent-inspired original UI. The account and approval
     * state remain in Activity fields, so navigating never recreates MSAL or
     * biometric/Keystore objects and never executes a GPU operation.
     */
    private fun buildUi() {
        val canvas = android.graphics.Color.rgb(247, 249, 252)
        val paper = android.graphics.Color.WHITE
        val ink = android.graphics.Color.rgb(30, 38, 50)
        val secondary = android.graphics.Color.rgb(91, 105, 124)
        val accent = android.graphics.Color.rgb(0, 103, 192)
        val outline = android.graphics.Color.rgb(226, 232, 241)
        val softBlue = android.graphics.Color.rgb(235, 244, 255)

        // Light status/navigation bar icons stay legible on the pale canvas.
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS)
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_TRANSLUCENT_STATUS)
        window.statusBarColor = canvas
        window.navigationBarColor = paper

        fun dp(v: Int) = (v * resources.displayMetrics.density + 0.5f).toInt()
        fun surface(color: Int, border: Int? = null, round: Int = 14) =
            android.graphics.drawable.GradientDrawable().apply {
                setColor(color)
                cornerRadius = dp(round).toFloat()
                if (border != null) setStroke(dp(1), border)
            }
        fun caption(parent: LinearLayout, value: String, size: Float = 13f,
                    color: Int = ink, medium: Boolean = false): TextView {
            val view = TextView(this).apply {
                text = value
                textSize = size
                setTextColor(color)
                typeface = android.graphics.Typeface.create(
                    if (medium) "sans-serif-medium" else "sans-serif",
                    android.graphics.Typeface.NORMAL
                )
                setLineSpacing(dp(2).toFloat(), 1f)
            }
            parent.addView(view)
            return view
        }
        fun space(parent: LinearLayout, height: Int) {
            parent.addView(View(this), LinearLayout.LayoutParams(1, dp(height)))
        }
        fun card(parent: LinearLayout, title: String, hint: String = ""): LinearLayout {
            val c = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                background = surface(paper, outline)
                setPadding(dp(15), dp(15), dp(15), dp(15))
                elevation = dp(1).toFloat()
            }
            parent.addView(c, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(12) })
            caption(c, title, 16f, ink, true)
            if (hint.isNotEmpty()) {
                space(c, 3)
                caption(c, hint, 12f, secondary)
            }
            space(c, 12)
            return c
        }
        fun button(parent: LinearLayout, title: String,
                   filled: Boolean = false, click: () -> Unit): Button {
            val color = if (filled) accent else canvas
            val button = Button(this).apply {
                text = title
                isAllCaps = false
                textSize = 13.5f
                typeface = android.graphics.Typeface.create(
                    "sans-serif-medium", android.graphics.Typeface.NORMAL)
                setTextColor(if (filled) paper else accent)
                background = android.graphics.drawable.RippleDrawable(
                    android.content.res.ColorStateList.valueOf(
                        if (filled) 0x33FFFFFF else 0x220067C0),
                    surface(color, if (filled) null else outline, 9),
                    null
                )
                stateListAnimator = null
                minHeight = 0
                minimumHeight = 0
                setPadding(dp(10), 0, dp(10), 0)
                setOnClickListener { click() }
            }
            parent.addView(button, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(46)
            ).apply { bottomMargin = dp(7) })
            return button
        }
        fun heading(parent: LinearLayout, title: String, hint: String) {
            caption(parent, title, 21f, ink, true)
            space(parent, 3)
            caption(parent, hint, 12f, secondary)
            space(parent, 14)
        }

        val shell = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(canvas)
        }
        // App bar stays visible while navigating; it is not tied to any page.
        val appBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(dp(17), dp(13), dp(17), dp(10))
            setBackgroundColor(paper)
        }
        val monogram = TextView(this).apply {
            text = "J"
            textSize = 20f
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            gravity = android.view.Gravity.CENTER
            setTextColor(paper)
            background = surface(accent, round = 10)
            contentDescription = "吉皮提"
        }
        appBar.addView(monogram, LinearLayout.LayoutParams(dp(39), dp(39)))
        val appTitle = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(11), 0, 0, 0)
        }
        caption(appTitle, "吉皮提", 19f, ink, true)
        caption(appTitle, "安全审批中心 · v" + BuildConfig.VERSION_NAME, 11f, secondary)
        appBar.addView(appTitle, LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        val settingsShortcut = TextView(this).apply {
            text = "设置"
            textSize = 13f
            setTextColor(accent)
            gravity = android.view.Gravity.CENTER
            setPadding(dp(7), dp(6), dp(7), dp(6))
            contentDescription = "打开设置和应用更新"
            setOnClickListener { showPage("settings") }
        }
        appBar.addView(settingsShortcut)
        shell.addView(appBar)

        val line = View(this).apply { setBackgroundColor(outline) }
        shell.addView(line, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(1)
        ))

        val statusBar = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = surface(softBlue, round = 0)
            setPadding(dp(17), dp(9), dp(17), dp(9))
        }
        status = caption(statusBar,
            if (isOfflinePreview) "离线预览：不会连接 Microsoft、VPS 或 GPU"
            else "正在读取 Microsoft 账号及设备状态……", 12.5f, ink)
        status.maxLines = 3
        shell.addView(statusBar)

        pageScroll = ScrollView(this).apply {
            isFillViewport = true
            clipToPadding = false
        }
        val pageHost = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(18), dp(16), dp(24))
        }
        pageScroll.addView(pageHost)
        fun page(): LinearLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
            pageHost.addView(this, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ))
        }
        homePage = page()
        requestsPage = page()
        settingsPage = page()

        // Home: identity and connection status, no excessive vertical controls.
        heading(homePage, "概览", "验证身份、查看连接与设备安全状态")
        val account = card(homePage, "Microsoft 账户")
        microsoftState = caption(account,
            if (isOfflinePreview) "离线演示 · 不提供真实登录"
            else "正在确认登录状态……", 14.5f, ink, true)
        space(account, 13)
        val loginButton = button(account,
            "使用 Microsoft 账号登录 / 重新验证", true) { signIn() }

        val network = card(homePage, "VPS 安全连接", "仅通过 HTTPS 连接受身份保护的审批接口")
        readiness = caption(network,
            if (isOfflinePreview) "离线演示：不访问 VPS"
            else "未检查 · 点击下方按钮执行安全探测", 12.5f, secondary)
        space(network, 11)
        if (!isOfflinePreview) {
            button(network, "检查 HTTPS 连接") {
                readiness.text = "正在检测 HTTPS 与 Microsoft 身份保护……"
                MobileApi.probe { result ->
                    runOnUiThread {
                        readiness.text = result.fold(
                            onSuccess = { "连接正常 · VPS 已启用身份保护" },
                            onFailure = { "连接未通过 · 请检查网络或 VPS 接口" }
                        )
                    }
                }
            }
        }
        button(network, "查看安全诊断与设备配置") {
            showPage("settings")
        }
        val quick = card(homePage, "审批安全", "通知不会直接执行 GPU 开关机")
        caption(quick,
            "真实批准须经过账户身份验证、设备绑定、操作确认和强生物识别签名。",
            12.5f, secondary)
        space(quick, 12)
        button(quick, "查看待审批申请") { showPage("requests") }

        // Dedicated approval page: don't hide approval controls under settings.
        heading(requestsPage, "待审批申请", "请逐项确认 GPU 操作类型、费用及数据风险")
        val pending = card(requestsPage, "当前申请")
        detail = caption(pending, "暂无待审批申请", 15f, ink, true)
        space(pending, 12)
        val refreshButton = button(pending, "刷新待审批申请") { refresh() }
        denyButton = button(pending,
            if (isOfflinePreview) "模拟拒绝（不发送）" else "拒绝本次操作"
        ) { requestDecision("deny") }
        approveButton = button(pending,
            if (isOfflinePreview) "模拟批准（不发送）" else "使用生物识别批准",
            true
        ) { requestDecision("approve") }
        showRequest(null)

        val safetySelftest = card(requestsPage, "安全审批链路自检",
            "验证微软身份、VPS 设备绑定和本机指纹签名；不会产生 GPU 开关机申请")
        selftestStatus = caption(safetySelftest,
            if (isOfflinePreview) "离线预览版不连接 VPS，无法执行真实自检"
            else "尚未测试 · 已绑定后可验证指纹签名与服务器验签", 12.5f, secondary)
        space(safetySelftest, 11)
        selftestButton = button(safetySelftest, "开始指纹安全自检", true) {
            confirmSecureSelftest()
        }
        if (isOfflinePreview) {
            selftestButton.isEnabled = false
            selftestButton.alpha = 0.44f
        }
        caption(safetySelftest,
            "只使用独立的一次性测试随机数；不会审批申请、触发 GPU 或修改设备绑定。",
            12f, secondary)

        if (isOfflinePreview) {
            val demo = card(requestsPage, "离线模拟", "所有操作仅在本地运行，不会改变 GPU 状态")
            button(demo, "模拟开机申请") { showOfflineDemo("start") }
            button(demo, "模拟关机申请") { showOfflineDemo("stop") }
            button(demo, "清除模拟申请") {
                current = null
                showRequest(null)
                setStatus("已清除本地模拟申请")
            }
        }

        val enrollment = card(requestsPage, "首次设备绑定",
            "仅在受信任且具备强生物识别的小米真机操作")
        button(enrollment, "检查本机强生物识别和硬件密钥") {
            AlertDialog.Builder(this)
                .setTitle("真机绑定安全检查")
                .setMessage(DeviceSafety.report(this))
                .setPositiveButton("关闭", null)
                .show()
        }
        pairing = EditText(this).apply {
            hint = "输入 VPS 私人终端的一次性配对密钥"
            textSize = 13f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            isSingleLine = true
            setTextColor(ink)
            setHintTextColor(secondary)
            background = surface(paper, outline, 9)
            setPadding(dp(11), 0, dp(11), 0)
        }
        enrollment.addView(pairing, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(45)
        ))
        space(enrollment, 11)
        val enrollButton = button(enrollment, "绑定此手机（仅首次）") { enrollPhone() }
        if (isOfflinePreview) {
            for (view in arrayOf(loginButton, refreshButton, enrollButton)) {
                view.isEnabled = false
                view.alpha = 0.44f
            }
            pairing.isEnabled = false
        }

        // Settings: version and updates have a first-class, dedicated tab.
        heading(settingsPage, "设置", "管理更新、诊断和应用信息")
        val about = card(settingsPage, "关于吉皮提", "独立的安全审批应用 · Fluent 风格")
        caption(about, "版本 " + BuildConfig.VERSION_NAME, 18f, ink, true)
        space(about, 4)
        caption(about, "构建 " + BuildConfig.VERSION_CODE +
            "  ·  " + (if (isOfflinePreview) "离线预览版" else "Microsoft 联机版"),
            12f, secondary)

        val updates = card(settingsPage, "应用更新",
            "下载验证通过后，由 Android 系统确认安装")
        updateStatus = caption(updates,
            if (isOfflinePreview) "离线预览版不访问在线更新源。"
            else "更新来源：吉皮提 VPS · 可手动检查，或开启启动时自动检查。",
            12.5f, secondary)
        space(updates, 10)
        updateProgress = android.widget.ProgressBar(this, null,
            android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progress = 0
            visibility = View.GONE
            progressTintList = android.content.res.ColorStateList.valueOf(accent)
        }
        updates.addView(updateProgress, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(4)
        ))
        space(updates, 10)
        updateCheckButton = button(updates, "检查更新") { checkForAppUpdates() }
        updateDownloadButton = button(updates, "下载发现的新版本") { downloadAppUpdate() }
        updateInstallButton = button(updates, "安装已验证的更新", true) {
            installAppUpdate()
        }
        updateDownloadButton.isEnabled = false
        updateInstallButton.isEnabled = false
        updateDownloadButton.alpha = 0.44f
        updateInstallButton.alpha = 0.44f
        if (isOfflinePreview) {
            updateCheckButton.isEnabled = false
            updateCheckButton.alpha = 0.44f
        }

        val preference = card(settingsPage, "更新偏好")
        val autoUpdateSwitch = android.widget.Switch(this).apply {
            text = "启动时自动检查更新"
            textSize = 13.5f
            setTextColor(ink)
            isChecked = prefs.getBoolean("auto_update_check", false)
            isEnabled = !isOfflinePreview
            setOnCheckedChangeListener { _, checked ->
                prefs.edit().putBoolean("auto_update_check", checked).apply()
            }
        }
        preference.addView(autoUpdateSwitch)
        space(preference, 7)
        caption(preference, "仅检查新版本，不会自动下载或安装。", 12f, secondary)

        val ownerNotify = card(settingsPage, "自建 VPS 通知（不接小米平台）",
            "不依赖 Mi Push / FCM，不需要第三方开发者账号")
        val noticeSwitch = android.widget.Switch(this).apply {
            text = "启用自己的 HTTPS 待审批提醒"
            textSize = 13.5f
            setTextColor(ink)
            isChecked = VpsNotifications.enabled(this@MainActivity)
            isEnabled = !isOfflinePreview
            setOnCheckedChangeListener { _, checked ->
                val scheduled = VpsNotifications.setEnabled(this@MainActivity, checked)
                setStatus(when {
                    !checked -> "已关闭自建 VPS 提醒，不再进行后台检查"
                    scheduled -> "自建提醒已开启：前台约 45 秒检查，后台由 Android 系统定期调度"
                    else -> "已开启提醒偏好，但尚未绑定设备或系统未接受后台任务"
                })
            }
        }
        ownerNotify.addView(noticeSwitch)
        space(ownerNotify, 9)
        caption(ownerNotify,
            "后台约每 15 分钟检查一次，省电策略可能延迟；需要通知权限。" +
            " 建议在小米系统中允许吉皮提通知、自启动和后台电池使用。" +
            " 提醒不包含审批权限，点击后仍需本人指纹。",
            12f, secondary)

        val safety = card(settingsPage, "安全与诊断", "版本和登录操作不会改变 GPU 电源权限")
        caption(safety, "仅在小米真机上进行正式设备绑定和生物识别审批。",
            12.5f, secondary)
        space(safety, 12)
        button(safety, "查看本机安全检查结果") {
            AlertDialog.Builder(this)
                .setTitle("安全准备状态")
                .setMessage(readinessReport())
                .setPositiveButton("关闭", null)
                .show()
        }

        shell.addView(pageScroll, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f
        ))

        // Persistent bottom navigation: three pages, no page has to scroll past
        // all of the others just to find "Settings" or "Updates".
        val navigation = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(14), dp(5), dp(14), dp(5))
            gravity = android.view.Gravity.CENTER_VERTICAL
            setBackgroundColor(paper)
            elevation = dp(5).toFloat()
        }
        fun tab(label: String, pageName: String): TextView {
            val control = TextView(this).apply {
                text = label
                textSize = 13.5f
                gravity = android.view.Gravity.CENTER
                setTextColor(secondary)
                setOnClickListener { showPage(pageName) }
                contentDescription = "打开" + label
            }
            navigation.addView(control, LinearLayout.LayoutParams(0, dp(48), 1f))
            return control
        }
        homeTab = tab("首页", "home")
        requestsTab = tab("审批", "requests")
        settingsTab = tab("设置", "settings")
        shell.addView(navigation)
        setContentView(shell)
        // API 30 PhoneWindow.getInsetsController() can crash before DecorView
        // exists. Defer styling until after setContentView and attachment.
        window.decorView.post {
            val lightBars =
                android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.decorView.windowInsetsController?.setSystemBarsAppearance(
                lightBars, lightBars
            )
        }
        showPage(if (hintRequestId != null) "requests" else "home")
    }

    private fun showPage(page: String) {
        if (!::homePage.isInitialized || !::requestsPage.isInitialized ||
            !::settingsPage.isInitialized) return
        val selected = if (page in setOf("home", "requests", "settings")) page else "home"
        homePage.visibility = if (selected == "home") View.VISIBLE else View.GONE
        requestsPage.visibility = if (selected == "requests") View.VISIBLE else View.GONE
        settingsPage.visibility = if (selected == "settings") View.VISIBLE else View.GONE
        val dark = android.graphics.Color.rgb(0, 103, 192)
        val muted = android.graphics.Color.rgb(91, 105, 124)
        for ((name, tab) in listOf("home" to homeTab,
            "requests" to requestsTab, "settings" to settingsTab)) {
            tab.setTextColor(if (name == selected) dark else muted)
            tab.typeface = android.graphics.Typeface.create(
                if (name == selected) "sans-serif-medium" else "sans-serif",
                android.graphics.Typeface.NORMAL
            )
            tab.background = android.graphics.drawable.GradientDrawable().apply {
                setColor(if (name == selected)
                    android.graphics.Color.rgb(232, 243, 255)
                    else android.graphics.Color.TRANSPARENT)
                cornerRadius = (11 * resources.displayMetrics.density)
            }
        }
        if (::pageScroll.isInitialized) pageScroll.scrollTo(0, 0)
    }

    private fun checkForAppUpdates() {
        if (BuildConfig.DEBUG) return
        updateCheckButton.isEnabled = false
        updateStatus.text = "正在从吉皮提 VPS 检查新版本……"
        SecureUpdater.check(this) { result ->
            updateCheckButton.isEnabled = true
            result.fold(
                onSuccess = { release ->
                    latestUpdate = release
                    if (release == null) {
                        if (::settingsTab.isInitialized) settingsTab.text = "设置"
                        updateStatus.text = "当前已是最新版本（" + BuildConfig.VERSION_NAME + "）。"
                    } else {
                        if (::settingsTab.isInitialized) settingsTab.text = "设置 · 新版"
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
        val microsoft = if (!microsoftConfigured()) "尚未配置正式微软应用"
                        else if (loginConfirmedInSession) "已成功验证（本次会话）"
                        else "已配置 Client ID，登录状态待确认"
        val binding = if (deviceId() == null) "尚未绑定 VPS（不会进行真实审批）"
                      else "已有设备绑定记录；仍须服务端验签"
        val mode = if (isOfflinePreview) "Debug：禁止真实配对和审批"
                   else "Release：需要 Microsoft 登录 + 真机硬件密钥 + 逐次生物识别"
        return "当前模式：$mode\n微软账户：$microsoft\n设备绑定：$binding\n" +
            DeviceSafety.report(this) +
            "\n\nMi Push 审核未完成前，可通过审批页手动刷新；通知绝不自动批准。" +
            "\nGPU 电源仍由 VPS 安全规则单独控制。"
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
                    setStatus(if (DeviceSafety.likelyEmulator())
                        "Microsoft 登录成功！当前为模拟器环境，不允许绑定 VPS。"
                        else "Microsoft 登录成功！尚未绑定 VPS，请先查看审批页的真机安全诊断。")
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
    private fun withMicrosoftToken(
        next: (String) -> Unit, onFailure: (() -> Unit)? = null
    ) {
        if (isOfflinePreview || !microsoftConfigured()) {
            setStatus("本版本未启用真实登录")
            onFailure?.invoke()
            return
        }
        val app = msal
        if (app == null) {
            setStatus("请先初始化微软登录")
            onFailure?.invoke()
            return
        }
        app.acquireTokenSilentAsync(
            arrayOf("User.Read"),
            "https://login.microsoftonline.com/consumers",
            object : SilentAuthenticationCallback {
                override fun onSuccess(result: IAuthenticationResult) {
                    val token = result.account.idToken
                    if (token.isNullOrBlank()) {
                        setStatus("缺少 ID Token，请重新登录微软账号")
                        onFailure?.invoke()
                    } else {
                        cachedIdToken = token
                        next(token)
                    }
                }
                override fun onError(exception: MsalException) {
                    setStatus("微软登录已过期，请点击登录/重新验证")
                    onFailure?.invoke()
                }
            }
        )
    }

    /**
     * First-time binding is a security-sensitive operation. A separate explicit
     * confirmation and hardware-backed biometric signature must both succeed
     * BEFORE sending the one-time VPS pairing code. No GPU action occurs.
     *
     * This local enrollment proof is not a remote hardware attestation: the VPS
     * still authorizes enrollment using a Microsoft ID token + root-only code.
     */
    private fun enrollPhone() {
        if (isOfflinePreview) return setStatus("离线预览禁止真实配对")
        if (deviceId() != null) return setStatus(
            "此应用已有设备绑定记录；不要重复绑定，若换机请通过 VPS 管理员安全重置"
        )
        val problem = DeviceSafety.prerequisiteProblem(this)
        if (problem != null) return AlertDialog.Builder(this)
            .setTitle("手机尚不满足安全绑定条件")
            .setMessage(problem + "\n\n可在设置 → 安全与诊断查看详细状态。")
            .setPositiveButton("知道了", null)
            .show().let { Unit }

        val code = pairing.text.toString().trim()
        if (code.length < 32) {
            return setStatus("请在小米真机输入 VPS 私人 SSH 终端获取的一次性配对码")
        }
        AlertDialog.Builder(this)
            .setTitle("确认将此真机绑定到 VPS？")
            .setMessage(
                "这将占用 VPS 唯一的审批设备名额。绑定后如换手机，需由 VPS 管理员" +
                "人工安全重置。\n\n只有你主动确认并通过强生物识别后，" +
                "才会发送 Microsoft 身份凭据和一次性配对码。\n" +
                "不会立即开机、关机或提交 GPU 审批。"
            )
            .setNegativeButton("取消", null)
            .setPositiveButton("继续生物识别") { _, _ ->
                beginSecureEnrollment(code)
            }
            .show()
    }

    /**
     * Error-code-only local diagnostic. No pairing secret, Microsoft identity
     * token, private key, public key, device ID, or GPU API is shown or logged.
     */
    private fun showKeystoreProblem(error: Exception) {
        val code = ApprovalKey.safeError(error)
        setStatus("本机硬件密钥检查未通过［$code］；配对码未发送")
        val report = DeviceSafety.report(this)
        AlertDialog.Builder(this)
            .setTitle("未绑定 VPS · 本机安全检查")
            .setMessage(
                "错误代码：$code\n\n" + report +
                "\n\n请勿删除应用数据、重置密钥或关闭安全保护。" +
                "可以复制下面的安全诊断文字，不含配对码、密钥或微软令牌。"
            )
            .setNegativeButton("关闭", null)
            .setPositiveButton("复制诊断") { _, _ ->
                val clipboard = getSystemService(android.content.Context.CLIPBOARD_SERVICE)
                    as android.content.ClipboardManager
                clipboard.setPrimaryClip(
                    android.content.ClipData.newPlainText(
                        "吉皮提本机安全诊断", "错误代码：$code\n" + report
                    )
                )
                setStatus("本机安全诊断已复制（不含账户和配对信息）")
            }
            .show()
    }

    private fun beginSecureEnrollment(code: String) {
        val problem = DeviceSafety.prerequisiteProblem(this)
        if (problem != null) return setStatus(problem)
        val pub = try {
            ApprovalKey.publicKeyBase64() // Fails closed if secure hardware is absent.
        } catch (e: Exception) {
            return showKeystoreProblem(e)
        }
        val signingOp = try {
            ApprovalKey.signatureForBiometric()
        } catch (e: Exception) {
            return showKeystoreProblem(e)
        }
        // Do not leave the root-only code visible in the screen during biometric UI.
        pairing.text.clear()
        val challenge = ByteArray(32).also { java.security.SecureRandom().nextBytes(it) }
        val prompt = BiometricPrompt(
            this, ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    super.onAuthenticationSucceeded(result)
                    try {
                        val authorized = result.cryptoObject?.signature
                            ?: error("Biometric CryptoObject missing")
                        authorized.update("JIPITE-ENROLL-LOCAL\\n".toByteArray(Charsets.US_ASCII))
                        authorized.update(challenge)
                        val proof = authorized.sign()
                        if (proof.isEmpty()) error("Hardware biometric signature missing")
                    } catch (_: Exception) {
                        setStatus("本机强生物识别验证失败，未发送 VPS 配对码")
                        return
                    }
                    if (deviceId() != null) {
                        setStatus("绑定状态已变化，请勿重复提交")
                        return
                    }
                    withMicrosoftToken { token ->
                        MobileApi.post("enroll", token, JSONObject()
                            .put("pairing_code", code)
                            .put("public_key", pub)
                            .put("fcm_token", prefs.getString("fcm_token", "") ?: "")
                        ) { response ->
                            present(response) { json ->
                                prefs.edit().putString("device_id", json.getString("device_id")).apply()
                                VpsNotifications.configureJob(this@MainActivity)
                                setStatus("真机首次绑定成功；以后审批仍需每次指纹 / 强生物识别")
                                refresh()
                            }
                        }
                    }
                }
                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    super.onAuthenticationError(errorCode, errString)
                    setStatus("已取消或未通过强生物识别；配对码未发送")
                }
            }
        )
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("吉皮提 · 首次绑定设备")
            .setSubtitle("仅验证本人持有的硬件审批密钥；不执行 GPU 操作")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
            .setNegativeButtonText("取消")
            .build()
        try {
            prompt.authenticate(info, BiometricPrompt.CryptoObject(signingOp))
        } catch (e: Exception) {
            showKeystoreProblem(e)
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
                    VpsNotifications.onPendingResponse(applicationContext, json)
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

    /**
     * Biometric proof-of-possession for the already enrolled public key.
     * This path must never invoke GPU challenge/decision APIs.
     * Every response and the exact domain-separated bytes are checked before
     * handing a per-use Keystore Signature to BiometricPrompt.
     */
    private fun confirmSecureSelftest() {
        if (selftestBusy || isOfflinePreview) return
        val id = deviceId() ?: return setStatus("尚未绑定 VPS，无法进行指纹验签自检")
        val problem = DeviceSafety.prerequisiteProblem(this)
        if (problem != null) return setStatus("自检条件未满足：" + problem)
        val keyReport = ApprovalKey.existingKeyReport()
        if (!keyReport.startsWith("密钥本机检查通过")) {
            return setStatus("硬件密钥本机检查未通过，禁止自检。请先查看安全诊断。")
        }
        AlertDialog.Builder(this)
            .setTitle("仅验证指纹签名 · 不操作 GPU")
            .setMessage(
                "VPS 将提供一次性随机挑战。你需要使用小米指纹确认，" +
                "VPS 只用已绑定公钥验签，检查后会立即作废挑战。\n\n" +
                "不会创建待审批 GPU 任务，不会执行开关机，也不会更改配对绑定。"
            )
            .setNegativeButton("取消", null)
            .setPositiveButton("开始安全自检") { _, _ -> startSecureSelftest(id) }
            .show()
    }

    private fun finishSecureSelftest(message: String) {
        runOnUiThread {
            selftestBusy = false
            if (::selftestButton.isInitialized) selftestButton.isEnabled = !isOfflinePreview
            if (::selftestStatus.isInitialized) selftestStatus.text = message
            setStatus(message)
        }
    }

    private fun isValidSelftestChallenge(challenge: JSONObject, deviceId: String): Boolean {
        if (challenge.optString("kind") != "biometric_selftest") return false
        if (!deviceId.matches(Regex("[A-Za-z0-9_-]{16,100}"))) return false
        val nonce = challenge.optString("nonce")
        if (!nonce.matches(Regex("[A-Za-z0-9_-]{24,64}"))) return false
        val expiry = challenge.optLong("expires_at", -1)
        val now = System.currentTimeMillis() / 1000
        if (expiry !in (now - 15)..(now + 180)) return false
        val encoded = challenge.optString("payload_b64")
        if (encoded.length !in 50..1024) return false
        val bytes = try { Base64.decode(encoded, Base64.DEFAULT) }
                    catch (_: IllegalArgumentException) { return false }
        val expected = ("JIPITE-SELFTEST-V1\n" + deviceId + "\n" +
            nonce + "\n" + expiry).toByteArray(Charsets.US_ASCII)
        return java.security.MessageDigest.isEqual(bytes, expected)
    }

    private fun startSecureSelftest(id: String) {
        if (selftestBusy || isOfflinePreview) return
        selftestBusy = true
        selftestButton.isEnabled = false
        selftestStatus.text = "正在验证 Microsoft 账号并获取 VPS 一次性挑战……"
        withMicrosoftToken(
            next = { token ->
                MobileApi.post("selftest_challenge", token,
                    JSONObject().put("device_id", id)
                ) { response ->
                    runOnUiThread {
                        response.onSuccess { challenge ->
                            if (!isValidSelftestChallenge(challenge, id)) {
                                finishSecureSelftest("服务端自检挑战格式或有效期不符，已拒绝签名")
                            } else {
                                val signature = try { ApprovalKey.signatureForBiometric() }
                                                catch (e: Exception) {
                                                    finishSecureSelftest(
                                                        "硬件审批密钥不可用：" + ApprovalKey.safeError(e))
                                                    return@onSuccess
                                                }
                                selftestStatus.text = "请使用小米指纹完成逐次签名验证……"
                                askSelftestBiometric(signature, challenge, token, id)
                            }
                        }
                        response.onFailure {
                            finishSecureSelftest(
                                "无法获取 VPS 自检挑战：" +
                                ((it.message ?: "网络或身份验证失败").take(100))
                            )
                        }
                    }
                }
            },
            onFailure = {
                finishSecureSelftest("微软登录未就绪；请返回首页重新验证后再试")
            }
        )
    }

    private fun askSelftestBiometric(
        signature: Signature, challenge: JSONObject, token: String, id: String
    ) {
        val prompt = BiometricPrompt(
            this, ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(
                    result: BiometricPrompt.AuthenticationResult
                ) {
                    super.onAuthenticationSucceeded(result)
                    val signed = try {
                        val authenticatedSignature = result.cryptoObject?.signature
                            ?: error("No per-use biometric crypto object")
                        val payload = Base64.decode(
                            challenge.getString("payload_b64"), Base64.DEFAULT
                        )
                        authenticatedSignature.update(payload)
                        Base64.encodeToString(authenticatedSignature.sign(), Base64.NO_WRAP)
                    } catch (_: Exception) {
                        finishSecureSelftest("硬件指纹签名失败；未向 VPS 提交验证")
                        return
                    }
                    selftestStatus.text = "指纹已通过；正在请 VPS 验证已绑定公钥和防重放……"
                    MobileApi.post("selftest_verify", token, JSONObject()
                        .put("device_id", id)
                        .put("nonce", challenge.getString("nonce"))
                        .put("signature", signed)) { response ->
                        runOnUiThread {
                            response.onSuccess { reply ->
                                val success =
                                    reply.optBoolean("identity_verified") &&
                                    reply.optBoolean("device_bound") &&
                                    reply.optBoolean("signature_verified") &&
                                    reply.optBoolean("one_time_challenge_consumed") &&
                                    reply.has("gpu_operation_performed") &&
                                    !reply.optBoolean("gpu_operation_performed", true)
                                finishSecureSelftest(
                                    if (success)
                                        "安全自检通过 ✓ Microsoft、设备绑定、指纹签名、VPS 验签与防重放均正常；未操作 GPU"
                                    else
                                        "VPS 自检结果不完整，未确认验签通过；未操作 GPU"
                                )
                            }
                            response.onFailure {
                                finishSecureSelftest(
                                    "VPS 未能确认签名：" +
                                    ((it.message ?: "服务器验签失败").take(100)))
                            }
                        }
                    }
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    super.onAuthenticationError(errorCode, errString)
                    finishSecureSelftest("指纹自检已取消或未通过；未操作 GPU")
                }

                override fun onAuthenticationFailed() {
                    super.onAuthenticationFailed()
                    selftestStatus.text = "指纹未通过，请在系统提示中重试或取消"
                }
            }
        )
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("吉皮提 · 安全审批自检")
            .setSubtitle("指纹签名仅供 VPS 一次性验签，不触发 GPU 操作")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
            .setNegativeButtonText("取消")
            .build()
        try {
            prompt.authenticate(info, BiometricPrompt.CryptoObject(signature))
        } catch (_: Exception) {
            finishSecureSelftest("无法启动强生物识别签名；未操作 GPU")
        }
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
        val problem = DeviceSafety.prerequisiteProblem(this)
        if (problem != null) return setStatus("安全条件未满足，禁止真实审批：" + problem)
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
