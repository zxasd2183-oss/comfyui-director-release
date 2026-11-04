package cn.borealos.jipite

import android.content.Context
import android.content.Intent
import com.xiaomi.mipush.sdk.ErrorCode
import com.xiaomi.mipush.sdk.MiPushClient
import com.xiaomi.mipush.sdk.MiPushCommandMessage
import com.xiaomi.mipush.sdk.MiPushMessage
import com.xiaomi.mipush.sdk.PushMessageReceiver
import org.json.JSONObject

/** Xiaomi notification only; approval is NEVER performed in this receiver.
 * The user must review operation details fetched from the authenticated VPS.
 */
class XiaomiPushReceiver : PushMessageReceiver() {
    override fun onReceiveRegisterResult(context: Context, message: MiPushCommandMessage) {
        if (message.command != MiPushClient.COMMAND_REGISTER ||
            message.resultCode != ErrorCode.SUCCESS) return
        val regId = message.commandArguments?.firstOrNull().orEmpty()
        if (regId.length !in 8..256 || !regId.matches(Regex("[A-Za-z0-9_-]+"))) return
        context.getSharedPreferences("jipite-device", Context.MODE_PRIVATE).edit()
            .putString("fcm_token", "xm:" + regId).apply()
        // User's next in-app refresh syncs this regId to the authenticated VPS.
        // Never transmit unverified push callback data directly to the approval API.
    }

    override fun onNotificationMessageClicked(context: Context, message: MiPushMessage) {
        val info = runCatching { JSONObject(message.content) }.getOrNull()
        if (info?.optString("kind") != "gpu-approval") return
        val id = info.optString("request_id")
        if (id.length !in 20..80 || !id.matches(Regex("[A-Za-z0-9_-]+"))) return
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("request_id", id)
        context.startActivity(intent)
    }

    override fun onNotificationMessageArrived(context: Context, message: MiPushMessage) {
        // Deliberately no provider operation or hidden approval.
    }
}
