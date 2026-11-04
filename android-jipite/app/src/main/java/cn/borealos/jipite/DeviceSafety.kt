package cn.borealos.jipite

import android.app.KeyguardManager
import android.content.Context
import android.os.Build
import androidx.biometric.BiometricManager

/**
 * Fail-closed local prerequisites for enrolling a phone as the sole GPU approver.
 *
 * Emulator checks are diagnostic heuristics, not remote attestation. Real
 * authorization remains bound to the server-side Microsoft subject, one-time
 * pairing code, and a per-operation hardware-protected Keystore signature.
 */
object DeviceSafety {
    fun likelyEmulator(): Boolean {
        val hardware = Build.HARDWARE.orEmpty().lowercase()
        val fingerprint = Build.FINGERPRINT.orEmpty().lowercase()
        val product = Build.PRODUCT.orEmpty().lowercase()
        val model = Build.MODEL.orEmpty().lowercase()
        val manufacturer = Build.MANUFACTURER.orEmpty().lowercase()
        return hardware.contains("ranchu") ||
            hardware.contains("goldfish") ||
            hardware.contains("vbox") ||
            hardware.contains("nox") ||
            hardware.contains("mumu") ||
            fingerprint.startsWith("generic") ||
            fingerprint.contains("vbox") ||
            model.contains("emulator") ||
            model.contains("mumu") ||
            model.contains("android sdk") ||
            product.startsWith("sdk") ||
            product.contains("emulator") ||
            manufacturer.contains("genymotion")
    }

    fun prerequisiteProblem(context: Context): String? {
        if (BuildConfig.DEBUG) return "离线预览版不允许真实手机配对"
        if (likelyEmulator()) return "检测到模拟器特征；MuMu 仅用于登录与界面测试，请使用小米真机"
        val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        if (keyguard?.isDeviceSecure != true) return "请先在系统设置中启用安全锁屏"
        val biometrics = BiometricManager.from(context).canAuthenticate(
            BiometricManager.Authenticators.BIOMETRIC_STRONG
        )
        if (biometrics != BiometricManager.BIOMETRIC_SUCCESS) {
            return when (biometrics) {
                BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED ->
                    "请在小米手机设置中录入指纹或安全级别足够高的人脸"
                BiometricManager.BIOMETRIC_ERROR_NO_HARDWARE ->
                    "未检测到可用的强生物识别硬件"
                BiometricManager.BIOMETRIC_ERROR_HW_UNAVAILABLE ->
                    "强生物识别暂时不可用，请稍后再试"
                else -> "此设备暂时不能使用 BIOMETRIC_STRONG 签名审批"
            }
        }
        return null
    }

    fun report(context: Context): String {
        val issue = prerequisiteProblem(context)
        val device = if (likelyEmulator()) "疑似模拟器（禁止真实配对）"
                     else "未发现常见模拟器特征（不等于硬件远程证明）"
        val key = ApprovalKey.existingKeyReport()
        return buildString {
            append("设备环境：").append(device)
            append("\n本机检查：").append(issue ?: "安全锁屏及强生物识别已就绪")
            append("\n审批密钥：").append(key)
            append("\n\n真实配对必须在受信任的小米真机上操作。")
            append("\n新建密钥后还会检查安全硬件及逐次生物识别要求。")
            append("\n仅显示本机状态，不联系 VPS、微软或 GPU。")
        }
    }
}
