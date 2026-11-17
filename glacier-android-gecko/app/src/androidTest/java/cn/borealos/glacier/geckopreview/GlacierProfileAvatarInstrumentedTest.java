package cn.borealos.glacier.geckopreview;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

import static org.junit.Assert.*;

/** Avatar never leaks a session token, confuses remembered account with login,
 * or misrepresents a pending authorization as an approved device. */
@RunWith(AndroidJUnit4.class)
public final class GlacierProfileAvatarInstrumentedTest {
    @Test
    public void guestAndRememberedUsernameRemainSignedOut() {
        GlacierCloudSync.State s=new GlacierCloudSync.State();
        assertEquals(GlacierProfileAvatarState.GUEST,
                GlacierProfileAvatarState.mode(s,false));
        s.username="exampleAccount";
        s.approved=true;
        assertEquals(GlacierProfileAvatarState.GUEST,
                GlacierProfileAvatarState.mode(s,false));
        assertEquals("Glacier 账号 · 未登录",
                GlacierProfileAvatarState.accessibilityLabel(
                        GlacierProfileAvatarState.mode(s,false)));
    }

    @Test
    public void pendingAndApprovedSessionsShowTheCorrectAvatar() {
        GlacierCloudSync.State s=new GlacierCloudSync.State();
        s.username="Alice";s.token="synthetic-not-a-real-token";
        assertEquals(GlacierProfileAvatarState.PENDING,
                GlacierProfileAvatarState.mode(s,false));
        assertEquals("Glacier 账号 · 等待设备授权",
                GlacierProfileAvatarState.accessibilityLabel(
                        GlacierProfileAvatarState.mode(s,false)));
        s.approved=true;
        assertEquals(GlacierProfileAvatarState.APPROVED,
                GlacierProfileAvatarState.mode(s,false));
        assertEquals("A",GlacierProfileAvatarState.initial(s));
        assertEquals("Glacier 账号 · 已登录",
                GlacierProfileAvatarState.accessibilityLabel(
                        GlacierProfileAvatarState.mode(s,false)));
    }

    @Test
    public void damagedEncryptedSessionNeverDisplaysLoggedIn() {
        GlacierCloudSync.State s=new GlacierCloudSync.State();
        s.username="Alice";s.token="synthetic-not-a-real-token";s.approved=true;
        assertEquals(GlacierProfileAvatarState.LOCKED,
                GlacierProfileAvatarState.mode(s,true));
        assertEquals("Glacier 账号 · 本机会话已锁定",
                GlacierProfileAvatarState.accessibilityLabel(
                        GlacierProfileAvatarState.mode(s,true)));
    }

    @Test
    public void labelDoesNotRevealAccountNameOrSecret() {
        GlacierCloudSync.State s=new GlacierCloudSync.State();
        s.username="distinct-account-id";s.token="do-not-reveal-token";s.approved=true;
        String label=GlacierProfileAvatarState.accessibilityLabel(
                GlacierProfileAvatarState.mode(s,false));
        assertFalse(label.contains(s.username));
        assertFalse(label.contains(s.token));
        assertFalse(label.contains("登录 Glacier"));
        assertEquals("D",GlacierProfileAvatarState.initial(s));
    }
}
