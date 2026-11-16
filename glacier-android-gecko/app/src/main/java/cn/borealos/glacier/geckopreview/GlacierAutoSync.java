package cn.borealos.glacier.geckopreview;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Non-destructive E2E account synchronization decision engine.
 * Run only on an executor. Never log tokens, password, account cards or HTTPS
 * responses. A baseline is established only by an explicit first upload/pull.
 */
final class GlacierAutoSync {
    static final class Result {
        final String space, kind, localHash;
        final int version;
        final List<BrowserAccountsStore.Card> cards;
        Result(String s,String k,int v,String h,List<BrowserAccountsStore.Card> c) {
            space=s;kind=k;version=v;localHash=h;cards=c;
        }
    }

    private GlacierAutoSync() {}

    static String fingerprint(List<BrowserAccountsStore.Card> all,String space) throws Exception {
        List<BrowserAccountsStore.Card> rows=new ArrayList<>();
        for(BrowserAccountsStore.Card card:all) {
            if(space.equals(card.profile))rows.add(card);
        }
        rows.sort(Comparator.comparing((BrowserAccountsStore.Card c)->c.site)
                .thenComparing(c->c.name.toLowerCase(java.util.Locale.ROOT)));
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        for(BrowserAccountsStore.Card row:rows) {
            if(!BrowserAccountsStore.valid(row))
                throw new java.io.IOException("Corrupt local account card");
            for(String part:new String[]{row.profile,row.site,row.name,
                    row.username,row.password,row.codeApi}) {
                byte[] encoded=part.getBytes(StandardCharsets.UTF_8);
                digest.update(java.nio.ByteBuffer.allocate(4).putInt(encoded.length).array());
                digest.update(encoded);
            }
        }
        byte[] hash=digest.digest();
        StringBuilder out=new StringBuilder();
        for(byte b:hash)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        return out.toString();
    }

    /** Accept only integer server versions that never move backwards. */
    static boolean versionRollsBack(int known,long observed) {
        return known < 0 || observed < 0
                || observed > Integer.MAX_VALUE || observed < known;
    }

    static int serverVersion(JSONObject response) throws java.io.IOException {
        Object value=response.opt("version");
        if(!(value instanceof Integer) && !(value instanceof Long))
            throw new java.io.IOException("Malformed cloud version");
        long number=((Number)value).longValue();
        if(number < 0 || number > Integer.MAX_VALUE)
            throw new java.io.IOException("Invalid cloud version");
        return (int)number;
    }


    /** Manual actions must honor the same high-water mark as automatic sync. */
    static JSONObject baselineForSpace(JSONObject baselines,String space)
            throws java.io.IOException {
        if(baselines==null)throw new java.io.IOException("Missing local sync state");
        JSONObject item=baselines.optJSONObject(space);
        if(item==null && baselines.has(space))
            throw new java.io.IOException("Malformed local sync checkpoint");
        return item;
    }

    static int checkedManualVersion(JSONObject remote,JSONObject baseline,
            String currentHash,boolean upload) throws java.io.IOException {
        int version=serverVersion(remote);
        if(baseline==null)return version; // Explicit first sync.
        int known=serverVersion(baseline);
        String previous=baseline.optString("local_hash","");
        if(!previous.matches("[0-9a-f]{64}"))
            throw new java.io.IOException("Invalid local sync checkpoint");
        if(version<known)
            throw new java.io.IOException("Cloud vault version rolled back");
        if(upload && version>known)
            throw new java.io.IOException("Cloud vault changed on another device");
        if(!upload && !previous.equals(currentHash))
            throw new java.io.IOException("Local account cards changed; download blocked");
        return version;
    }

    static int checkedUploadVersion(JSONObject ack,int previous)
            throws java.io.IOException {
        int written=serverVersion(ack);
        if(written<=previous)
            throw new java.io.IOException("Cloud upload version did not advance");
        return written;
    }

    static Result reconcile(GlacierCloudSync.State state,String space,
            List<BrowserAccountsStore.Card> local,JSONObject baseline) throws Exception {
        if(!"private".equals(space)&&!"work".equals(space))
            throw new java.io.IOException("Unknown account space");
        if(baseline==null)return new Result(space,"uninitialized",0,"",null);
        int before=baseline.getInt("version");
        String previous=baseline.getString("local_hash");
        if(before < 0 || previous.length()!=64)
            return new Result(space,"uninitialized",0,"",null);
        String current=fingerprint(local,space);
        JSONObject remote=GlacierCloudSync.call(state,"GET","/v1/vault/"+space,null);
        final int remoteVersion;
        try {
            remoteVersion=serverVersion(remote);
        } catch(java.io.IOException error) {
            return new Result(space,"rollback",before,current,null);
        }
        if(versionRollsBack(before,remoteVersion))
            return new Result(space,"rollback",before,current,null);
        boolean changedHere=!current.equals(previous);
        boolean changedThere=remoteVersion!=before;
        if(changedHere&&changedThere)return new Result(space,"conflict",0,current,null);
        if(changedHere) {
            List<BrowserAccountsStore.Card> subset=new ArrayList<>();
            for(BrowserAccountsStore.Card c:local)if(space.equals(c.profile))subset.add(c);
            String encrypted=GlacierCloudSync.encrypt(space,subset,state.autoPassphrase);
            JSONObject body=new JSONObject();
            body.put("expected_version",before);
            body.put("envelope",encrypted);
            JSONObject result=GlacierCloudSync.call(state,"PUT","/v1/vault/"+space,body);
            final int written;
            try {
                written=serverVersion(result);
            } catch(java.io.IOException error) {
                return new Result(space,"rollback",before,current,null);
            }
            if(written <= before)
                return new Result(space,"rollback",before,current,null);
            return new Result(space,"uploaded",written,current,null);
        }
        if(changedThere) {
            if(remote.isNull("envelope"))
                return new Result(space,"conflict",0,current,null);
            List<BrowserAccountsStore.Card> imported=GlacierCloudSync.decrypt(
                    space,remote.getString("envelope"),state.autoPassphrase);
            return new Result(space,"downloaded",remoteVersion,current,imported);
        }
        return new Result(space,"unchanged",before,current,null);
    }
}
