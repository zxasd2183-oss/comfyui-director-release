import os, unittest
from unittest.mock import patch
from api import config_status, get_instance_status

class Client:
    def __init__(self, cfg):
        self.cfg = cfg
    def ucompshare(self):
        return self
    def invoke(self, action, params):
        assert action == 'DescribeCompShareInstance'
        assert params['UHostIds'] == ['uhost-test123']
        return {'RetCode': 0, 'UHostSet': [{
            'UHostId': 'uhost-test123', 'State': 'Stopped',
            'GpuType': '5090', 'GPU': 1, 'Password':'NEVER_ECHO',
            'FileBrowserPassword':'NEVER_ECHO', 'Region':'cn-wlcb',
        }]}
class Tests(unittest.TestCase):
    def test_unconfigured(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(get_instance_status()['reason'],'not_configured')
            self.assertFalse(config_status()['configured'])
    def test_fields_redacted(self):
        with patch.dict(os.environ,{'COMP_PUBLIC_KEY':'x','COMP_PRIVATE_KEY':'y','COMP_UHOST_ID':'uhost-test123'},clear=True):
            status=get_instance_status(Client)
            self.assertTrue(status['ok'])
            self.assertEqual(status['state'],'Stopped')
            self.assertNotIn('Password',str(status))
            self.assertNotIn('uhost-test123',str(status))
    def test_request_failure_is_sanitized(self):
        def failing_client(_): raise RuntimeError('sensitive internal error')
        with patch.dict(os.environ,{'COMP_PUBLIC_KEY':'x','COMP_PRIVATE_KEY':'y','COMP_UHOST_ID':'uhost-test123'},clear=True):
            self.assertEqual(get_instance_status(failing_client)['reason'],'provider_request_failed')
if __name__=='__main__': unittest.main()
