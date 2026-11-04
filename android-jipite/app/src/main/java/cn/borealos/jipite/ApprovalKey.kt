package cn.borealos.jipite

import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyInfo
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature

/**
 * Owner-controlled P-256 signing key: nonexportable, hardware-backed and
 * gated by BIOMETRIC_STRONG for EVERY signature. No credential/PIN fallback.
 */
object ApprovalKey {
    // Retain the original alias to preserve already bound devices across APK updates.
    private const val ALIAS = "jipite-v06-approval"
    private fun store(): KeyStore =
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun entry(): KeyStore.PrivateKeyEntry? =
        store().getEntry(ALIAS, null) as? KeyStore.PrivateKeyEntry

    private fun inspectSecureKey(keyEntry: KeyStore.PrivateKeyEntry): String {
        val privateKey = keyEntry.privateKey
        val info = KeyFactory.getInstance(privateKey.algorithm, "AndroidKeyStore")
            .getKeySpec(privateKey, KeyInfo::class.java)
        val level = if (Build.VERSION.SDK_INT >= 31) info.securityLevel else -10
        val backed = if (Build.VERSION.SDK_INT >= 31) {
            level == KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT ||
                level == KeyProperties.SECURITY_LEVEL_STRONGBOX ||
                level == KeyProperties.SECURITY_LEVEL_UNKNOWN_SECURE
        } else {
            @Suppress("DEPRECATION")
            info.isInsideSecureHardware
        }
        require(backed) { "审批私钥未受可信执行环境保护" }
        require(info.isUserAuthenticationRequired) { "审批私钥未要求身份认证" }
        require(info.userAuthenticationValidityDurationSeconds == -1) {
            "审批私钥未设置每次操作重新验证"
        }
        require(info.isUserAuthenticationRequirementEnforcedBySecureHardware) {
            "设备无法确认硬件强制生物识别"
        }
        return if (level == KeyProperties.SECURITY_LEVEL_STRONGBOX) "StrongBox 硬件安全"
               else "TEE 硬件安全"
    }

    /** Read-only check: NEVER create a key merely to display readiness. */
    fun existingKeyReport(): String = try {
        val keyEntry = entry()
        if (keyEntry == null) "尚未创建（首次绑定时生成）"
        else inspectSecureKey(keyEntry) + "，每次签名须强生物识别"
    } catch (_: Exception) {
        "当前审批密钥不可用或安全等级不符合要求；禁止绑定和批准"
    }

    fun publicKeyBase64(): String {
        var keyEntry = entry()
        if (keyEntry == null) {
            val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(java.security.spec.ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
                .setInvalidatedByBiometricEnrollment(true)
                .build()
            val generator = KeyPairGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore"
            )
            generator.initialize(spec)
            generator.generateKeyPair()
            keyEntry = entry()
        }
        val actual = keyEntry ?: error("无法获得 Android Keystore 审批密钥")
        inspectSecureKey(actual)
        return Base64.encodeToString(actual.certificate.publicKey.encoded, Base64.NO_WRAP)
    }

    fun signatureForBiometric(): Signature {
        val actual = entry() ?: error("设备尚未创建硬件审批密钥")
        inspectSecureKey(actual)
        return Signature.getInstance("SHA256withECDSA").apply {
            initSign(actual.privateKey as PrivateKey)
        }
    }
}
