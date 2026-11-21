package cn.borealos.glacier.geckopreview;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.*;

/**
 * Read a deterministic synthetic Windows/macOS vault fixture on Android.
 * Never use the fixture's fixed nonce/salt in production encryption.
 * No real credentials, external network, cookies or actual user account data.
 */
@RunWith(AndroidJUnit4.class)
public final class GlacierVaultInteropInstrumentedTest {
    private JSONObject fixture() throws Exception {
        return fixture("glacier_sync_interop_private_v1.json");
    }

    private JSONObject fixture(String assetName) throws Exception {
        try (InputStream stream = InstrumentationRegistry.getInstrumentation()
                .getContext().getAssets().open(assetName)) {
            byte[] data = stream.readAllBytes();
            assertTrue("Synthetic fixture must remain bounded", data.length < 8192);
            return new JSONObject(new String(data, StandardCharsets.UTF_8));
        }
    }

    @Test
    public void androidDecryptsDesktopAESGcmPbkdF2Vault() throws Exception {
        JSONObject f = fixture();
        JSONObject expected = f.getJSONObject("card");
        String space = f.getString("space");
        String phrase = f.getString("passphrase");
        String encrypted = f.getString("envelope");
        assertFalse("Plaintext secret must not appear in encrypted envelope",
                encrypted.contains(expected.getString("password")));
        List<BrowserAccountsStore.Card> actual = GlacierCloudSync.decrypt(
                space, encrypted, phrase);
        assertEquals(1, actual.size());
        BrowserAccountsStore.Card card = actual.get(0);
        assertEquals(expected.getString("site"), card.site);
        assertEquals(expected.getString("name"), card.name);
        assertEquals(expected.getString("username"), card.username);
        assertEquals(expected.getString("password"), card.password);
        assertEquals(expected.getString("code_api"), card.codeApi);
        assertEquals(space, card.profile);

        // The Android encryptor must produce a fresh randomized vault envelope.
        String newlyEncrypted = GlacierCloudSync.encrypt(space, actual, phrase);
        assertNotEquals(encrypted, newlyEncrypted);
        List<BrowserAccountsStore.Card> restored = GlacierCloudSync.decrypt(
                space, newlyEncrypted, phrase);
        assertEquals(1, restored.size());
        assertEquals(card.password, restored.get(0).password);
    }

    @Test
    public void androidRejectsWrongPassphraseAndWrongAccountSpace() throws Exception {
        JSONObject f = fixture();
        String space = f.getString("space");
        String phrase = f.getString("passphrase");
        String encrypted = f.getString("envelope");
        try {
            GlacierCloudSync.decrypt(space, encrypted, "incorrect-synthetic-passphrase");
            fail("Wrong passphrase must never import the desktop vault");
        } catch (Exception expected) {}
        try {
            GlacierCloudSync.decrypt("work", encrypted, phrase);
            fail("Cross-space vault must never import into work profile");
        } catch (Exception expected) {}
    }
    @Test
    public void androidDecryptsWorkVaultAndRejectsCrossSpaceImports() throws Exception {
        JSONObject f = fixture("glacier_sync_interop_work_v1.json");
        String phrase = f.getString("passphrase");
        String encrypted = f.getString("envelope");
        JSONObject expected = f.getJSONObject("card");
        assertEquals("work", f.getString("space"));
        assertFalse(encrypted.contains(expected.getString("password")));
        List<BrowserAccountsStore.Card> cards = GlacierCloudSync.decrypt(
                "work", encrypted, phrase);
        assertEquals(1, cards.size());
        BrowserAccountsStore.Card card = cards.get(0);
        assertEquals("work", card.profile);
        assertEquals(expected.getString("site"), card.site);
        assertEquals(expected.getString("name"), card.name);
        assertEquals(expected.getString("username"), card.username);
        assertEquals(expected.getString("password"), card.password);
        assertEquals(expected.getString("code_api"), card.codeApi);

        String rotated = GlacierCloudSync.encrypt("work", cards, phrase);
        assertNotEquals("Production encryption must randomize salt/nonce", encrypted, rotated);
        assertEquals(card.password,
                GlacierCloudSync.decrypt("work", rotated, phrase).get(0).password);
        try {
            GlacierCloudSync.decrypt("private", encrypted, phrase);
            fail("Work vault ciphertext must not decrypt in private space");
        } catch (Exception expectedFailure) {}
        try {
            GlacierCloudSync.decrypt("work", encrypted, "synthetic-wrong-passphrase");
            fail("Wrong passphrase must never import work credentials");
        } catch (Exception expectedFailure) {}
    }

}
