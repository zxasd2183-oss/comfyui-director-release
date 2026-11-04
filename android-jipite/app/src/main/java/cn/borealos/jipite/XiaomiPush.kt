package cn.borealos.jipite

import android.content.Context

/** Load native Xiaomi SDK only when the xiaomi flavor has the official
 * MiPush AAR and app's public AppId/AppKey installed. Google builds still compile.
 * NO GPU power call is ever made here.
 */
object XiaomiPush {
    fun initialize(context: Context) {
        val app = context.applicationContext
        val idResource = app.resources.getIdentifier("mipush_app_id", "string", app.packageName)
        val keyResource = app.resources.getIdentifier("mipush_app_key", "string", app.packageName)
        if (idResource == 0 || keyResource == 0) return
        val appId = app.getString(idResource).trim()
        val appKey = app.getString(keyResource).trim()
        if (appId.isBlank() || appKey.isBlank() ||
            appId.startsWith("REPLACE") || appKey.startsWith("REPLACE")) return
        runCatching {
            val client = Class.forName("com.xiaomi.mipush.sdk.MiPushClient")
            val register = client.getMethod("registerPush", Context::class.java,
                String::class.java, String::class.java)
            register.invoke(null, app, appId, appKey)
        }
    }
}
