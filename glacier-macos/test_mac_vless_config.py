"""Regression checks for VLESS link transport options omitted by old Mac builds."""
import unittest
import uuid

from main import parse_node, build_proxy_config

BASE = "vless://" + str(uuid.UUID(int=1)) + "@example.com:443?encryption=none&security=tls"

class MacVlessTransportTests(unittest.TestCase):
    def test_reality_without_explicit_fp_uses_chrome_clienthello(self):
        link=BASE.replace("security=tls","security=reality")
        link+="&pbk="+("A"*43)+"&sid=01ab"
        config=parse_node(link)
        self.assertEqual(config["tls"]["utls"],{"enabled":True,"fingerprint":"chrome"})
        self.assertTrue(config["tls"]["reality"]["enabled"])
        self.assertEqual(config["tls"]["reality"]["short_id"],"01ab")

    def test_reality_explicit_fp_preserved(self):
        link=BASE.replace("security=tls","security=reality")
        link+="&pbk="+("A"*43)+"&sid=01ab&fp=firefox"
        self.assertEqual(parse_node(link)["tls"]["utls"]["fingerprint"],"firefox")

    def test_modern_singbox_has_explicit_local_resolver_for_node_only(self):
        cfg=build_proxy_config(BASE,19010)
        self.assertEqual(cfg["dns"],{
            "servers":[{"type":"local","tag":"system-local"}],"final":"system-local"
        })
        self.assertEqual(cfg["route"]["default_domain_resolver"],"system-local")
        self.assertEqual(cfg["route"]["final"],"node")
        self.assertEqual(cfg["inbounds"][0]["listen"],"127.0.0.1")
        self.assertEqual(cfg["outbounds"][0]["server"],"example.com")

    def test_websocket_early_data_kept(self):
        result=parse_node(BASE+"&type=ws&path=%2Fws&host=cdn.example.com&ed=2048")
        self.assertEqual(result["transport"],{
            "type":"ws", "path":"/ws", "headers":{"Host":"cdn.example.com"},
            "max_early_data":2048, "early_data_header_name":"Sec-WebSocket-Protocol"
        })

    def test_websocket_early_data_header(self):
        result=parse_node(BASE+"&type=ws&ed=1024&eh=Early-Data")
        self.assertEqual(result["transport"]["early_data_header_name"],"Early-Data")

    def test_httpupgrade(self):
        result=parse_node(BASE+"&type=httpupgrade&path=%2Fupgrade&host=cdn.example.com")
        self.assertEqual(result["transport"],{
            "type":"httpupgrade", "path":"/upgrade", "host":"cdn.example.com"
        })

    def test_grpc_service_alias(self):
        result=parse_node(BASE+"&type=grpc&service_name=myservice")
        self.assertEqual(result["transport"]["service_name"],"myservice")

    def test_unsupported_transport_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_node(BASE+"&type=unknown")

    def test_rejects_disabled_tls_verification(self):
        with self.assertRaises(ValueError):
            parse_node(BASE+"&allowInsecure=1")

    def test_rejects_oversized_early_data(self):
        with self.assertRaises(ValueError):
            parse_node(BASE+"&type=ws&ed=999999999")

if __name__=="__main__":
    unittest.main()
