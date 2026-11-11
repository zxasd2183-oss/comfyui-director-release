package cn.borealos.glacier.geckopreview;

import android.content.Context;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;

import static org.junit.Assert.*;

/**
 * The test data is synthetic; no user credentials or external network.
 * Checks encrypted tab metadata, cross-profile ownership, thumbnail bytes,
 * tamper rejection and atomic save/restore.
 */
@RunWith(AndroidJUnit4.class)
public final class BrowserTabStoreInstrumentedTest {
    @Test
    public void encryptedRestoreKeepsTabOrderAndProfileAndRejectsTampering() throws Exception {
        Context ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();
        File file = new File(ctx.getNoBackupFilesDir(), "glacier-tabs-v1.bin");
        file.delete();
        byte[] preview = new byte[]{1,2,3,4,5};
        BrowserTabStore.Snapshot original = new BrowserTabStore.Snapshot();
        original.activeId = "test-tab-work-5678";
        original.tabs.add(new BrowserTabStore.TabRecord("test-tab-private-1234",
                "private", "https://example.com/", "Example private",
                "{\"safe\":\"fake-state\"}", preview));
        original.tabs.add(new BrowserTabStore.TabRecord("test-tab-work-5678",
                "work", "https://example.org/", "Example work", "", null));
        original.tabs.add(new BrowserTabStore.TabRecord("test-tab-not-safe",
                "work", "http://127.0.0.1:18765/transfer", "CI fixture", "", null));
        assertFalse(BrowserTabStore.validUrl("javascript:alert(1)"));
        assertFalse(BrowserTabStore.validUrl("file:///etc/passwd"));
        assertFalse(BrowserTabStore.validUrl("http://127.0.0.1:18765/transfer"));
        try {
            BrowserTabStore.save(ctx, original);
            byte[] ciphertext=Files.readAllBytes(file.toPath());
            String raw = new String(ciphertext, java.nio.charset.StandardCharsets.ISO_8859_1);
            assertFalse(raw.contains("example.com"));
            assertFalse(raw.contains("Example private"));
            assertTrue(ciphertext.length > 32);
            BrowserTabStore.Snapshot restored=BrowserTabStore.load(ctx);
            assertEquals(2, restored.tabs.size());
            assertEquals("test-tab-work-5678", restored.activeId);
            assertEquals("private",restored.tabs.get(0).profile);
            assertEquals("work",restored.tabs.get(1).profile);
            assertEquals("https://example.org/",restored.tabs.get(1).url);
            assertEquals("{\"safe\":\"fake-state\"}",restored.tabs.get(0).state);
            assertArrayEquals(preview,restored.tabs.get(0).thumb);
            ciphertext[ciphertext.length - 1] ^= 0x01;
            Files.write(file.toPath(), ciphertext);
            try {
                BrowserTabStore.load(ctx);
                fail("AES-GCM must reject modified tab file");
            } catch (Exception expected) {
                // Authenticated encryption must fail closed.
            }
        } finally {
            file.delete();
        }
    }
}
