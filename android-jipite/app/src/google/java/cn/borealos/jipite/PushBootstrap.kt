package cn.borealos.jipite

import android.content.Context
import com.google.firebase.messaging.FirebaseMessaging

/** Google builds only. Firebase does not run or initialize on Xiaomi builds. */
object PushBootstrap {
    fun initialize(context: Context, onToken: (String) -> Unit) {
        FirebaseMessaging.getInstance().token
            .addOnSuccessListener { token ->
                if (token.isNotBlank()) onToken(token)
            }
    }
}
