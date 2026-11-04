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

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }
        fun line(text: String, size: Float = 16f): TextView {
            val view = TextView(this).apply {
                this.text = text
                textSize = size
                setPadding(0, 10, 0, 10)
            }
            root.addView(view)
            return view
        }
        fun button(text: String, callback: () -> Unit): Button {
            val btn = Button(this).apply {
                this.text = text
                setOnClickListener { callback() }
            }
            root.addView(btn)
            return btn
        }

        line("吉皮提 · GPU 审批器", 25f)
        line("Microsoft 个人账号 + 本机强生物识别\n绝不从通知直接执行开关机", 14f)
        if (isOfflinePreview) {
            line("【离线演示 / MuMu 测试】所有申请与决策均为本地模拟，不会控制 GPU", 17f)
        } else {
            line("【V0.8 联机准备版】仅已完成微软注册、设备绑定和生物识别时才能批准真实申请", 15f)
        }
        status = line("初始化中……", 15f)
        microsoftState = line(
            if (isOfflinePreview) "微软账号：离线演示版不提供真实登录"
            else "微软账号：正在读取登录状态……", 17f
        )
        button("查看 V0.8 接入准备清单") { readiness.text = readinessReport() }
        readiness = line("点击上方按钮检查本地配置（不访问网络）", 14f)
        if (!isOfflinePreview) {
            button("检测 VPS HTTPS 审批接口（不需要登录）") {
                readiness.text = "正在检查 HTTPS 接口是否要求 Microsoft 身份认证……"
                MobileApi.probe { result ->
                    runOnUiThread {
                        readiness.text = result.fold(
                            onSuccess = { it },
                            onFailure = { "HTTPS 预检失败：网络不可达或接口配置不正确。不会执行 GPU 操作。" }
                        )
                    }
                }
            }
        }
        val loginButton = button("使用 Microsoft 账号登录 / 重新验证") { signIn() }
        line("首次绑定：请输入 VPS 终端生成的一次性配对密钥", 14f)
        pairing = EditText(this).apply {
            hint = "仅首次配对使用，不要发给 ChatGPT"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            isSingleLine = true
        }
        root.addView(pairing)
        val enrollButton = button("绑定此手机（仅首次）") { enrollPhone() }
        val refreshButton = button("刷新待审批申请") { refresh() }
        if (isOfflinePreview) {
            loginButton.isEnabled = false
            enrollButton.isEnabled = false
            refreshButton.isEnabled = false
            pairing.isEnabled = false
            line("模拟器本地测试（无需账号、网络或真实配对码）", 16f)
            button("模拟开机申请 · 不会真实启动") { showOfflineDemo("start") }
            button("模拟关机申请 · 不会真实关闭") { showOfflineDemo("stop") }
            button("清除模拟申请") {
                current = null
                showRequest(null)
                setStatus("已清除本地模拟申请")
            }
        }
        detail = line("暂无待审批申请", 18f)
        denyButton = button(
            if (isOfflinePreview) "模拟拒绝（不发送）" else "拒绝本次操作（需要生物识别）"
        ) { requestDecision("deny") }
        approveButton = button(
            if (isOfflinePreview) "模拟批准（不执行）" else "指纹 / 面容批准本次操作"
        ) { requestDecision("approve") }
        showRequest(null)

        val scroll = ScrollView(this)
        scroll.addView(root)
        setContentView(scroll)
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
