"""MCP tool must expose the official ChatGPT file parameter descriptor."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hub_app


class TestStudioFileParamTool(unittest.TestCase):
    def test_file_input_metadata_and_required_fields(self):
        items=asyncio.run(hub_app.app.list_tools())
        matches=[x for x in items if x.name in {
            "sync_chatgpt_visual_to_studio","enqueue_chatgpt_visual_to_studio"}]
        self.assertEqual(len(matches),2)
        for tool in matches:
            with self.subTest(tool=tool.name):
                self.assertEqual(tool.meta.get("openai/fileParams"),["file"])
                schema=tool.inputSchema
                file_param=schema["properties"]["file"]
                if "$ref" in file_param:
                    ref=file_param["$ref"]
                    self.assertTrue(ref.startswith("#/$defs/"))
                    file_param=schema["$defs"][ref.split("/")[-1]]
                self.assertEqual({"download_url","file_id"},
                                 set(file_param["required"]))
                self.assertTrue({"download_url","file_id","mime_type","file_name"}
                                <=set(file_param["properties"]))
        names={x.name for x in items}
        self.assertIn("get_chatgpt_visual_sync_status",names)
        self.assertIn("list_recent_chatgpt_visual_syncs",names)

if __name__=="__main__":
    unittest.main()
