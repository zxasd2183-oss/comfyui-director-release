package cn.borealos.jipite

import android.content.Context
import android.content.Intent
import com.google.firebase.messaging.FirebaseMessaging

/** Google builds only. Firebase does not run or initialize on Xiaomi builds. */
object PushBootstrap {
    fun requestIdFromIntent(intent: Intent?): String? {
        val id = intent?.getStringExtra("request_id")
        return id?.takeIf { it.length in 20..80 && it.matches(Regex("[A-Za-z0-9_-]+")) }
    }

    fun initialize(context: Context, onToken: (String) -> Unit) {
        FirebaseMessaging.getInstance().token
            .addOnSuccessListener { token ->
                if (token.isNotBlank()) onToken(token)
            }
    }
}
