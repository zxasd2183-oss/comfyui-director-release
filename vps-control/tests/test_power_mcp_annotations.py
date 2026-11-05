"""Contract test: ChatGPT must see request tools as writes, never as reads."""
import asyncio
import unittest

from power_write_mcp import app


class ToolAnnotationsTests(unittest.TestCase):
    def test_write_tools_are_not_mislabeled_read_only(self):
        tools = asyncio.run(app.list_tools())
        by_name = {t.name: t for t in tools}
        self.assertEqual(set(by_name), {
            "request_gpu_start", "request_gpu_stop", "get_power_request_status",
            "get_power_service_health",
            "get_control_center_status", "get_gpu_power_status",
        })
        for name in ("request_gpu_start", "request_gpu_stop"):
            anno = by_name[name].annotations
            self.assertIsNotNone(anno)
            self.assertIs(anno.readOnlyHint, False)
            self.assertIs(anno.destructiveHint, False)
        self.assertIs(by_name["get_power_request_status"].annotations.readOnlyHint,
                      True)
        for name in ("get_power_service_health", "get_control_center_status",
                     "get_gpu_power_status"):
            self.assertIs(by_name[name].annotations.readOnlyHint, True)


if __name__ == "__main__":
    unittest.main()
