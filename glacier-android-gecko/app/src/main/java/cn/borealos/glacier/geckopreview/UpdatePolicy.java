package cn.borealos.glacier.geckopreview;

import java.net.URI;
import java.util.Locale;

/**
 * Glacier Android update release allowlist and version checks.
 * URL and release naming are pinned to the owner's GitHub repository.
 */
public final class UpdatePolicy {
    public static final String OWNER_REPO="zxasd2183-oss/comfyui-director-release";
    public static final String PREFIX="glacier-android-gecko-network-v";
    public static final String API="https://api.github.com/repos/"+OWNER_REPO+"/releases?per_page=30";
    public static final long MAX_APK_BYTES=600L*1024L*1024L;
    public static final long MIN_APK_BYTES=10L*1024L*1024L;
    private UpdatePolicy() {}

    public static int[] parseVersion(String value) {
        if(value==null || !value.matches("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)"))
            return null;
        String[] pieces=value.split("\\.");
        try {
            int[] v=new int[3];
            for(int i=0;i<3;i++) v[i]=Integer.parseInt(pieces[i]);
            return v;
        }catch(NumberFormatException exception){
            return null;
        }
    }

    public static boolean newer(String incoming,String installed) {
        int[] a=parseVersion(incoming),b=parseVersion(installed);
        if(a==null||b==null)return false;
        for(int i=0;i<3;i++){
            if(a[i]>b[i])return true;
            if(a[i]<b[i])return false;
        }
        return false;
    }

    public static String tagVersion(String tag) {
        if(tag==null||!tag.startsWith(PREFIX))return null;
        String version=tag.substring(PREFIX.length());
        return parseVersion(version)==null?null:version;
    }

    public static String assetName(String version) {
        if(parseVersion(version)==null)return null;
        return "GlacierAndroid-v"+version+"-GeckoView-VLESS-ARM64-x86_64.apk";
    }

    public static boolean allowedDownloadUrl(String value) {
        if(value==null||value.length()>2048)return false;
        try {
            URI url=new URI(value);
            if(!"https".equalsIgnoreCase(url.getScheme()) || url.getHost()==null
                    || url.getRawUserInfo()!=null || url.getPort()!=-1
                    || url.getRawFragment()!=null)return false;
            if(!"github.com".equalsIgnoreCase(url.getHost()))return false;
            String prefix="/"+OWNER_REPO+"/releases/download/";
            if(!url.getRawPath().startsWith(prefix) || url.getRawQuery()!=null)return false;
            String rest=url.getRawPath().substring(prefix.length());
            int slash=rest.indexOf('/');
            if(slash<0)return false;
            String version=tagVersion(rest.substring(0,slash));
            return version!=null && assetName(version).equals(rest.substring(slash+1));
        }catch(Exception e){return false;}
    }

    public static boolean allowedHttpsHop(String value) {
        if(value==null||value.length()>4096)return false;
        try{
            URI u=new URI(value);
            if(!"https".equalsIgnoreCase(u.getScheme())||u.getHost()==null
                    ||u.getRawUserInfo()!=null||u.getPort()!=-1)return false;
            String host=u.getHost().toLowerCase(Locale.ROOT);
            return host.equals("api.github.com")||host.equals("github.com")
                    ||host.equals("release-assets.githubusercontent.com")
                    ||host.equals("objects.githubusercontent.com");
        }catch(Exception e){return false;}
    }

    public static boolean sha256(String hash) {
        return hash!=null&&hash.matches("[0-9a-f]{64}");
    }

    public static boolean saneAsset(long bytes,String hash) {
        return bytes>=MIN_APK_BYTES&&bytes<=MAX_APK_BYTES&&sha256(hash);
    }
}
