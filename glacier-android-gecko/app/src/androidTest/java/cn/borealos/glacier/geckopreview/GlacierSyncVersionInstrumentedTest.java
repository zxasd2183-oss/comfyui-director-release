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

    @Test
    public void manualSyncRejectsOldCloudAndDirtyLocalData() throws Exception {
        JSONObject baseline=new JSONObject()
                .put("version",5)
                .put("local_hash","a".repeat(64));
        JSONObject old=new JSONObject().put("version",4);
        for(boolean upload:new boolean[]{true,false}) {
            try {
                GlacierAutoSync.checkedManualVersion(old,baseline,
                        "a".repeat(64),upload);
                fail("stale cloud must not overwrite either direction");
            } catch(java.io.IOException expected) {}
        }
        try {
            GlacierAutoSync.checkedManualVersion(
                    new JSONObject().put("version",6),baseline,
                    "a".repeat(64),true);
            fail("newer cloud must not be replaced by a stale manual upload");
        } catch(java.io.IOException expected) {}
        try {
            GlacierAutoSync.checkedManualVersion(
                    new JSONObject().put("version",6),baseline,
                    "b".repeat(64),false);
            fail("dirty local account cards must not be discarded");
        } catch(java.io.IOException expected) {}
        assertEquals(6,GlacierAutoSync.checkedManualVersion(
                new JSONObject().put("version",6),baseline,
                "a".repeat(64),false));
        assertEquals(0,GlacierAutoSync.checkedManualVersion(
                new JSONObject().put("version",0),null,
                "a".repeat(64),true));
    }

    @Test
    public void manualAckAndCheckpointMustBeWellFormed() throws Exception {
        JSONObject baseline=new JSONObject()
                .put("version",5).put("local_hash","bad");
        try {
            GlacierAutoSync.checkedManualVersion(
                    new JSONObject().put("version",5),baseline,
                    "a".repeat(64),false);
            fail("malformed checkpoint must be rejected");
        } catch(java.io.IOException expected) {}
        for(Object v:new Object[]{5,4,"6",true}) {
            try {
                GlacierAutoSync.checkedUploadVersion(
                        new JSONObject().put("version",v),5);
                fail("bad upload acknowledgement");
            } catch(java.io.IOException expected) {}
        }
        assertEquals(6,GlacierAutoSync.checkedUploadVersion(
                new JSONObject().put("version",6),5));
        try {
            GlacierAutoSync.baselineForSpace(
                    new JSONObject().put("private","bad"),"private");
            fail("malformed stored checkpoint must not become first sync");
        } catch(java.io.IOException expected) {}
    }

}
