package cn.borealos.glacier.geckopreview;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONObject;
import org.json.JSONArray;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import static org.junit.Assert.*;

/** Tests the exact encrypted envelope also consumed by Windows and macOS. */
@RunWith(AndroidJUnit4.class)
public class GlacierBookmarkPortableInstrumentedTest {
    private JSONObject fixture() throws Exception {
        try(InputStream in=InstrumentationRegistry.getInstrumentation().getContext()
                .getAssets().open("glacier_bookmark_portable_work_v1.json")) {
            java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream();
            byte[] buffer=new byte[4096];
            int n;
            while((n=in.read(buffer))!=-1)out.write(buffer,0,n);
            return new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
        }
    }

    @Test public void androidDecryptsDesktopWorkBookmarksAndReencryptsWithFreshRandomness()
            throws Exception {
        JSONObject f=fixture();
        List<BrowserLibraryStore.Entry> imported=GlacierBookmarkPortable.decrypt(
                "work",f.getString("envelope"),f.getString("passphrase"));
        assertEquals(2,imported.size());
        JSONArray expected=f.getJSONArray("bookmarks");
        for(int i=0;i<imported.size();i++) {
            JSONObject row=expected.getJSONObject(i);
            assertEquals(row.getString("title"),imported.get(i).title);
            assertEquals(row.getString("url"),imported.get(i).url);
            assertEquals(row.getLong("at"),imported.get(i).timestamp);
            assertEquals("work",imported.get(i).profile);
        }
        String rotated=GlacierBookmarkPortable.encrypt(
                "work",imported,f.getString("passphrase"));
        assertNotEquals(f.getString("envelope"),rotated);
        assertEquals(2,GlacierBookmarkPortable.decrypt(
                "work",rotated,f.getString("passphrase")).size());
    }

    @Test public void bookmarkEnvelopeRejectsWrongSpaceAndWrongPassphrase() throws Exception {
        JSONObject f=fixture();
        for(String mode:new String[]{"wrong-space","wrong-password"}) {
            try {
                GlacierBookmarkPortable.decrypt(
                        "wrong-space".equals(mode)?"private":"work",
                        f.getString("envelope"),
                        "wrong-password".equals(mode)?"not-the-right-bookmark-passphrase":
                                f.getString("passphrase"));
                fail("Unexpectedly accepted encrypted bookmark "+mode);
            }catch(Exception expected) {}
        }
        try {
            GlacierCloudSync.decrypt("work",f.getString("envelope"),
                    f.getString("passphrase"));
            fail("Account vault MUST reject a bookmark payload");
        }catch(Exception expected) {}
    }

    @Test public void mergePreservesLocalAndOtherSpaceWithoutDataLoss() throws Exception {
        JSONObject f=fixture();
        List<BrowserLibraryStore.Entry> imported=GlacierBookmarkPortable.decrypt(
                "work",f.getString("envelope"),f.getString("passphrase"));
        BrowserLibraryStore.Snapshot existing=new BrowserLibraryStore.Snapshot();
        existing.bookmarks.add(new BrowserLibraryStore.Entry(
                "private","私人的书签","https://private.example.org/","","","",0,100));
        existing.bookmarks.add(new BrowserLibraryStore.Entry(
                "work","旧本地标题","https://docs.example.org/guide","","","",0,101));
        existing.history.add(new BrowserLibraryStore.Entry(
                "private","History","https://history.example.org/","","","",0,102));
        existing.downloads.add(new BrowserLibraryStore.Entry(
                "private","File","","download","content://com.example.documents/items/1",
                "application/pdf",120,103));
        BrowserLibraryStore.Snapshot merged=GlacierBookmarkPortable.previewMerge(
                existing,"work",imported);
        assertEquals(3,merged.bookmarks.size());
        assertEquals(1,merged.history.size());
        assertEquals(1,merged.downloads.size());
        assertEquals("私人的书签",merged.bookmarks.get(0).title);
        assertEquals("旧本地标题",merged.bookmarks.get(1).title);
        assertEquals("Glacier 示例工作站",merged.bookmarks.get(2).title);
        assertEquals(2,existing.bookmarks.size()); // preview never mutates
    }

    @Test public void importingWorkMustNotEvictFullPrivateBookmarkStore() throws Exception {
        JSONObject f=fixture();
        List<BrowserLibraryStore.Entry> imported=GlacierBookmarkPortable.decrypt(
                "work",f.getString("envelope"),f.getString("passphrase"));
        BrowserLibraryStore.Snapshot full=new BrowserLibraryStore.Snapshot();
        for(int i=0;i<160;i++) {
            full.bookmarks.add(new BrowserLibraryStore.Entry(
                    "private","Private "+i,"https://private.example.org/"+i,
                    "","","",0,i));
        }
        try {
            GlacierBookmarkPortable.previewMerge(full,"work",imported);
            fail("An imported work bookmark may evict a private bookmark");
        }catch(java.io.IOException expected) {}
        assertEquals(160,full.bookmarks.size());
    }

    @Test public void duplicateAndCrossProfileMergeAreRejected() throws Exception {
        JSONObject f=fixture();
        List<BrowserLibraryStore.Entry> imported=GlacierBookmarkPortable.decrypt(
                "work",f.getString("envelope"),f.getString("passphrase"));
        List<BrowserLibraryStore.Entry> bad=new ArrayList<>(imported);
        bad.add(imported.get(0));
        try {
            GlacierBookmarkPortable.previewMerge(new BrowserLibraryStore.Snapshot(),
                    "work",bad);
            fail("Duplicate imported bookmark allowed");
        }catch(Exception expected){}
        try {
            GlacierBookmarkPortable.previewMerge(new BrowserLibraryStore.Snapshot(),
                    "private",imported);
            fail("Cross-profile import allowed");
        }catch(Exception expected){}
    }
}
