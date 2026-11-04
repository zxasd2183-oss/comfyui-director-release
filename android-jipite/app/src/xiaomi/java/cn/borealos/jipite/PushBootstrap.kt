package cn.borealos.jipite

import android.content.Context
import android.content.Intent
import com.xiaomi.mipush.sdk.MiPushClient
import com.xiaomi.mipush.sdk.MiPushMessage
import com.xiaomi.mipush.sdk.PushMessageHelper
import org.json.JSONObject

/** Xiaomi mainland build: never initializes Google Play Services or Firebase. */
object PushBootstrap {
    fun initialize(context: Context, onToken: (String) -> Unit) {
        val app = context.applicationContext
        val id = app.resources.getIdentifier("mipush_app_id", "string", app.packageName)
        val key = app.resources.getIdentifier("mipush_app_key", "string", app.packageName)
        if (id == 0 || key == 0) return
        val appId = app.getString(id).trim()
        val appKey = app.getString(key).trim()
        if (appId.isEmpty() || appKey.isEmpty() ||
            appId.startsWith("REPLACE") || appKey.startsWith("REPLACE")) return

        MiPushClient.registerPush(app, appId, appKey)
        val regId = MiPushClient.getRegId(app).orEmpty()
        if (validRegId(regId)) onToken("xm:$regId")
    }

    fun requestIdFromIntent(intent: Intent?): String? {
        if (intent == null) return null
        val regularId = intent.getStringExtra("request_id")
        if (validRequestId(regularId)) return regularId
        // Xiaomi's official notify_effect=1 opens Launcher Activity and
        // puts MiPushMessage in PushMessageHelper.KEY_MESSAGE. The receiver's
        // onNotificationMessageClicked is NOT invoked in this case.
        @Suppress("DEPRECATION")
        val message = intent.getSerializableExtra(PushMessageHelper.KEY_MESSAGE) as? MiPushMessage
            ?: return null
        val payload = runCatching { JSONObject(message.content) }.getOrNull() ?: return null
        if (payload.optString("kind") != "gpu-approval") return null
        return payload.optString("request_id").takeIf { validRequestId(it) }
    }

    fun validRegId(s: String?): Boolean =
        s != null && s.length in 8..256 && s.matches(Regex("[A-Za-z0-9_+=/-]+"))

    private fun validRequestId(s: String?): Boolean =
        s != null && s.length in 20..80 && s.matches(Regex("[A-Za-z0-9_-]+"))
}
