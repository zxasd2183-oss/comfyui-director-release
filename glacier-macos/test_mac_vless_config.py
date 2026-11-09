"""Regression checks for VLESS link transport options omitted by old Mac builds."""
import unittest
import uuid

from main import parse_node

BASE = "vless://" + str(uuid.UUID(int=1)) + "@example.com:443?encryption=none&security=tls"

class MacVlessTransportTests(unittest.TestCase):
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
