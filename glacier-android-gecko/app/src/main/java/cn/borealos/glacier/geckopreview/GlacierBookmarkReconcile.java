package cn.borealos.glacier.geckopreview;

import org.json.JSONObject;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/**
 * Fail-closed bookmark sync decisions for Android. No network, persistence,
 * login override, or background auto-transfer in this class.
 *
 * Caller MUST use the already approved GlacierCloudSync.State and
 * GlacierCloudSync.call over a running NativeProxy, then persist any
 * approved/downloaded BrowserLibraryStore snapshot before storing checkpoint.
 * Never sends bookmarks to /v1/vault/{private,work} (account cards).
 */
final class GlacierBookmarkReconcile {
    static final class Plan {
        final String kind, expectedLocalHash, ciphertext;
        final long expectedVersion;
        final BrowserLibraryStore.Snapshot preview;
        final JSONObject checkpoint;
        Plan(String k,String hash,long v,String encrypted,
             BrowserLibraryStore.Snapshot snapshot,JSONObject cp) {
            kind=k;expectedLocalHash=hash;expectedVersion=v;
            ciphertext=encrypted;preview=snapshot;checkpoint=cp;
        }
    }

    private GlacierBookmarkReconcile() {}

    private static List<BrowserLibraryStore.Entry> inSpace(
            BrowserLibraryStore.Snapshot snapshot,String space) throws Exception {
        if(snapshot==null||!BrowserLibraryStore.validProfile(space))
            throw new IOException("Invalid bookmark snapshot/space");
        List<BrowserLibraryStore.Entry> rows=new ArrayList<>();
        for(BrowserLibraryStore.Entry e:snapshot.bookmarks) {
            if(!BrowserLibraryStore.validProfile(e.profile))
                throw new IOException("Invalid local bookmark space");
            if(space.equals(e.profile))rows.add(e);
        }
        return rows;
    }

    private static String hash(BrowserLibraryStore.Snapshot snapshot,String space)
            throws Exception {
        List<BrowserLibraryStore.Entry> list=inSpace(snapshot,space);
        List<BrowserLibraryStore.Entry> rows=new ArrayList<>(list);
        rows.sort(Comparator.comparing((BrowserLibraryStore.Entry e)->e.url)
                .thenComparing(e->e.title).thenComparingLong(e->e.timestamp));
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        for(BrowserLibraryStore.Entry entry:rows) {
            if(!BrowserLibraryStore.validWebUrl(entry.url)
                    ||entry.title==null||entry.title.isEmpty()
                    ||entry.timestamp<0||entry.timestamp>4102444800000L)
                throw new IOException("Invalid local bookmark data");
            for(String value:new String[]{entry.profile,entry.url,entry.title,
                    Long.toString(entry.timestamp)}) {
                byte[] bytes=value.getBytes(StandardCharsets.UTF_8);
                digest.update(ByteBuffer.allocate(4).putInt(bytes.length).array());
                digest.update(bytes);
            }
        }
        StringBuilder text=new StringBuilder();
        for(byte b:digest.digest())text.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        return text.toString();
    }

    private static BrowserLibraryStore.Snapshot fromRows(
            List<BrowserLibraryStore.Entry> rows) {
        BrowserLibraryStore.Snapshot s=new BrowserLibraryStore.Snapshot();
        s.bookmarks.addAll(rows);
        return s;
    }

    private static JSONObject checkpoint(String owner,String space,long version,
            BrowserLibraryStore.Snapshot local,
            BrowserLibraryStore.Snapshot remote) throws Exception {
        if(owner==null||owner.isEmpty()||owner.length()>256||version<0
                ||version>Integer.MAX_VALUE)
            throw new IOException("Invalid bookmark account scope or version");
        return new JSONObject().put("owner",owner).put("space",space)
                .put("version",version)
                .put("local_hash",hash(local,space))
                .put("remote_hash",hash(remote,space));
    }

    private static void verifyCheckpoint(JSONObject state,String owner,String space)
            throws Exception {
        if(state==null||!owner.equals(state.optString("owner",""))
                ||!space.equals(state.optString("space","")))
            throw new IOException("Bookmark checkpoint belongs to another account or space");
        if(state.optLong("version",-1)<0||state.optLong("version",-1)>Integer.MAX_VALUE
                ||!state.optString("local_hash","").matches("[0-9a-f]{64}")
                ||!state.optString("remote_hash","").matches("[0-9a-f]{64}"))
            throw new IOException("Bookmark checkpoint damaged");
    }

    private static long remoteVersion(JSONObject cloud) throws Exception {
        if(cloud==null||!(cloud.opt("version") instanceof Integer
                ||cloud.opt("version") instanceof Long))
            throw new IOException("Invalid cloud bookmark version");
        long version=((Number)cloud.opt("version")).longValue();
        if(version<0||version>Integer.MAX_VALUE)
            throw new IOException("Cloud bookmark version out of range");
        return version;
    }

    private static BrowserLibraryStore.Snapshot remoteSnapshot(
            JSONObject cloud,long version,String space,String passphrase) throws Exception {
        if(version==0) {
            if(!cloud.isNull("envelope") && cloud.has("envelope"))
                throw new IOException("Unversioned bookmark ciphertext refused");
            return new BrowserLibraryStore.Snapshot();
        }
        String encrypted=cloud.optString("envelope","");
        if(encrypted.isEmpty())throw new IOException("Missing cloud bookmark ciphertext");
        return fromRows(GlacierBookmarkPortable.decrypt(space,encrypted,passphrase));
    }

    /** No baseline means no implicit upload: require explicit initial choice. */
    static Plan reconcile(String owner,String space,BrowserLibraryStore.Snapshot local,
            JSONObject baseline,JSONObject cloud,String passphrase) throws Exception {
        if(baseline==null)
            return new Plan("uninitialized","",0,null,null,null);
        verifyCheckpoint(baseline,owner,space);
        String currentHash=hash(local,space);
        long before=baseline.getLong("version");
        long remoteVer=remoteVersion(cloud);
        if(remoteVer<before)
            return new Plan("rollback",currentHash,before,null,null,null);
        BrowserLibraryStore.Snapshot remote=remoteSnapshot(cloud,remoteVer,space,passphrase);
        String remoteHash=hash(remote,space);
        if(remoteVer==before&&!remoteHash.equals(baseline.getString("remote_hash")))
            return new Plan("tampered",currentHash,before,null,null,null);
        boolean here=!currentHash.equals(baseline.getString("local_hash"));
        boolean there=remoteVer!=before;
        if(here&&there)
            return new Plan("conflict",currentHash,remoteVer,null,null,null);
        if(here) {
            String encrypted=GlacierBookmarkPortable.encrypt(space,inSpace(local,space),passphrase);
            return new Plan("upload_pending",currentHash,remoteVer,encrypted,null,
                    checkpoint(owner,space,remoteVer+1,local,local));
        }
        if(there) {
            BrowserLibraryStore.Snapshot merged=GlacierBookmarkPortable.previewMerge(
                    local,space,inSpace(remote,space));
            return new Plan("download_pending",currentHash,remoteVer,null,merged,
                    checkpoint(owner,space,remoteVer,merged,remote));
        }
        return new Plan("unchanged",currentHash,remoteVer,null,null,null);
    }

    static Plan firstSync(String owner,String space,BrowserLibraryStore.Snapshot local,
            JSONObject cloud,String passphrase,String explicitChoice) throws Exception {
        if(!"upload".equals(explicitChoice)&&!"download".equals(explicitChoice))
            throw new IOException("Explicit initial upload/download consent required");
        String localHash=hash(local,space);
        long version=remoteVersion(cloud);
        BrowserLibraryStore.Snapshot remote=remoteSnapshot(cloud,version,space,passphrase);
        if("upload".equals(explicitChoice)) {
            if(version!=0)throw new IOException("Remote bookmarks exist: refuse first upload");
            String crypt=GlacierBookmarkPortable.encrypt(space,inSpace(local,space),passphrase);
            return new Plan("upload_pending",localHash,0,crypt,null,
                    checkpoint(owner,space,1,local,local));
        }
        if(version==0)return new Plan("empty",localHash,0,null,null,null);
        BrowserLibraryStore.Snapshot merged=GlacierBookmarkPortable.previewMerge(
                local,space,inSpace(remote,space));
        return new Plan("download_pending",localHash,version,null,merged,
                checkpoint(owner,space,version,merged,remote));
    }

    /** Caller verifies local unchanged, then saves preview in encrypted store. */
    static JSONObject approveImport(String owner,String space,
            BrowserLibraryStore.Snapshot current,Plan plan) throws Exception {
        if(plan==null||!"download_pending".equals(plan.kind)
                ||plan.preview==null||plan.checkpoint==null)
            throw new IOException("No import pending");
        if(!hash(current,space).equals(plan.expectedLocalHash))
            throw new IOException("Local bookmarks changed while download was pending");
        verifyCheckpoint(plan.checkpoint,owner,space);
        if(!hash(plan.preview,space).equals(plan.checkpoint.getString("local_hash")))
            throw new IOException("Import preview changed");
        return plan.checkpoint;
    }

    /** Only a strictly monotonic CAS PUT acknowledgement allows checkpoint save. */
    static JSONObject approveUpload(Plan plan,JSONObject reply) throws Exception {
        if(plan==null||!"upload_pending".equals(plan.kind)
                ||plan.checkpoint==null||reply==null)
            throw new IOException("No upload pending");
        long version=remoteVersion(reply);
        if(version!=plan.expectedVersion+1)
            throw new IOException("Upload CAS acknowledgement did not advance by one");
        return plan.checkpoint;
    }
}
