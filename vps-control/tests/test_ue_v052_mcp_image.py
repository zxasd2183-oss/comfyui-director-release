"""Contract: existing mcp>=1.29,<2 transports original PNG bytes as ImageContent."""
import base64
import unittest

from mcp.server.fastmcp import Image


class PreviewMCPImageTest(unittest.TestCase):
    def test_encoded_png_is_mcp_image_not_json_or_text(self):
        payload = b"\x89PNG\r\n\x1a\n" + b"image-binary"
        tool_result = Image(data=payload, format="png")
        content = tool_result.to_image_content().model_dump(by_alias=True)
        self.assertEqual(content["type"], "image")
        self.assertEqual(content["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(content["data"]), payload)


if __name__ == "__main__":
    unittest.main()
