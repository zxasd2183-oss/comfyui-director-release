"""Regression safety checks for the Android Chrome-like account avatar."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "glacier-android-gecko/app/src/main/java/cn/borealos/glacier/geckopreview"
MAIN = SRC / "MainActivity.java"
AVATAR = SRC / "GlacierProfileAvatarState.java"
VECTOR = ROOT / "glacier-android-gecko/app/src/main/res/drawable/glacier_profile_silhouette.xml"
TEST = ROOT / "glacier-android-gecko/app/src/androidTest/java/cn/borealos/glacier/geckopreview/GlacierProfileAvatarInstrumentedTest.java"
SMOKE = ROOT / "glacier-android-gecko/scripts/emulator_smoke_v012.py"


class MobileProfileAvatarGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main=MAIN.read_text(encoding="utf-8")
        cls.avatar=AVATAR.read_text(encoding="utf-8")

    def test_no_login_text_button_and_44dp_clickable_avatar(self):
        self.assertNotIn('Button account = button(cloudState.username.isEmpty()',self.main)
        self.assertIn('cloudAvatar = new FrameLayout(this)',self.main)
        self.assertIn('cloudAvatar.setClickable(true)',self.main)
        self.assertIn('cloudAvatar.setFocusable(true)',self.main)
        self.assertIn('new LinearLayout.LayoutParams(dp(44), dp(44))',self.main)
        self.assertIn('cloudAvatar.setOnClickListener(v -> showCloudMenu())',self.main)
        self.assertIn('glacier_profile_silhouette',VECTOR.name)
        self.assertIn('R.drawable.glacier_profile_silhouette',self.main)
        self.assertIn('<vector',VECTOR.read_text(encoding="utf8"))

    def test_ui_state_is_token_driven_not_username_only(self):
        self.assertIn('state.token.isEmpty()',self.avatar)
        self.assertIn('state.username.isEmpty()',self.avatar)
        self.assertIn('state.approved ? APPROVED : PENDING',self.avatar)
        self.assertIn('if (locked) return LOCKED',self.avatar)
        self.assertIn('GlacierProfileAvatarState.mode(cloudState, cloudSessionReadonly)',self.main)
        self.assertIn('GlacierProfileAvatarState.initial(cloudState)',self.main)
        self.assertIn('GlacierProfileAvatarState.accessibilityLabel(state)',self.main)
        self.assertIn('cloudAvatarGuest.setVisibility(signedIn ? View.GONE : View.VISIBLE)',self.main)
        self.assertIn('cloudAvatarInitial.setVisibility(signedIn ? View.VISIBLE : View.GONE)',self.main)
        for label in ('Glacier 账号 · 未登录','Glacier 账号 · 已登录',
                      'Glacier 账号 · 等待设备授权','Glacier 账号 · 本机会话已锁定'):
            self.assertIn(label,self.avatar)

    def test_refresh_after_login_approval_logout_and_initial_render(self):
        self.assertIn('cloudAvatar= new FrameLayout(this)',self.main.replace('cloudAvatar =','cloudAvatar='))
        self.assertIn('toolbar.addView(cloudAvatar, accountParams);\n        refreshCloudAvatar();',self.main)
        self.assertIn('refreshCloudAvatar();\n                if(output==null)return;',self.main)
        self.assertIn('GlacierCloudSync.save(this,next);\n                        cloudEpoch++;\n                        cloudState=next;',self.main)
        self.assertIn('next.approved=true;\n            GlacierCloudSync.save(this,next);',self.main)
        self.assertIn('next.token="";\n            next.approved=false;',self.main)
        self.assertIn('cloudState=next;\n            return "已退出同步账号',self.main)
        self.assertIn('cloudState = GlacierCloudSync.load(this);',self.main)

    def test_signed_in_menu_hides_login_and_keeps_logout(self):
        self.assertIn('String[] actions = signedIn ? new String[]{',self.main)
        self.assertIn('"退出 Glacier 账号"',self.main)
        self.assertIn('"注册 Glacier 账号","登录 / 申请设备授权"',self.main)
        self.assertIn('" · 等待设备授权"',self.main)
        self.assertIn('String action = actions[which]',self.main)

    def test_real_emulator_and_instrumentation_cover_state(self):
        smoke=SMOKE.read_text(encoding='utf-8')
        self.assertIn('await_ui(desc="Glacier 账号 · 未登录"',smoke)
        self.assertIn('tap(desc="Glacier 账号 · 未登录")',smoke)
        src=TEST.read_text(encoding='utf-8')
        for text in ('guestAndRememberedUsernameRemainSignedOut',
                     'pendingAndApprovedSessionsShowTheCorrectAvatar',
                     'damagedEncryptedSessionNeverDisplaysLoggedIn',
                     'labelDoesNotRevealAccountNameOrSecret'):
            self.assertIn(text,src)


if __name__=="__main__":
    unittest.main()
