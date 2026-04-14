# OIDC authentication stub — full implementation pending.
# This module will integrate with authlib to provide OpenID Connect login.

from fastapi import APIRouter

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])
