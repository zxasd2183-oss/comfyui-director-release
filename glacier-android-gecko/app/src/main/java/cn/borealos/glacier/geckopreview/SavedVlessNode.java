package cn.borealos.glacier.geckopreview;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.security.GeneralSecurityException;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Opt-in, on-device-only saved VLESS configuration. No plaintext node is
 * written to prefs, logs, cloud backup or external files.
 *
 * The Android Keystore key is non-exportable; a random GCM nonce protects
 * each saved config. This is not a password vault or server-side sync.
 */
final class SavedVlessNode {
    private static final String STORE = "glacier_saved_network_v1";
    private static final String KEY_ALIAS = "glacier_vless_node_aes_v1";
    private static final String PREF_IV = "iv";
    private static final String PREF_DATA = "encrypted_node";
    private static final String PREF_AUTO = "auto_connect";
    private static final byte[] AAD =
            "cn.borealos.glacier.geckopreview.saved-vless.v1"
                    .getBytes(StandardCharsets.UTF_8);

    private SavedVlessNode() {}

    private static SharedPreferences preferences(Context ctx) {
        return ctx.getApplicationContext()
                .getSharedPreferences(STORE, Context.MODE_PRIVATE);
    }

    private static KeyStore keystore() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        return store;
    }

    private static SecretKey nodeKey(boolean allowCreate) throws Exception {
        KeyStore store = keystore();
        if (store.containsAlias(KEY_ALIAS)) {
            java.security.Key key = store.getKey(KEY_ALIAS, null);
            if (!(key instanceof SecretKey)) {
                throw new GeneralSecurityException("Saved network key invalid");
            }
            return (SecretKey) key;
        }
        if (!allowCreate) throw new GeneralSecurityException("Saved network key missing");
        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(
                KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .setUserAuthenticationRequired(false)
                .setKeySize(256)
                .build());
        return generator.generateKey();
    }

    static synchronized boolean exists(Context ctx) {
        SharedPreferences p = preferences(ctx);
        return p.contains(PREF_DATA) || p.contains(PREF_IV);
    }

    static synchronized boolean autoConnectEnabled(Context ctx) {
        return exists(ctx) && preferences(ctx).getBoolean(PREF_AUTO, true);
    }

    static synchronized void disableAutoConnect(Context ctx) {
        // Keep the ciphertext, but honour an explicit DIRECT session choice.
        preferences(ctx).edit().putBoolean(PREF_AUTO, false).apply();
    }

    static synchronized void save(Context ctx, String rawLink) throws Exception {
        // Even if called from future UI code, never store unchecked input.
        VlessLink.parse(rawLink);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, nodeKey(true));
        cipher.updateAAD(AAD);
        byte[] encrypted = cipher.doFinal(rawLink.getBytes(StandardCharsets.UTF_8));
        byte[] nonce = cipher.getIV();
        if (nonce == null || nonce.length != 12)
            throw new GeneralSecurityException("Invalid encryption nonce");
        boolean committed = preferences(ctx).edit()
                .putString(PREF_IV, Base64.encodeToString(nonce, Base64.NO_WRAP))
                .putString(PREF_DATA, Base64.encodeToString(encrypted, Base64.NO_WRAP))
                .putBoolean(PREF_AUTO, true)
                .commit();
        if (!committed) throw new GeneralSecurityException("Could not save node");
    }

    /** Returns null only when there is no stored node. Corruption is an error. */
    static synchronized String load(Context ctx) throws Exception {
        SharedPreferences p = preferences(ctx);
        String nonceText = p.getString(PREF_IV, null);
        String encryptedText = p.getString(PREF_DATA, null);
        if (nonceText == null && encryptedText == null) return null;
        if (nonceText == null || encryptedText == null)
            throw new GeneralSecurityException("Incomplete saved node");
        byte[] nonce = Base64.decode(nonceText, Base64.NO_WRAP);
        byte[] encrypted = Base64.decode(encryptedText, Base64.NO_WRAP);
        if (nonce.length != 12 || encrypted.length < 16)
            throw new GeneralSecurityException("Invalid saved data");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, nodeKey(false), new GCMParameterSpec(128, nonce));
        cipher.updateAAD(AAD);
        String rawLink = new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        VlessLink.parse(rawLink);
        return rawLink;
    }

    static synchronized void clear(Context ctx) throws Exception {
        if (!preferences(ctx).edit().clear().commit())
            throw new GeneralSecurityException("Cannot remove saved node");
        KeyStore store = keystore();
        if (store.containsAlias(KEY_ALIAS)) store.deleteEntry(KEY_ALIAS);
    }
}
