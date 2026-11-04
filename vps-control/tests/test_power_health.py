"""Safe diagnostic contract: only classified messages and required key names."""
import unittest
from unittest.mock import patch
from power_ops import PowerError
from power_write_mcp import get_power_service_health


class HealthTests(unittest.TestCase):
    def classify(self, message):
        with patch("power_write_mcp._config", side_effect=PowerError(message)):
            return get_power_service_health()

    def test_secret_values_never_returned(self):
        result=self.classify("Power configuration incomplete: COMP_PRIVATE_KEY, COMP_ZONE")
        self.assertEqual(result["reason"], "credential_required_fields_missing")
        self.assertEqual(result["missing_field_names"],
                         ["COMP_PRIVATE_KEY","COMP_ZONE"])
        self.assertNotIn("private-value",str(result))

    def test_invalid_mode(self):
        result=self.classify("Credential file permissions must be 0600")
        self.assertEqual(result["reason"],"credential_file_permissions_too_open")
        self.assertNotIn("missing_field_names",result)

    def test_unexpected_error_text_is_redacted(self):
        result=self.classify("private api key is secret")
        self.assertEqual(result["reason"],"credential_file_invalid_or_incomplete")
        self.assertNotIn("secret",str(result))

    def test_region_zone_errors_are_distinct(self):
        self.assertEqual(self.classify("Invalid region")["reason"],"credential_region_invalid")
        self.assertEqual(self.classify("Invalid zone")["reason"],"credential_zone_invalid")


if __name__=="__main__":
    unittest.main()
