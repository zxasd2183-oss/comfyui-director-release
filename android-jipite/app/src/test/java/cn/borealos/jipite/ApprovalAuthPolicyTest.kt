package cn.borealos.jipite

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApprovalAuthPolicyTest {
    // Android Keystore AUTH_BIOMETRIC_STRONG and AUTH_DEVICE_CREDENTIAL are
    // distinct bitmask values; use representative test constants to keep
    // these tests independent of Android instrumentation or a real Keystore.
    private val strong = 0x000f
    private val credential = 0x8000

    @Test fun legacyPerUseWithBiometricOnlyPasses() {
        assertTrue(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(-1, strong, strong))
    }

    @Test fun zeroTimeoutWithBiometricOnlyPasses() {
        assertTrue(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(0, strong, strong))
    }

    @Test fun anyPositiveTimeoutFailsEvenIfBiometricOnly() {
        for (timeout in listOf(1, 5, 15, 300, Int.MAX_VALUE)) {
            assertFalse(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(timeout, strong, strong))
        }
    }

    @Test fun credentialOrMixedAuthMustFailEvenWithPerUseTimeout() {
        for (timeout in listOf(-1, 0)) {
            assertFalse(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(timeout, credential, strong))
            assertFalse(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(timeout, strong or credential, strong))
            assertFalse(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(timeout, 0, strong))
        }
    }

    @Test fun unexpectedNegativeTimeoutFailsClosed() {
        assertFalse(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(-2, strong, strong))
        assertFalse(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(Int.MIN_VALUE, strong, strong))
    }

    @Test fun missingStrongBiometricConstantFailsClosed() {
        assertFalse(ApprovalAuthPolicy.requiresStrongBiometricEveryUse(0, 0, 0))
    }
}
