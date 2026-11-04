package cn.borealos.jipite

import android.content.Context
import com.xiaomi.mipush.sdk.MiPushClient

/** Domestic Xiaomi push. No Google Mobile Services required. */
object PushBootstrap {
    fun initialize(context: Context, onToken: (String) -> Unit) {
        XiaomiPush.initialize(context)
        val regId = MiPushClient.getRegId(context.applicationContext).orEmpty()
        if (regId.length in 8..256 &&
            regId.matches(Regex("[A-Za-z0-9_+=/-]+"))) {
            onToken("xm:" + regId)
        }
    }
}
