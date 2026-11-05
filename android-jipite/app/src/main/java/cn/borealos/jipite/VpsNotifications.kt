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
    private const val DIAGNOSTIC_JOB_ID = 0x4a503105
    private const val PERIODIC_STATUS = "vps_poll_periodic_status"
    private const val PERIODIC_TIME = "vps_poll_periodic_ms"
    private const val DIAGNOSTIC_STATUS = "vps_poll_diagnostic_status"
    private const val DIAGNOSTIC_TIME = "vps_poll_diagnostic_ms"
    private const val CHANNEL = "jipite_owner_pending"
    private const val ID = 17031
    private const val TEST_ID = 17032
    private const val DIAGNOSTIC_ID = 17033

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
            manager.cancel(DIAGNOSTIC_JOB_ID)
            return false
        }
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getString("device_id", null).isNullOrBlank()) {
            manager.cancel(JOB_ID)
            manager.cancel(DIAGNOSTIC_JOB_ID)
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



    fun isDiagnosticJob(jobId: Int): Boolean = jobId == DIAGNOSTIC_JOB_ID

    /** Scheduling is not proof of execution: Android/HyperOS can delay it. */
    fun scheduleDiagnostic(context: Context): String {
        if (!enabled(context)) return "请先开启 HTTPS 待审批提醒。"
        if (context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString("device_id", null).isNullOrBlank()) {
            return "此手机没有本地设备绑定记录，不能执行 VPS 查询自检。"
        }
        return try {
            val manager = context.getSystemService(Context.JOB_SCHEDULER_SERVICE)
                as JobScheduler
            if (manager.getPendingJob(DIAGNOSTIC_JOB_ID) != null) {
                "已有一次性后台检测在排队，请返回桌面并等待 Android 调度。"
            } else {
                val info = JobInfo.Builder(
                    DIAGNOSTIC_JOB_ID,
                    ComponentName(context.applicationContext, VpsPollJobService::class.java)
                ).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setMinimumLatency(10_000L).build()
                if (manager.schedule(info) == JobScheduler.RESULT_SUCCESS) {
                    recordDiagnostic(context, "scheduled")
                    "已安排后台查询，请返回桌面并锁屏，然后查看测试通知或本页诊断。"
                } else {
                    recordDiagnostic(context, "schedule_failed")
                    "Android 未接受后台任务，请检查系统限制。"
                }
            }
        } catch (_: Exception) {
            recordDiagnostic(context, "schedule_failed")
            "后台任务调度失败，请检查系统省电设置。"
        }
    }

    private fun saveCode(context: Context, statusKey: String, timeKey: String, code: String) {
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(statusKey, code)
            .putLong(timeKey, System.currentTimeMillis()).apply()
    }

    fun recordPeriodic(context: Context, code: String) =
        saveCode(context, PERIODIC_STATUS, PERIODIC_TIME, code)

    fun recordDiagnostic(context: Context, code: String) =
        saveCode(context, DIAGNOSTIC_STATUS, DIAGNOSTIC_TIME, code)

    private fun label(code: String): String = when (code) {
        "scheduled" -> "已排队，等待 Android 调度"
        "running" -> "Android 后台任务已启动"
        "ok" -> "通过：Microsoft 静默身份认证与 VPS 只读查询成功"
        "busy" -> "周期任务正在查询，请稍后重新测试"
        "no_account" -> "后台未找到 Microsoft 登录账户"
        "no_token", "auth_failed", "account_error", "msal_error" ->
            "Microsoft 后台静默认证未完成，请打开应用重新登录"
        "vps_error" -> "VPS 查询失败：网络、身份或服务器拒绝"
        "unbound" -> "手机尚未绑定 VPS"
        "disabled" -> "自建提醒未开启"
        "timeout" -> "后台查询超时"
        "interrupted" -> "Android 中断后台任务"
        "schedule_failed" -> "Android 不允许后台调度"
        "internal_error" -> "后台任务内部异常"
        else -> "尚未检测"
    }

    fun diagnosticSummary(context: Context): String {
        val pref = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        fun entry(statusKey: String, timeKey: String): String {
            val timestamp = pref.getLong(timeKey, 0L)
            if (timestamp <= 0L) return "尚未检测"
            val date = java.text.DateFormat.getDateTimeInstance(
                java.text.DateFormat.SHORT, java.text.DateFormat.MEDIUM
            ).format(java.util.Date(timestamp))
            return "$date · ${label(pref.getString(statusKey, "") ?: "")}"
        }
        return "一次性后台测试：" + entry(DIAGNOSTIC_STATUS, DIAGNOSTIC_TIME) +
            "\n周期后台检查：" + entry(PERIODIC_STATUS, PERIODIC_TIME) +
            "\n不保存 Microsoft Token、设备 ID 或审批申请内容。"
    }

    /** Clearly marked notification, with no request ID or approval action. */
    fun notifyDiagnosticFinished(context: Context, code: String) {
        if (!enabled(context)) return
        if (Build.VERSION.SDK_INT >= 33 &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED) return
        try {
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager
            if (!manager.areNotificationsEnabled()) return
            ensureChannel(manager)
            if (manager.getNotificationChannel(CHANNEL)?.importance ==
                NotificationManager.IMPORTANCE_NONE) return
            val open = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                putExtra("show_background_diagnostics", true)
            }
            val launch = PendingIntent.getActivity(
                context, 3, open,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val ok = code == "ok"
            manager.notify(DIAGNOSTIC_ID, Notification.Builder(context, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(if (ok) "吉皮提 · 后台 VPS 查询自检通过"
                                  else "吉皮提 · 后台 VPS 查询自检未完成")
                .setContentText(if (ok)
                    "Microsoft 静默认证及 VPS 只读查询成功，未操作 GPU。"
                    else "查看吉皮提设置中的诊断状态；未操作 GPU。")
                .setContentIntent(launch)
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_STATUS)
                .build())
        } catch (_: Exception) {
            // Failure to post a notification must not erase the local test result.
        }
    }

    private fun ensureChannel(manager: NotificationManager) {
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL, "吉皮提 · GPU 待审批提醒",
                NotificationManager.IMPORTANCE_HIGH
            ).apply { description = "来自自己 VPS 的待审批提醒，仅提醒，不能直接批准" }
        )
    }

    /**
     * User-initiated, local-only Android notification transport check.
     *
     * Does not call the VPS, create a pending GPU request, touch approval keys
     * or change the deduplication digest for real pending notifications.
     * A separate notification ID and PendingIntent request code prevent it
     * from replacing or opening an actual approval request.
     */
    fun sendLocalTest(context: Context): String {
        if (!enabled(context)) return "请先开启「启用自己的 HTTPS 待审批提醒」。"
        if (Build.VERSION.SDK_INT >= 33 &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED) {
            return "Android 通知权限未开启。请在系统设置中允许吉皮提发送通知。"
        }
        return try {
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager
            if (!manager.areNotificationsEnabled()) {
                "系统已关闭吉皮提的通知，请在手机系统设置中允许通知。"
            } else {
                ensureChannel(manager)
                if (manager.getNotificationChannel(CHANNEL)?.importance ==
                    NotificationManager.IMPORTANCE_NONE) {
                    "GPU 提醒通知通道已被关闭，请在手机系统通知设置中重新开启。"
                } else {
                    val open = Intent(context, MainActivity::class.java).apply {
                        flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                        // No request_id: a test notification must never select a GPU request.
                    }
                    val launch = PendingIntent.getActivity(
                        context, 1, open,
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                    )
                    val notification = Notification.Builder(context, CHANNEL)
                        .setSmallIcon(android.R.drawable.ic_dialog_info)
                        .setContentTitle("吉皮提 · 本地通知自检")
                        .setContentText("这只是系统通知测试，没有 GPU 操作或审批申请。")
                        .setContentIntent(launch)
                        .setAutoCancel(true)
                        .setCategory(Notification.CATEGORY_STATUS)
                        .build()
                    manager.notify(TEST_ID, notification)
                    "已向 Android 提交本地测试通知，请下拉通知栏查看；" +
                        "它不代表后台轮询或 VPS 网络已经验收。"
                }
            }
        } catch (_: SecurityException) {
            "系统拒绝发送通知，请检查吉皮提的通知权限。"
        } catch (_: Exception) {
            "通知自检未完成，请检查系统通知设置后重试。"
        }
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
            // Never mark an alert as delivered while system/app channel is disabled.
            if (!manager.areNotificationsEnabled()) return
            ensureChannel(manager)
            if (manager.getNotificationChannel(CHANNEL)?.importance ==
                NotificationManager.IMPORTANCE_NONE) return
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
