package cn.borealos.jipite

import android.content.Context
import android.content.Intent

/** During Xiaomi developer review: no push SDK, no Google service.
 * The user explicitly opens the app and taps "刷新待审批申请".
 * This stub never grants approval or touches GPU power.
 */
object PushBootstrap {
    fun initialize(context: Context, onToken: (String) -> Unit) {
        // Intentionally disabled. Manual polling is a user action.
    }

    fun requestIdFromIntent(intent: Intent?): String? {
        val value = intent?.getStringExtra("request_id")
        return value?.takeIf {
            it.length in 20..80 && it.matches(Regex("[A-Za-z0-9_-]+"))
        }
    }
}
