"""Compatibility import for offline tests and operator packaging.

Runtime Worker uses the signed-owned ue_jobs.py implementation directly.
This file is NOT required in the pinned nine-file Windows update archive.
"""
from ue_jobs import inspect_episode_inputs

__all__ = ["inspect_episode_inputs"]
