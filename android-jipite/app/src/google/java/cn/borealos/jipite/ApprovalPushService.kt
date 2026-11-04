package cn.borealos.jipite

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/** Push is merely a hint to open the app. NO approval from a notification action. */
class ApprovalPushService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        getSharedPreferences("jipite-device", MODE_PRIVATE).edit()
            .putString("fcm_token", token).apply()
    }

    override fun onMessageReceived(message: RemoteMessage) {
        if (message.data["kind"] != "gpu-approval") return
        val id = message.data["request_id"] ?: return
        val action = message.data["action"] ?: return
        if (id.length !in 20..80 || action !in listOf("start", "stop")) return
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        val channel = "gpu-approvals"
        manager.createNotificationChannel(
            NotificationChannel(channel, "GPU 开关机审批", NotificationManager.IMPORTANCE_HIGH)
        )
        val intent = Intent(this, MainActivity::class.java)
            .putExtra("request_id", id)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pending = PendingIntent.getActivity(
            this, id.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val title = if (action == "start") "RTX 5090 开机申请" else "RTX 5090 关机申请"
        val notification = NotificationCompat.Builder(this, channel)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentTitle("吉皮提 · $title")
            .setContentText("点击查看申请并使用指纹或面容确认")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        if (Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED) {
            manager.notify(id.hashCode(), notification)
        }
    }
}
