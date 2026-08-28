"""Authentication layer.

All admin routes depend on `admin_auth`. The mechanism lives in `app.security`;
swap the implementation there (e.g. for OAuth2/JWT) without touching route
definitions. Routes simply declare `dependencies=[admin_auth]`.
"""
from fastapi import Depends

from app.security import verify_admin_api_key

admin_auth = Depends(verify_admin_api_key)
