package cn.borealos.glacier.geckopreview;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.junit.Test;
import org.junit.runner.RunWith;

import static org.junit.Assert.*;

/**
 * No networking or user credentials. Validates encrypted opt-in persistence,
 * auto-connect toggling, tamper rejection, and deletion with Android Keystore.
 */
@RunWith(AndroidJUnit4.class)
public final class SavedVlessNodeInstrumentedTest {
    private static final String FAKE_NODE =
            "vless://123e4567-e89b-12d3-a456-426614174000@example.com:443"
            + "?encryption=none&security=tls&type=tcp&sni=example.com";

    @Test
    public void encryptedNodeCanBeRestoredAfterSessionAndDeleted() throws Exception {
        Context ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();
        SavedVlessNode.clear(ctx);
        try {
            assertFalse(SavedVlessNode.exists(ctx));
            assertNull(SavedVlessNode.load(ctx));
            SavedVlessNode.save(ctx, FAKE_NODE);
            assertTrue(SavedVlessNode.exists(ctx));
            assertTrue(SavedVlessNode.autoConnectEnabled(ctx));
            assertEquals(FAKE_NODE,SavedVlessNode.load(ctx));

            SharedPreferences prefs=ctx.getSharedPreferences(
                    "glacier_saved_network_v1",Context.MODE_PRIVATE);
            String ciphertext=prefs.getString("encrypted_node",null);
            String iv=prefs.getString("iv",null);
            assertNotNull(ciphertext);
            assertNotNull(iv);
            assertFalse(ciphertext.contains("123e4567"));
            assertFalse(ciphertext.contains("example.com"));
            assertEquals(12,Base64.decode(iv,Base64.NO_WRAP).length);

            SavedVlessNode.disableAutoConnect(ctx);
            assertFalse(SavedVlessNode.autoConnectEnabled(ctx));
            assertEquals(FAKE_NODE,SavedVlessNode.load(ctx));

            SavedVlessNode.save(ctx, FAKE_NODE);
            assertTrue(SavedVlessNode.autoConnectEnabled(ctx));
            prefs.edit().putString("encrypted_node",
                    Base64.encodeToString(new byte[32],Base64.NO_WRAP)).commit();
            try {
                SavedVlessNode.load(ctx);
                fail("GCM authentication must reject corrupted data");
            } catch (Exception expected) {
                // Tampering must never silently restore a different link.
            }
        } finally {
            SavedVlessNode.clear(ctx);
        }
        assertFalse(SavedVlessNode.exists(ctx));
        assertNull(SavedVlessNode.load(ctx));
    }
}
