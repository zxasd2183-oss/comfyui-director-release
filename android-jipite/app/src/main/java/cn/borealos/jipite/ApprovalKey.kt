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
 * Hardware-backed, per-use BIOMETRIC_STRONG P-256 key. Existing alias is
 * preserved across upgrades. No software or PIN-only fallback is permitted.
 *
 * Diagnostic output contains only nonsecret KeyInfo authorization flags.
 */
object ApprovalKey {
    private const val ALIAS = "jipite-v06-approval"

    class KeySafetyException(val code: String, cause: Throwable? = null) :
        IllegalStateException(code, cause)

    private fun store(): KeyStore =
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun entry(): KeyStore.PrivateKeyEntry? =
        store().getEntry(ALIAS, null) as? KeyStore.PrivateKeyEntry

    private fun keyInfo(actual: KeyStore.PrivateKeyEntry): KeyInfo =
        try {
            KeyFactory.getInstance(actual.privateKey.algorithm, "AndroidKeyStore")
                .getKeySpec(actual.privateKey, KeyInfo::class.java)
        } catch (e: Exception) {
            throw KeySafetyException("KEYINFO_UNAVAILABLE_" + safeError(e), e)
        }

    private fun levelLabel(level: Int): String = when (level) {
        KeyProperties.SECURITY_LEVEL_SOFTWARE -> "SOFTWARE"
        KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT -> "TEE"
        KeyProperties.SECURITY_LEVEL_STRONGBOX -> "STRONGBOX"
        KeyProperties.SECURITY_LEVEL_UNKNOWN_SECURE -> "UNKNOWN_SECURE"
        KeyProperties.SECURITY_LEVEL_UNKNOWN -> "UNKNOWN"
        else -> "OTHER"
    }

    private data class Audit(
        val level: String,
        val hardwareBacked: Boolean,
        val authenticationRequired: Boolean,
        val everyUse: Boolean,
        val hardwareEnforcedAuth: Boolean,
        val biometricEnrollmentInvalidates: Boolean
    ) {
        fun failureCode(): String? = when {
            !hardwareBacked -> "KEY_NOT_HARDWARE_BACKED"
            !authenticationRequired -> "AUTH_NOT_REQUIRED"
            !everyUse -> "AUTH_NOT_PER_USE"
            !hardwareEnforcedAuth -> "AUTH_NOT_HARDWARE_ENFORCED"
            else -> null
        }

        fun summary(): String = buildString {
            append("安全等级：").append(level)
            append("\n硬件密钥：").append(if (hardwareBacked) "是" else "否")
            append("\n要求身份认证：").append(if (authenticationRequired) "是" else "否")
            append("\n每次操作重新认证：").append(if (everyUse) "是" else "否")
            append("\n认证由安全硬件强制：").append(if (hardwareEnforcedAuth) "是" else "否")
            append("\n新增指纹后密钥失效：")
                .append(if (biometricEnrollmentInvalidates) "是" else "否")
        }
    }

    private fun audit(actual: KeyStore.PrivateKeyEntry): Audit {
        val info = keyInfo(actual)
        val level = if (Build.VERSION.SDK_INT >= 31) {
            levelLabel(info.securityLevel)
        } else {
            @Suppress("DEPRECATION")
            if (info.isInsideSecureHardware) "TEE_OR_SECURE_ELEMENT" else "SOFTWARE"
        }
        val backed = if (Build.VERSION.SDK_INT >= 31) {
            info.securityLevel in setOf(
                KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT,
                KeyProperties.SECURITY_LEVEL_STRONGBOX,
                KeyProperties.SECURITY_LEVEL_UNKNOWN_SECURE
            )
        } else {
            @Suppress("DEPRECATION")
            info.isInsideSecureHardware
        }
        return Audit(
            level = level,
            hardwareBacked = backed,
            authenticationRequired = info.isUserAuthenticationRequired,
            everyUse = info.userAuthenticationValidityDurationSeconds == -1,
            hardwareEnforcedAuth = info.isUserAuthenticationRequirementEnforcedBySecureHardware,
            biometricEnrollmentInvalidates = info.isInvalidatedByBiometricEnrollment
        )
    }

    private fun inspectSecureKey(actual: KeyStore.PrivateKeyEntry): String {
        val outcome = audit(actual)
        val failure = outcome.failureCode()
        if (failure != null) throw KeySafetyException(failure)
        return if (outcome.level == "STRONGBOX") "StrongBox 硬件安全"
               else "TEE / 硬件安全"
    }

    /**
     * Only a stable nonsecret error identifier reaches the UI, never an OEM
     * exception message that could accidentally contain sensitive details.
     */
    fun safeError(exception: Throwable): String {
        if (exception is KeySafetyException) return exception.code
        return when (exception) {
            is android.security.keystore.KeyPermanentlyInvalidatedException ->
                "KEY_INVALIDATED_BY_BIOMETRIC_CHANGE"
            is java.security.InvalidAlgorithmParameterException ->
                "KEYGEN_PARAMETERS_UNSUPPORTED"
            is java.security.ProviderException -> "KEYSTORE_PROVIDER_ERROR"
            is java.security.UnrecoverableKeyException -> "KEY_UNRECOVERABLE"
            is java.security.spec.InvalidKeySpecException -> "KEY_SPEC_UNAVAILABLE"
            is java.security.KeyStoreException -> "KEYSTORE_UNAVAILABLE"
            is java.security.NoSuchAlgorithmException -> "KEY_ALGORITHM_UNAVAILABLE"
            is java.security.NoSuchProviderException -> "KEYSTORE_PROVIDER_UNAVAILABLE"
            is java.security.InvalidKeyException -> "KEY_NOT_AUTHORIZED"
            else -> "KEYSTORE_OPERATION_FAILED"
        }
    }

    /** Read-only diagnostic: does NOT generate, destroy or rotate keys. */
    fun existingKeyReport(): String {
        val actual = try {
            entry()
        } catch (e: Exception) {
            return "读取密钥失败［${safeError(e)}］；禁止绑定"
        }
        if (actual == null) return "尚未创建（首次绑定时才生成）"
        return try {
            val report = audit(actual)
            val issue = report.failureCode()
            (if (issue == null) "密钥本机检查通过"
             else "密钥本机检查未通过［$issue］，禁止配对") +
                "\n" + report.summary()
        } catch (e: Exception) {
            "密钥检查异常［${safeError(e)}］；禁止绑定和批准"
        }
    }

    fun publicKeyBase64(): String {
        var actual = entry()
        if (actual == null) {
            val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(java.security.spec.ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
                .setInvalidatedByBiometricEnrollment(true)
                .build()
            try {
                val generator = KeyPairGenerator.getInstance(
                    KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore"
                )
                generator.initialize(spec)
                generator.generateKeyPair()
                actual = entry()
            } catch (e: Exception) {
                throw KeySafetyException("KEYGEN_FAILED_" + safeError(e), e)
            }
        }
        val keyEntry = actual ?: throw KeySafetyException("KEY_ENTRY_MISSING")
        inspectSecureKey(keyEntry)
        return Base64.encodeToString(keyEntry.certificate.publicKey.encoded, Base64.NO_WRAP)
    }

    fun signatureForBiometric(): Signature {
        val actual = entry() ?: throw KeySafetyException("KEY_ENTRY_MISSING")
        inspectSecureKey(actual)
        return try {
            Signature.getInstance("SHA256withECDSA").apply {
                initSign(actual.privateKey as PrivateKey)
            }
        } catch (e: Exception) {
            throw KeySafetyException("SIGN_INIT_FAILED_" + safeError(e), e)
        }
    }
}
