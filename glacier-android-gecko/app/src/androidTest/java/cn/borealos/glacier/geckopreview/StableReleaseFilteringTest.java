package cn.borealos.glacier.geckopreview;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

/** Android-only updater regression: stable releases may be offered, previews may not. */
public final class StableReleaseFilteringTest {
    private static JSONObject release(String version, boolean prerelease, boolean draft)
            throws Exception {
        String tag = "glacier-android-browser-v" + version;
        String file = "GlacierAndroid-v" + version + "-ARM64-x86_64-release.apk";
        String url = "https://github.com/zxasd2183-oss/comfyui-director-release"
                + "/releases/download/" + tag + "/" + file;
        JSONObject asset = new JSONObject()
                .put("name", file)
                .put("state", "uploaded")
                .put("browser_download_url", url)
                .put("digest", "sha256:" + new String(new char[64]).replace('\0', 'a'))
                .put("size", 20000000L);
        return new JSONObject()
                .put("tag_name", tag)
                .put("prerelease", prerelease)
                .put("draft", draft)
                .put("assets", new JSONArray().put(asset));
    }

    @Test
    public void stableReleaseWinsOverHigherPreviewAndDraft() throws Exception {
        JSONArray list = new JSONArray()
                .put(release("0.2.5", false, true))
                .put(release("0.2.4", true, false))
                .put(release("0.2.3", false, false));
        BrowserUpdater.Release found = BrowserUpdater.findLatest(list.toString(), "0.2.1");
        assertNotNull(found);
        assertEquals("0.2.3", found.version);
    }

    @Test
    public void previewOnlyFeedDoesNotOfferUpdate() throws Exception {
        JSONArray list = new JSONArray()
                .put(release("0.2.4", true, false))
                .put(release("0.2.5", false, true));
        assertNull(BrowserUpdater.findLatest(list.toString(), "0.2.1"));
    }
}
