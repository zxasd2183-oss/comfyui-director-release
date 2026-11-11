package cn.borealos.glacier.geckopreview;

import android.content.Context;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

import static org.junit.Assert.*;

/** All synthetic. Verifies M04 encryption, isolation, safe schemes and tamper rejection. */
@RunWith(AndroidJUnit4.class)
public final class BrowserLibraryStoreInstrumentedTest {
    @Test
    public void encryptedLibraryKeepsTwoProfilesAndRejectsChanges() throws Exception {
        Context ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();
        File file=new File(ctx.getNoBackupFilesDir(),"glacier-library-v1.bin");
        file.delete();
        assertFalse(BrowserLibraryStore.validWebUrl("javascript:alert(1)"));
        assertFalse(BrowserLibraryStore.validWebUrl("file:///private/secrets.txt"));
        assertFalse(BrowserLibraryStore.validWebUrl("http://127.0.0.1:18765/transfer"));
        assertFalse(BrowserLibraryStore.validWebUrl("https://user:password@example.com/"));
        assertTrue(BrowserLibraryStore.validWebUrl("https://example.com/a?q=1"));
        assertFalse(BrowserLibraryStore.validDocumentUri("file:///tmp/a"));
        assertTrue(BrowserLibraryStore.validDocumentUri(
                "content://com.android.providers.downloads.documents/document/100"));

        BrowserLibraryStore.Snapshot snapshot=new BrowserLibraryStore.Snapshot();
        snapshot.bookmarks.add(new BrowserLibraryStore.Entry(
                "private","Private Example","https://example.com/","","","",0,100));
        snapshot.bookmarks.add(new BrowserLibraryStore.Entry(
                "work","Work Example","https://example.org/","","","",0,200));
        snapshot.history.add(new BrowserLibraryStore.Entry(
                "private","One","https://example.com/path?sample=1","","","",0,300));
        snapshot.history.add(new BrowserLibraryStore.Entry(
                "work","Two","https://example.org/","","","",0,400));
        snapshot.downloads.add(new BrowserLibraryStore.Entry(
                "work","","","example.txt",
                "content://com.android.providers.downloads.documents/document/100",
                "text/plain",21,500));
        snapshot.history.add(new BrowserLibraryStore.Entry(
                "private","Fixture","http://127.0.0.1:18765/transfer","","","",0,0));
        try {
            BrowserLibraryStore.save(ctx,snapshot);
            byte[] cipher=Files.readAllBytes(file.toPath());
            String raw=new String(cipher,StandardCharsets.ISO_8859_1);
            assertFalse(raw.contains("example.com"));
            assertFalse(raw.contains("Private Example"));
            assertFalse(raw.contains("example.txt"));
            BrowserLibraryStore.Snapshot restored=BrowserLibraryStore.load(ctx);
            assertEquals(2,restored.bookmarks.size());
            assertEquals(2,restored.history.size());
            assertEquals(1,restored.downloads.size());
            assertEquals("private",restored.bookmarks.get(0).profile);
            assertEquals("work",restored.bookmarks.get(1).profile);
            assertEquals("https://example.com/path?sample=1",
                    restored.history.get(0).url);
            assertEquals(21,restored.downloads.get(0).bytes);
            assertEquals("work",restored.downloads.get(0).profile);

            restored.bookmarks.remove(0);
            restored.history.removeIf(e->e.profile.equals("private"));
            BrowserLibraryStore.save(ctx,restored);
            BrowserLibraryStore.Snapshot reduced=BrowserLibraryStore.load(ctx);
            assertEquals(1,reduced.bookmarks.size());
            assertEquals("work",reduced.bookmarks.get(0).profile);
            assertEquals(1,reduced.history.size());
            assertEquals("work",reduced.history.get(0).profile);

            cipher=Files.readAllBytes(file.toPath());
            cipher[cipher.length-1]^=1;
            Files.write(file.toPath(),cipher);
            try {
                BrowserLibraryStore.load(ctx);
                fail("Modified GCM ciphertext must not be accepted");
            } catch(Exception expected) {
                // Authentication failure is correct.
            }
        } finally {
            file.delete();
        }
    }
}
