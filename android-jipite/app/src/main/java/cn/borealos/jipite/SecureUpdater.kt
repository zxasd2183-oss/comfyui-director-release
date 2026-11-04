package cn.borealos.jipite

import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.Executors
import javax.net.ssl.HttpsURLConnection

/**
 * User-initiated updates from the owner's HTTPS VPS mirror.
 *
 * Security gates: pinned host, manifest version/asset/digest, APK SHA-256,
 * installed package ID, monotonically increasing
 * Android version code and matching APK signing certificate.
 *
 * Never downloads from user-supplied URLs, never auto-installs, and never
 * performs any GPU or Microsoft credential action.
 */
object SecureUpdater {
    private const val API = "https://jipite.borealos.cn/app-updates/latest.json"
    private const val DOWNLOAD_PREFIX = "https://jipite.borealos.cn/app-updates/"
    private const val MAX_APK_BYTES = 100_000_000L
    private const val MIN_APK_BYTES = 100_000L
    private val worker = Executors.newSingleThreadExecutor()
    private val versionPattern = Regex("^[0-9]+\\.[0-9]+\\.[0-9]+$")
    private val shaPattern = Regex("^[0-9a-fA-F]{64}$")

    data class Release(
        val version: String,
        val tag: String,
        val downloadUrl: String,
        val sha256: String,
        val size: Long
    )

    fun installedVersion(): String = BuildConfig.VERSION_NAME

    // Must be strictly greater than the local app version.
    private fun asVersion(value: String): List<Int>? {
        if (!Regex("^[0-9]+\\.[0-9]+\\.[0-9]+$").matches(value)) return null
        return value.split('.').map { it.toIntOrNull() ?: return null }
    }

    private fun isNewer(remote: String, local: String): Boolean {
        val r = asVersion(remote) ?: return false
        val l = asVersion(local) ?: return false
        for (i in 0..2) {
            if (r[i] != l[i]) return r[i] > l[i]
        }
        return false
    }

    private fun parseLatest(metadata: JSONObject): Release? {
        // Manifest is served as a static public JSON file from the owner's VPS.
        // Do not allow the server to supply an arbitrary download URL.
        require(metadata.optInt("schema", -1) == 1) { "更新清单格式不受支持" }
        val version = metadata.optString("version")
        require(versionPattern.matches(version)) { "更新版本号格式无效" }
        val filename = "Jipite-v$version-Microsoft-connected.apk"
        require(metadata.optString("asset") == filename) { "更新 APK 文件名不匹配" }
        val hash = metadata.optString("sha256")
        require(shaPattern.matches(hash)) { "更新校验信息无效" }
        val size = metadata.optLong("size", -1L)
        require(size in MIN_APK_BYTES..MAX_APK_BYTES) { "更新文件大小异常" }
        if (!isNewer(version, installedVersion())) return null
        return Release(
            version, "jipite-v$version", DOWNLOAD_PREFIX + filename,
            hash.lowercase(), size
        )
    }

    fun check(context: android.content.Context, callback: (Result<Release?>) -> Unit) {
        if (BuildConfig.DEBUG) {
            callback(Result.failure(IllegalStateException("离线测试版本不访问在线更新源")))
            return
        }
        worker.execute {
            val result = runCatching {
                val conn = openHttps(API)
                try {
                    val stream = conn.inputStream
                    val data = stream.use { input ->
                        val output = java.io.ByteArrayOutputStream()
                        val chunk = ByteArray(8192)
                        while (true) {
                            val length = input.read(chunk)
                            if (length < 0) break
                            if (output.size() + length > 16_384) error("更新信息超出大小限制")
                            output.write(chunk, 0, length)
                        }
                        output.toString("UTF-8")
                    }
                    parseLatest(JSONObject(data))
                } finally {
                    conn.disconnect()
                }
            }
            postToMain(context) { callback(result) }
        }
    }

    fun download(
        context: android.content.Context,
        release: Release,
        progress: (Int) -> Unit,
        complete: (Result<File>) -> Unit
    ) {
        if (BuildConfig.DEBUG) {
            complete(Result.failure(IllegalStateException("离线测试版不能下载正式更新")))
            return
        }
        worker.execute {
            val result = runCatching {
                require(isNewer(release.version, installedVersion())) { "已是最新版本" }
                require(release.tag == "jipite-v${release.version}" &&
                    release.downloadUrl ==
                    "$DOWNLOAD_PREFIX" + "Jipite-v${release.version}-Microsoft-connected.apk") {
                    "更新下载地址不可信"
                }
                val directory = File(context.cacheDir, "jipite-updates")
                require(directory.isDirectory || directory.mkdirs()) { "无法创建更新缓存目录" }
                val part = File(directory, "jipite-update.apk.part")
                val target = File(directory, "jipite-update.apk")
                part.delete()
                try {
                    val conn = openHttps(release.downloadUrl)
                    try {
                        if (conn.contentLengthLong > MAX_APK_BYTES) error("APK 超出大小限制")
                        val sha = MessageDigest.getInstance("SHA-256")
                        var count = 0L
                        var lastPercent = -1
                        conn.inputStream.use { input ->
                            part.outputStream().use { output ->
                                val buffer = ByteArray(32768)
                                while (true) {
                                    val n = input.read(buffer)
                                    if (n == -1) break
                                    count += n
                                    if (count > MAX_APK_BYTES || count > release.size) {
                                        error("APK 大小与发布记录不符")
                                    }
                                    sha.update(buffer, 0, n)
                                    output.write(buffer, 0, n)
                                    val percent = ((count * 100) / release.size).toInt()
                                    if (percent != lastPercent) {
                                        lastPercent = percent
                                        postToMain(context) { progress(percent) }
                                    }
                                }
                            }
                        }
                        require(count == release.size) { "APK 文件下载不完整" }
                        val actual = sha.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
                        require(actual.equals(release.sha256, ignoreCase = true)) {
                            "SHA-256 校验失败，已拒绝安装"
                        }
                        validateApk(context, part, release.version)
                        target.delete()
                        require(part.renameTo(target)) { "无法保存已验证 APK" }
                        target
                    } finally {
                        conn.disconnect()
                    }
                } catch (t: Exception) {
                    part.delete()
                    throw t
                }
            }
            postToMain(context) { complete(result) }
        }
    }

    private fun validateApk(context: android.content.Context, file: File, expectedVersion: String) {
        val manager = context.packageManager
        val archive = manager.getPackageArchiveInfo(
            file.absolutePath, PackageManager.GET_SIGNING_CERTIFICATES
        ) ?: error("无法读取 APK 安装信息")
        require(archive.packageName == context.packageName) { "更新包名不匹配" }
        require(archive.versionName == expectedVersion) { "更新包版本号与发布记录不一致" }
        val installed = manager.getPackageInfo(
            context.packageName, PackageManager.GET_SIGNING_CERTIFICATES
        )
        require(archive.longVersionCode > installed.longVersionCode) { "新版本号必须大于已安装版本" }
        val present = installed.signingInfo?.apkContentsSigners
            ?: error("无法读取现有 APK 签名")
        val incoming = archive.signingInfo?.apkContentsSigners
            ?: error("无法验证下载的 APK 签名")
        require(present.size == 1 && incoming.size == 1 &&
            MessageDigest.isEqual(present[0].toByteArray(), incoming[0].toByteArray())) {
            "APK 签名证书与当前吉皮提不一致，已拒绝安装"
        }
    }

    fun requestInstall(activity: Activity, file: File, expectedVersion: String): Boolean {
        if (BuildConfig.DEBUG) return false
        val expectedPath = File(activity.cacheDir, "jipite-updates/jipite-update.apk")
        require(file.canonicalFile == expectedPath.canonicalFile) {
            "不能安装应用私有更新缓存以外的 APK"
        }
        validateApk(activity, file, expectedVersion) // Verify again just before installer.
        if (!activity.packageManager.canRequestPackageInstalls()) {
            val permission = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${activity.packageName}")
            )
            activity.startActivity(permission)
            return false
        }
        val uri = FileProvider.getUriForFile(
            activity, "${activity.packageName}.updates", file
        )
        activity.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        )
        return true
    }

    private fun openHttps(url: String): HttpsURLConnection {
        val requested = URL(url)
        require(requested.protocol == "https" &&
            requested.host == "jipite.borealos.cn" &&
            requested.port in setOf(-1, 443) &&
            requested.userInfo == null &&
            (url == API || (
                requested.path.matches(
                    Regex("^/app-updates/Jipite-v[0-9]+\\.[0-9]+\\.[0-9]+-Microsoft-connected\\.apk$")
                ) && requested.query == null && requested.ref == null
            ))) {
            "更新请求仅允许访问吉皮提 VPS 上固定的 HTTPS 下载目录"
        }
        val conn = requested.openConnection() as HttpsURLConnection
        conn.instanceFollowRedirects = false
        conn.connectTimeout = 10000
        conn.readTimeout = 25000
        conn.setRequestProperty("User-Agent", "Jipite-Android-Updater")
        conn.setRequestProperty("Accept",
            if (url == API) "application/json" else "application/vnd.android.package-archive")
        val status = conn.responseCode
        if (status != 200) {
            conn.disconnect()
            error("VPS 更新接口返回 HTTP $status")
        }
        return conn
    }

    private fun postToMain(context: android.content.Context, callback: () -> Unit) {
        android.os.Handler(context.mainLooper).post(callback)
    }
}
