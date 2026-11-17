package cn.borealos.glacier.geckopreview;

import java.util.Locale;

/**
 * Pure presentation state for the compact Android profile avatar.
 * A stored username is not proof of authentication: only a saved session token
 * can make the avatar appear signed in. No credentials enter UI labels or logs.
 */
final class GlacierProfileAvatarState {
    static final int GUEST = 0;
    static final int PENDING = 1;
    static final int APPROVED = 2;
    static final int LOCKED = 3;

    private GlacierProfileAvatarState() {}

    static int mode(GlacierCloudSync.State state, boolean locked) {
        if (locked) return LOCKED;
        if (state == null || state.username == null || state.username.isEmpty()
                || state.token == null || state.token.isEmpty()) return GUEST;
        return state.approved ? APPROVED : PENDING;
    }

    static String initial(GlacierCloudSync.State state) {
        if (state == null || state.username == null || state.username.isEmpty()) return "";
        return new String(Character.toChars(
                state.username.codePointAt(0))).toUpperCase(Locale.ROOT);
    }

    static String accessibilityLabel(int mode) {
        switch (mode) {
            case APPROVED: return "Glacier 账号 · 已登录";
            case PENDING: return "Glacier 账号 · 等待设备授权";
            case LOCKED: return "Glacier 账号 · 本机会话已锁定";
            default: return "Glacier 账号 · 未登录";
        }
    }
}
