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

    static Result reconcile(GlacierCloudSync.State state,String space,
            List<BrowserAccountsStore.Card> local,JSONObject baseline) throws Exception {
        if(!"private".equals(space)&&!"work".equals(space))
            throw new java.io.IOException("Unknown account space");
        if(baseline==null)return new Result(space,"uninitialized",0,"",null);
        int before=baseline.getInt("version");
        String previous=baseline.getString("local_hash");
        if(previous.length()!=64)return new Result(space,"uninitialized",0,"",null);
        String current=fingerprint(local,space);
        JSONObject remote=GlacierCloudSync.call(state,"GET","/v1/vault/"+space,null);
        int remoteVersion=remote.getInt("version");
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
            return new Result(space,"uploaded",result.getInt("version"),current,null);
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
