package cn.borealos.jipite

/**
 * Normalize Keystore's legacy (-1) and modern key-generation (0) per-operation
 * timeout conventions. A timeout alone is NEVER enough: the hardware-reported
 * authentication type must be exactly BIOMETRIC_STRONG, without credential/PIN.
 *
 * All unknown/positive timeout values, unset/combined auth types and invalid
 * input fail closed. The Android Keystore must still enforce user auth in
 * hardware; each Signature must be supplied through BiometricPrompt.CryptoObject.
 */
internal object ApprovalAuthPolicy {
    fun isPerOperationTimeout(seconds: Int): Boolean =
        seconds == -1 || seconds == 0

    fun isBiometricOnly(authType: Int, strongBiometric: Int): Boolean =
        authType == strongBiometric && strongBiometric != 0

    fun requiresStrongBiometricEveryUse(
        seconds: Int,
        authType: Int,
        strongBiometric: Int
    ): Boolean = isPerOperationTimeout(seconds) &&
        isBiometricOnly(authType, strongBiometric)
}
