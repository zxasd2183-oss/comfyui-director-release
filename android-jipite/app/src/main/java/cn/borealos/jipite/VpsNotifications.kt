package cn.borealos.jipite

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobScheduler
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Base64
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Self-hosted polling from the existing Microsoft-authenticated VPS /pending API.
 * No Xiaomi developer account, FCM, Mi Push, third-party relay, or GPU commands.
 *
 * Notifications contain no bearer token, approval capability, device ID, or
 * pairing code. Every GPU approval remains deliberate + biometric-only.
 */
object VpsNotifications {
    private const val PREFS = "jipite-device"
    private const val ENABLED = "vps_notifications_enabled"
    private const val LAST = "vps_notification_digest"
    private const val JOB_ID = 0x4a503103
    private const val CHANNEL = "jipite_owner_pending"
    private const val ID = 17031

    fun enabled(context: Context): Boolean =
        !BuildConfig.DEBUG &&
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(ENABLED, false)

    fun setEnabled(context: Context, enabled: Boolean): Boolean {
        val contextApp = context.applicationContext
        if (BuildConfig.DEBUG) return false
        contextApp.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putBoolean(ENABLED, enabled).apply()
        return configureJob(contextApp)
    }

    fun configureJob(context: Context): Boolean {
        val manager = context.applicationContext
            .getSystemService(Context.JOB_SCHEDULER_SERVICE) as JobScheduler
        if (!enabled(context)) {
            manager.cancel(JOB_ID)
            return false
        }
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getString("device_id", null).isNullOrBlank()) {
            manager.cancel(JOB_ID)
            return false
        }
        // Re-entering the Activity must not reset the next periodic deadline.
        if (manager.getPendingJob(JOB_ID) != null) return true
        val info = JobInfo.Builder(
            JOB_ID, ComponentName(context.applicationContext, VpsPollJobService::class.java)
        )
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setPeriodic(JobInfo.getMinPeriodMillis())
            .build()
        return manager.schedule(info) == JobScheduler.RESULT_SUCCESS
    }

    /** Return a safe notification candidate only from a genuine pending response. */
    fun onPendingResponse(context: Context, response: JSONObject) {
        if (!enabled(context) || !response.optBoolean("ok")) return
        val requests = response.optJSONArray("requests") ?: return
        val now = System.currentTimeMillis() / 1000
        val identifiers = mutableListOf<String>()
        var chosenId: String? = null
        for (i in 0 until minOf(requests.length(), 5)) {
            val item = requests.optJSONObject(i) ?: continue
            val id = item.optString("request_id")
            val action = item.optString("action")
            val expiry = item.optLong("expires_at", -1)
            if (id.matches(Regex("[A-Za-z0-9_-]{20,80}")) &&
                action in setOf("start", "stop") &&
                expiry > now && expiry <= now + TimeUnit.DAYS.toSeconds(1)) {
                identifiers.add(id)
                if (chosenId == null) chosenId = id
            }
        }
        if (identifiers.isEmpty()) return
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(identifiers.sorted().joinToString("\n").toByteArray(Charsets.UTF_8))
        val key = Base64.encodeToString(digest, Base64.NO_WRAP)
        val preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        synchronized(this) {
            if (preferences.getString(LAST, null) == key) return
            // Do not consume notification state if Android 13+ permission is denied.
            if (Build.VERSION.SDK_INT >= 33 &&
                context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                    PackageManager.PERMISSION_GRANTED) return
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL, "吉皮提 · GPU 待审批提醒",
                    NotificationManager.IMPORTANCE_HIGH
                ).apply { description = "来自自己 VPS 的待审批提醒，仅提醒，不能直接批准" }
            )
            val open = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                putExtra("request_id", chosenId)
            }
            val pendingIntent = PendingIntent.getActivity(
                context, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val notification = Notification.Builder(context, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("吉皮提 · 有待审批 GPU 操作")
                .setContentText("请打开吉皮提查看操作风险，再用指纹确认；通知不会自动审批。")
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_STATUS)
                .build()
            manager.notify(ID, notification)
            preferences.edit().putString(LAST, key).apply()
        }
    }
}
