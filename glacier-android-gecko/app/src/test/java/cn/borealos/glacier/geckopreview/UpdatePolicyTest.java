package cn.borealos.glacier.geckopreview;

import org.junit.Test;
import static org.junit.Assert.*;

public final class UpdatePolicyTest {
    @Test public void acceptsKnownTagAndStrictVersion() {
        assertEquals("0.1.3",UpdatePolicy.tagVersion("glacier-android-gecko-network-v0.1.3"));
        assertNull(UpdatePolicy.tagVersion("glacier-android-gecko-debug-v0.1.3"));
        assertNull(UpdatePolicy.tagVersion("glacier-android-gecko-network-v0.1.3-extra"));
    }
    @Test public void rejectsRollbackAndNoOp() {
        assertTrue(UpdatePolicy.newer("0.1.4","0.1.3"));
        assertTrue(UpdatePolicy.newer("1.0.0","0.99.99"));
        assertFalse(UpdatePolicy.newer("0.1.2","0.1.3"));
        assertFalse(UpdatePolicy.newer("0.1.3","0.1.3"));
        assertFalse(UpdatePolicy.newer("0.1.3-rc1","0.1.2"));
    }
    @Test public void releaseUrlIsExact() {
        String url="https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/"
            +"glacier-android-gecko-network-v0.1.4/"
            +"GlacierAndroid-v0.1.4-GeckoView-VLESS-ARM64-x86_64.apk";
        assertTrue(UpdatePolicy.allowedDownloadUrl(url));
        assertFalse(UpdatePolicy.allowedDownloadUrl(url.replace("github.com","evil.example.com")));
        assertFalse(UpdatePolicy.allowedDownloadUrl(url.replace("https://","http://")));
        assertFalse(UpdatePolicy.allowedDownloadUrl(url+"?token=wrong"));
        assertFalse(UpdatePolicy.allowedDownloadUrl(url.replace("network-v0.1.4","network-v0.1.5")));
    }
    @Test public void redirectsNeverAllowUntrustedOrHttp() {
        assertTrue(UpdatePolicy.allowedHttpsHop("https://api.github.com/repos/test"));
        assertTrue(UpdatePolicy.allowedHttpsHop("https://release-assets.githubusercontent.com/object"));
        assertFalse(UpdatePolicy.allowedHttpsHop("http://github.com/"));
        assertFalse(UpdatePolicy.allowedHttpsHop("https://attacker.github.com/"));
        assertFalse(UpdatePolicy.allowedHttpsHop("https://github.com.evil.org/file"));
        assertFalse(UpdatePolicy.allowedHttpsHop("https://alice:pw@github.com/"));
    }
    @Test public void validHashAndSizeOnly() {
        String sha="a".repeat(64);
        assertTrue(UpdatePolicy.saneAsset(210000000L,sha));
        assertFalse(UpdatePolicy.saneAsset(210000000L,"a".repeat(63)));
        assertFalse(UpdatePolicy.saneAsset(1024L,sha));
        assertFalse(UpdatePolicy.saneAsset(1000000000L,sha));
    }
}
