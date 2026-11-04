package cn.borealos.jipite

import org.json.JSONObject
import java.net.URL
import java.util.concurrent.Executors
import javax.net.ssl.HttpsURLConnection

/** Calls the owner-controlled HTTPS backend. Never contacts provider power APIs. */
object MobileApi {
    private val executor = Executors.newSingleThreadExecutor()
    private const val BASE = "https://jipite.borealos.cn/api/v1/mobile/"

    /**
     * A side-effect-free HTTPS reachability probe. The backend's pending API
     * must return HTTP 401 + microsoft_login_required for an anonymous POST.
     * Never sends Microsoft tokens, pairing codes, device ids, or signatures.
     */
    fun probe(callback: (Result<String>) -> Unit) {
        executor.execute {
            val result = runCatching {
                val con = URL(BASE + "pending").openConnection() as HttpsURLConnection
                try {
                    con.requestMethod = "POST"
                    con.connectTimeout = 6000
                    con.readTimeout = 8000
                    con.setRequestProperty("Content-Type", "application/json")
                    con.setRequestProperty("Accept", "application/json")
                    con.doOutput = true
                    con.outputStream.use { it.write("{}".toByteArray(Charsets.UTF_8)) }
                    val status = con.responseCode
                    val body = (if (status in 200..299) con.inputStream else con.errorStream)
                        ?.bufferedReader(Charsets.UTF_8)?.use { it.readText().take(4096) } ?: "{}"
                    val reason = runCatching { JSONObject(body).optString("reason") }.getOrDefault("")
                    if (status != 401 || reason != "microsoft_login_required") {
                        error("审批服务未返回预期的身份验证保护响应")
                    }
                    "HTTPS 可达；审批接口已要求 Microsoft 身份认证（尚未验证登录、绑定或 GPU 操作）"
                } finally {
                    con.disconnect()
                }
            }
            callback(result)
        }
    }

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
