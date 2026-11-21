"""Opt-in FastAPI route adapter for Glacier's isolated bookmark ciphertext store.

INERT unless explicitly mounted. The live VPS must supply its EXISTING
verified session identity dependency; this module never implements a login
or trusts account identifiers supplied by clients. Never share the
/v1/vault/private|work credential-card rows with bookmark ciphertext.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictInt, Field

from glacier_bookmark_cas_store import (
    BookmarkCASStore, BookmarkConflict, BookmarkStoreError,
)


class BookmarkPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: StrictInt = Field(ge=0, le=2147483646)
    envelope: str = Field(min_length=1, max_length=350000)


def create_bookmark_router(store: BookmarkCASStore, verified_session_user):
    """Require caller-supplied, authenticated request-bound session identity.

    verified_session_user must be the existing Glacier session dependency
    which has already validated bearer token, device authorization,
    account identity and revocation status. A raw Authorization header
    or unverified username is NOT an acceptable dependency.
    """
    if not isinstance(store, BookmarkCASStore) or not callable(verified_session_user):
        raise ValueError("Verified session dependency and encrypted bookmark store required")

    router = APIRouter(prefix="/v1/bookmarks", tags=["encrypted-bookmarks"])

    @router.get("/{space}")
    def get_bookmark_space(space: str, authenticated_id=Depends(verified_session_user)):
        try:
            return store.get(authenticated_id, space)
        except BookmarkStoreError:
            raise HTTPException(422, detail="Invalid bookmark account or space")

    @router.put("/{space}")
    def put_bookmark_space(
            space: str,
            request: BookmarkPutRequest,
            authenticated_id=Depends(verified_session_user)):
        try:
            return store.put(authenticated_id, space,
                             request.expected_version, request.envelope)
        except BookmarkConflict:
            raise HTTPException(409, detail="Encrypted bookmarks changed on another device")
        except BookmarkStoreError:
            raise HTTPException(422, detail="Malformed bookmark envelope or space")
    return router
