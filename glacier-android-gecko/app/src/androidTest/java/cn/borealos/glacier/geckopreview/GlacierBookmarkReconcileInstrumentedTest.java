package cn.borealos.glacier.geckopreview;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import java.util.ArrayList;
import java.util.List;

/** No production network or account session; all Android decisions are offline. */
@RunWith(AndroidJUnit4.class)
public class GlacierBookmarkReconcileInstrumentedTest {
    private static final String OWNER="https://sync.borealos.cn|synthetic-user";
    private static final String PASS="synthetic-bookmark-passphrase-2026";
    private static BrowserLibraryStore.Entry row(String profile,String title,String url,long at) {
        return new BrowserLibraryStore.Entry(profile,title,url,"","","",0,at);
    }
    private static BrowserLibraryStore.Snapshot local() {
        BrowserLibraryStore.Snapshot s=new BrowserLibraryStore.Snapshot();
        s.bookmarks.add(row("private","Keep private","https://private.example.org/keep",44));
        s.bookmarks.add(row("work","Work","https://work.example.org/guide",45));
        return s;
    }
    private static JSONObject cloud(long version,String envelope) throws Exception {
        return new JSONObject().put("version",version)
                .put("envelope",envelope==null?JSONObject.NULL:envelope);
    }
    private static String envelope(String name) throws Exception {
        List<BrowserLibraryStore.Entry> list=new ArrayList<>();
        list.add(row("work",name,"https://work.example.org/guide",45));
        return GlacierBookmarkPortable.encrypt("work",list,PASS);
    }

    @Test public void initialSyncRequiresUserChoiceAndNeverMutatesLocal() throws Exception {
        BrowserLibraryStore.Snapshot original=local();
        JSONObject empty=cloud(0,null);
        assertEquals("uninitialized",
                GlacierBookmarkReconcile.reconcile(OWNER,"work",original,null,empty,PASS).kind);
        try {
            GlacierBookmarkReconcile.firstSync(OWNER,"work",original,empty,PASS,"auto");
            fail("Initial automatic upload must not occur without explicit choice");
        }catch(java.io.IOException expected){}
        GlacierBookmarkReconcile.Plan pending=GlacierBookmarkReconcile.firstSync(
                OWNER,"work",original,empty,PASS,"upload");
        assertEquals("upload_pending",pending.kind);
        assertEquals(0,pending.expectedVersion);
        assertNotNull(pending.ciphertext);
        assertEquals(2,original.bookmarks.size());
        assertEquals(1,GlacierBookmarkReconcile.approveUpload(
                pending,new JSONObject().put("version",1)).getInt("version"));
        try {
            GlacierBookmarkReconcile.approveUpload(pending,new JSONObject().put("version",0));
            fail("Stale CAS upload acknowledgement accepted");
        }catch(java.io.IOException expected){}
        try {
            GlacierBookmarkReconcile.firstSync(
                    OWNER,"work",original,cloud(1,envelope("Work")),PASS,"upload");
            fail("Initial upload must refuse to replace pre-existing cloud data");
        }catch(java.io.IOException expected){}
    }

    @Test public void downloadDoesNotReplacePrivateOrExistingLocalTitle() throws Exception {
        BrowserLibraryStore.Snapshot before=local();
        List<BrowserLibraryStore.Entry> remote=new ArrayList<>();
        remote.add(row("work","Renamed externally","https://work.example.org/guide",50));
        remote.add(row("work","New external","https://work.example.org/new",51));
        String encrypted=GlacierBookmarkPortable.encrypt("work",remote,PASS);
        GlacierBookmarkReconcile.Plan plan=GlacierBookmarkReconcile.firstSync(
                OWNER,"work",before,cloud(3,encrypted),PASS,"download");
        assertEquals("download_pending",plan.kind);
        assertEquals(3,plan.preview.bookmarks.size());
        assertEquals("Keep private",plan.preview.bookmarks.get(0).title);
        assertEquals("Work",plan.preview.bookmarks.get(1).title);
        assertEquals("New external",plan.preview.bookmarks.get(2).title);
        assertEquals(2,before.bookmarks.size()); // pending import never writes
        assertEquals(3,GlacierBookmarkReconcile.approveImport(
                OWNER,"work",before,plan).getInt("version"));
        before.bookmarks.add(row("work","Changed meanwhile","https://work.example.org/edit",52));
        try {
            GlacierBookmarkReconcile.approveImport(OWNER,"work",before,plan);
            fail("Locally edited bookmarks must block stale cloud import");
        }catch(java.io.IOException expected){}
    }

    @Test public void rollbackTamperingAndSimultaneousChangesNeverUpload() throws Exception {
        BrowserLibraryStore.Snapshot local=local();
        GlacierBookmarkReconcile.Plan first=GlacierBookmarkReconcile.firstSync(
                OWNER,"work",local,cloud(0,null),PASS,"upload");
        JSONObject checkpoint=GlacierBookmarkReconcile.approveUpload(first,
                new JSONObject().put("version",1));
        String base=envelope("Work");
        assertEquals("unchanged",GlacierBookmarkReconcile.reconcile(
                OWNER,"work",local,checkpoint,cloud(1,base),PASS).kind);
        assertEquals("rollback",GlacierBookmarkReconcile.reconcile(
                OWNER,"work",local,checkpoint,cloud(0,null),PASS).kind);
        assertEquals("tampered",GlacierBookmarkReconcile.reconcile(
                OWNER,"work",local,checkpoint,cloud(1,envelope("Tampered")),PASS).kind);
        local.bookmarks.add(row("work","New Local","https://work.example.org/local",60));
        assertEquals("conflict",GlacierBookmarkReconcile.reconcile(
                OWNER,"work",local,checkpoint,cloud(2,envelope("Work")),PASS).kind);
        assertEquals(3,local.bookmarks.size());
        try {
            GlacierBookmarkReconcile.reconcile(
                    OWNER+"-other","work",local,checkpoint,cloud(1,base),PASS);
            fail("Cross-account checkpoint accepted");
        }catch(java.io.IOException expected){}
    }

    @Test public void fullPrivateLibraryCannotBeEvictedByWorkSync() throws Exception {
        BrowserLibraryStore.Snapshot full=new BrowserLibraryStore.Snapshot();
        for(int i=0;i<160;i++) {
            full.bookmarks.add(row("private","Private "+i,
                    "https://private.example.org/"+i,i));
        }
        try {
            GlacierBookmarkReconcile.firstSync(
                    OWNER,"work",full,cloud(1,envelope("Work")),PASS,"download");
            fail("Work import must refuse when global private library is full");
        }catch(java.io.IOException expected){}
        assertEquals(160,full.bookmarks.size());
    }
}
