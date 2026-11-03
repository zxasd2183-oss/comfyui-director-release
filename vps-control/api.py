"""Read-only adapter for CompShare GPU instance status.

No secrets or complete provider response are ever returned from the MCP tool.
"""
from __future__ import annotations
import os
from typing import Callable


def config_status() -> dict:
    keys = ('COMP_PUBLIC_KEY', 'COMP_PRIVATE_KEY', 'COMP_UHOST_ID')
    return {
        'version': '0.1.0',
        'configured': all(os.getenv(k) for k in keys),
        'instance_selected': bool(os.getenv('COMP_UHOST_ID')),
        'gpu_control_enabled': False,
        'mode': 'read_only',
    }


def get_instance_status(client_factory: Callable | None = None) -> dict:
    public = os.getenv('COMP_PUBLIC_KEY', '')
    private = os.getenv('COMP_PRIVATE_KEY', '')
    instance = os.getenv('COMP_UHOST_ID', '')
    region = os.getenv('COMP_REGION', 'cn-wlcb')
    zone = os.getenv('COMP_ZONE', '')
    if not (public and private and instance):
        return {'ok': False, 'reason': 'not_configured', 'mode': 'read_only'}

    if client_factory is None:
        try:
            from ucloud.client import Client
        except ImportError:
            return {'ok': False, 'reason': 'sdk_not_installed'}
        client_factory = Client
    try:
        client = client_factory({
            'region': region,
            'public_key': public,
            'private_key': private,
            'base_url': 'https://api.compshare.cn',
        })
        params = {'Region': region, 'UHostIds': [instance]}
        if zone:
            params['Zone'] = zone
        response = client.ucompshare().invoke('DescribeCompShareInstance', params)
    except Exception:
        # Never echo raw SDK/network exceptions; they may contain request details.
        return {'ok': False, 'reason': 'provider_request_failed'}

    if not isinstance(response, dict) or response.get('RetCode') != 0:
        return {'ok': False, 'reason': 'provider_returned_error'}
    instances = response.get('UHostSet') or []
    info = next((item for item in instances if item.get('UHostId') == instance), None)
    if not info:
        return {'ok': False, 'reason': 'instance_not_found'}
    # Explicit allowlist: provider's full response may include passwords and tokens.
    return {
        'ok': True,
        'state': info.get('State', 'Unknown'),
        'region': info.get('Region', region),
        'zone': info.get('Zone', zone),
        'gpu_type': info.get('GpuType'),
        'gpu_count': info.get('GPU'),
        'charge_type': info.get('ChargeType'),
        'is_spot': info.get('IsSpot'),
        'mode': 'read_only',
    }
