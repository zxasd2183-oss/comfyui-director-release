package cn.borealos.jipite

import android.Manifest
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
import com.google.firebase.messaging.FirebaseMessaging
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
    private lateinit var status: TextView
    private lateinit var detail: TextView
    private lateinit var pairing: EditText
    private lateinit var approveButton: Button
    private lateinit var denyButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        hintRequestId = intent?.getStringExtra("request_id")
        buildUi()
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 42)
        }
        // Xiaomi devices use Mi Push first; Google/FCM remains a fallback
        // when Google Play Services are actually available.
        XiaomiPush.initialize(this)
        runCatching {
            FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
                val currentToken = prefs.getString("fcm_token", "") ?: ""
                if (!currentToken.startsWith("xm:")) {
                    prefs.edit().putString("fcm_token", token).apply()
                    if (prefs.getString("device_id", null) != null) syncPushToken()
                }
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
                                setStatus("已登录 Microsoft 个人账号，正在检查待审批申请")
                                refresh()
                            } else setStatus("请先使用 Microsoft 个人账号登录")
                        }
                        override fun onAccountChanged(
                            priorAccount: com.microsoft.identity.client.IAccount?,
                            currentAccount: com.microsoft.identity.client.IAccount?
                        ) {
                            if (priorAccount?.id != currentAccount?.id) {
                                cachedIdToken = null
                                current = null
                                showRequest(null)
                            }
                        }
                        override fun onError(exception: MsalException) {
                            setStatus("微软账号初始化失败，请检查 MSAL 配置")
                        }
                    })
                }
                override fun onError(exception: MsalException) {
                    setStatus("MSAL 初始化失败，请核对 client_id 和 Android 签名哈希")
                }
            }
        )
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        hintRequestId = intent.getStringExtra("request_id")
        refresh()
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
        status = line("初始化中……", 15f)
        button("使用 Microsoft 账号登录 / 重新验证") { signIn() }
        line("首次绑定：请输入 VPS 终端生成的一次性配对密钥", 14f)
        pairing = EditText(this).apply {
            hint = "仅首次配对使用，不要发给 ChatGPT"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            isSingleLine = true
        }
        root.addView(pairing)
        button("绑定此手机（仅首次）") { enrollPhone() }
        button("刷新待审批申请") { refresh() }
        detail = line("暂无待审批申请", 18f)
        denyButton = button("拒绝本次操作（需要生物识别）") { requestDecision("deny") }
        approveButton = button("指纹 / 面容批准本次操作") { requestDecision("approve") }
        showRequest(null)

        val scroll = ScrollView(this)
        scroll.addView(root)
        setContentView(scroll)
    }

    private fun setStatus(message: String) {
        runOnUiThread { status.text = message }
    }

    private fun deviceId() = prefs.getString("device_id", null)
    private fun present(result: Result<JSONObject>, then: (JSONObject) -> Unit) {
        runOnUiThread {
            result.onSuccess(then)
            result.onFailure { setStatus("请求失败：" + (it.message ?: "网络或登录异常")) }
        }
    }

    private fun signIn() {
        val app = msal ?: return setStatus("MSAL 尚未初始化")
        val callback = object : AuthenticationCallback {
            override fun onSuccess(result: IAuthenticationResult) {
                cachedIdToken = result.account.idToken
                setStatus("微软账号登录成功")
                refresh()
            }
            override fun onError(exception: MsalException) {
                setStatus("登录失败，请检查个人微软账号和网络")
            }
            override fun onCancel() { setStatus("已取消微软账号登录") }
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
            override fun onError(exception: MsalException) { setStatus("无法获取已登录微软账号") }
        })
    }

    /** Silent MSAL token renewal; if it fails, require explicit Microsoft login. */
    private fun withMicrosoftToken(next: (String) -> Unit) {
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
        val title = if (action == "start") "启动 RTX 5090" else "关闭 RTX 5090"
        val warning = if (action == "start") "审批后可能产生 GPU 租赁费用"
                      else "请先确认任务结束、文件已保存到持久化存储"
        detail.text = title + "\n" + warning + "\n申请：" +
            item.optString("request_id") + "\n有效期：到 " +
            Instant.ofEpochSecond(item.optLong("expires_at")).toString()
        approveButton.isEnabled = true
        denyButton.isEnabled = true
    }

    private fun requestDecision(decision: String) {
        val item = current ?: return setStatus("没有待审批申请")
        val rid = item.optString("request_id")
        val action = item.optString("action")
        val id = deviceId() ?: return setStatus("设备未绑定")
        if (System.currentTimeMillis()/1000 >= item.optLong("expires_at")) {
            return setStatus("申请已过期，请在 ChatGPT 创建新申请")
        }
        // The API creates a NEW one-time nonce and server-bound canonical payload.
        withMicrosoftToken { token ->
            MobileApi.post("challenge", token, JSONObject()
                .put("device_id", id).put("request_id", rid).put("decision", decision)) { response ->
                present(response) { challenge ->
                    if (challenge.optString("request_id") != rid ||
                        challenge.optString("action") != action ||
                        challenge.optString("decision") != decision) {
                        return@present setStatus("服务器操作信息不匹配，拒绝签名")
                    }
                    if (System.currentTimeMillis()/1000 >= challenge.optLong("expires_at")) {
                        return@present setStatus("挑战已过期，重新刷新")
                    }
                    val signature = try { ApprovalKey.signatureForBiometric() }
                                    catch (e: Exception) {
                                        return@present setStatus("审批密钥无法使用，请检查生物识别是否变更")
                                    }
                    askBiometric(signature, challenge, token, id, decision)
                }
            }
        }
    }

    private fun askBiometric(signature: Signature, challenge: JSONObject, token: String,
                             id: String, decision: String) {
        val action = challenge.optString("action")
        val verb = if (decision == "deny") "拒绝" else "批准"
        val title = if (action == "start") "启动 RTX 5090" else "关闭 RTX 5090"
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
