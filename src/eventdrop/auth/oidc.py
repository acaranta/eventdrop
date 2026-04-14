from eventdrop.config import settings

oauth = None


def get_oauth():
    global oauth
    if oauth is None and settings.is_oidc_configured():
        from authlib.integrations.starlette_client import OAuth
        oauth = OAuth()
        oauth.register(
            name="oidc",
            server_metadata_url=f"{settings.oidc_provider_url}/.well-known/openid-configuration",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth
