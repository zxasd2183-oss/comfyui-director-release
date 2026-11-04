package cn.borealos.jipite

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature

/** A P-256 signing key locked by BIOMETRIC_STRONG for EVERY operation.
 * The private key never leaves Android Keystore.
 */
object ApprovalKey {
    private const val ALIAS = "jipite-v06-approval"
    private fun store(): KeyStore =
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    fun publicKeyBase64(): String {
        var entry = store().getEntry(ALIAS, null) as? KeyStore.PrivateKeyEntry
        if (entry == null) {
            val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(java.security.spec.ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
                .setInvalidatedByBiometricEnrollment(true)
                .build()
            val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
            gen.initialize(spec)
            gen.generateKeyPair()
            entry = store().getEntry(ALIAS, null) as KeyStore.PrivateKeyEntry
        }
        return Base64.encodeToString(entry.certificate.publicKey.encoded, Base64.NO_WRAP)
    }

    fun signatureForBiometric(): Signature {
        val entry = store().getEntry(ALIAS, null) as? KeyStore.PrivateKeyEntry
            ?: error("设备尚未绑定，请先生成审批密钥")
        return Signature.getInstance("SHA256withECDSA").apply {
            initSign(entry.privateKey as PrivateKey)
        }
    }
}
