package cn.borealos.jipite

import org.json.JSONObject
import java.net.URL
import java.util.concurrent.Executors
import javax.net.ssl.HttpsURLConnection

/** Calls the owner-controlled HTTPS backend. Never contacts provider power APIs. */
object MobileApi {
    private val executor = Executors.newSingleThreadExecutor()
    private const val BASE = "https://jipite.borealos.cn/api/v1/mobile/"

    fun post(
        op: String, microsoftIdToken: String, json: JSONObject,
        callback: (Result<JSONObject>) -> Unit
    ) {
        if (op !in setOf("enroll", "pending", "challenge", "decision", "push")) {
            callback(Result.failure(IllegalArgumentException("Unsupported API"))); return
        }
        executor.execute {
            val result = runCatching {
                val con = URL(BASE + op).openConnection() as HttpsURLConnection
                try {
                    con.requestMethod = "POST"
                    con.connectTimeout = 10000
                    con.readTimeout = 15000
                    con.setRequestProperty("Content-Type", "application/json")
                    con.setRequestProperty("Authorization", "Bearer " + microsoftIdToken)
                    con.setRequestProperty("Accept", "application/json")
                    con.doOutput = true
                    con.outputStream.use { it.write(json.toString().toByteArray(Charsets.UTF_8)) }
                    val stream = if (con.responseCode in 200..299) con.inputStream
                                 else con.errorStream
                    val reply = stream?.bufferedReader()?.use { it.readText() } ?: "{}"
                    val obj = JSONObject(reply)
                    if (con.responseCode !in 200..299 || !obj.optBoolean("ok")) {
                        error(obj.optString("reason", "请求失败"))
                    }
                    obj
                } finally {
                    con.disconnect()
                }
            }
            callback(result)
        }
    }
}
