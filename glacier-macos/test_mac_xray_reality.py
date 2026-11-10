"""REALITY routing must use bundled Xray-core, preserving security and node options."""
import base64
import unittest
import uuid
from unittest.mock import patch
from pathlib import Path

from main import parse_node, select_proxy_core
from mac_xray_reality import build_xray_reality_config

UUID=str(uuid.UUID(int=1))
PUB=base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")
BASE=(f"vless://{UUID}@example.org:443?"
      f"encryption=none&security=reality&type=tcp&sni=www.example.org"
      f"&fp=chrome&pbk={PUB}&sid=1a2b&flow=xtls-rprx-vision")


class XrayRealityConfigTests(unittest.TestCase):
    def test_reality_uses_official_xray_and_preserves_handshake_fields(self):
        with patch("main.xray_core_path",return_value=Path("/safe/bin/xray")),patch(
             "main.core_path",side_effect=AssertionError("REALITY must not use sing-box")):
            core,config,engine=select_proxy_core(BASE,19010)
        self.assertEqual(engine,"xray")
        self.assertEqual(str(core),"/safe/bin/xray")
        self.assertEqual(config["inbounds"][0]["listen"],"127.0.0.1")
        self.assertEqual(config["inbounds"][0]["protocol"],"socks")
        self.assertFalse(config["inbounds"][0]["settings"]["udp"])
        outbound=config["outbounds"][0]
        self.assertEqual(outbound["protocol"],"vless")
        self.assertEqual(outbound["settings"]["vnext"][0]["users"][0]["flow"],"xtls-rprx-vision")
        stream=outbound["streamSettings"]
        self.assertEqual(stream["security"],"reality")
        self.assertEqual(stream["network"],"tcp")
        self.assertEqual(stream["realitySettings"],{
            "serverName":"www.example.org","fingerprint":"chrome",
            "password":PUB,"shortId":"1a2b"
        })
        self.assertEqual(config["routing"]["domainStrategy"],"AsIs")
        self.assertNotIn("freedom",str(config))

    def test_nonreality_stays_with_original_singbox(self):
        with patch("main.core_path",return_value=Path("/safe/bin/sing-box")),patch(
             "main.xray_core_path",side_effect=AssertionError("TLS should use sing-box")):
            core,config,engine=select_proxy_core(BASE.replace("security=reality","security=tls"),19010)
        self.assertEqual(engine,"sing-box")
        self.assertEqual(config["outbounds"][0]["type"],"vless")
        self.assertEqual(str(core),"/safe/bin/sing-box")

    def test_default_chrome_fingerprint_when_missing(self):
        node=parse_node(BASE.replace("&fp=chrome",""))
        config=build_xray_reality_config(node,19010)
        self.assertEqual(config["outbounds"][0]["streamSettings"]["realitySettings"]["fingerprint"],"chrome")

    def test_invalid_shortid_rejected_before_core_launch(self):
        node=parse_node(BASE.replace("sid=1a2b","sid=abc"))
        with self.assertRaisesRegex(ValueError,"shortId"):
            build_xray_reality_config(node,19010)

    def test_early_data_not_silently_dropped(self):
        node=parse_node(BASE.replace("type=tcp","type=ws&ed=1024"))
        with self.assertRaisesRegex(ValueError,"Early Data"):
            build_xray_reality_config(node,19010)

    def test_missing_core_fails_closed(self):
        with patch("main.xray_core_path",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"Xray"):
                select_proxy_core(BASE,19010)


if __name__=="__main__":
    unittest.main()
