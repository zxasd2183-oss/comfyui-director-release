package cn.borealos.glacier.geckopreview;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

import static org.junit.Assert.*;

/** No network access, cookies or production credentials required. */
@RunWith(AndroidJUnit4.class)
public final class GlacierSyncVersionInstrumentedTest {
    @Test
    public void cloudVersionCanMoveForwardButNeverBackwards() {
        assertFalse(GlacierAutoSync.versionRollsBack(0, 0));
        assertFalse(GlacierAutoSync.versionRollsBack(5, 5));
        assertFalse(GlacierAutoSync.versionRollsBack(5, 6));
        assertTrue(GlacierAutoSync.versionRollsBack(5, 4));
        assertTrue(GlacierAutoSync.versionRollsBack(5, -1));
        assertTrue(GlacierAutoSync.versionRollsBack(-1, 5));
        assertTrue(GlacierAutoSync.versionRollsBack(5, ((long)Integer.MAX_VALUE)+1));
    }

    @Test
    public void malformedCloudResponseIsRejected() throws Exception {
        for (Object value : new Object[]{-1, "6", true, 1.5, ((long)Integer.MAX_VALUE)+1}) {
            JSONObject payload=new JSONObject().put("version", value);
            try {
                GlacierAutoSync.serverVersion(payload);
                fail("must reject invalid cloud version: "+value);
            } catch(java.io.IOException expected) {}
        }
        try {
            GlacierAutoSync.serverVersion(new JSONObject());
            fail("must reject missing cloud version");
        } catch(java.io.IOException expected) {}
        assertEquals(6, GlacierAutoSync.serverVersion(
                new JSONObject().put("version", 6)));
        assertEquals(6, GlacierAutoSync.serverVersion(
                new JSONObject().put("version", 6L)));
    }
}
