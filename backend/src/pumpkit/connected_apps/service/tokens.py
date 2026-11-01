from datetime import timedelta

# The one scope Pumpkit grants (ADR 0020): an app may use every tool the User can.
SCOPE = "pumpkit"

ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
REFRESH_TOKEN_LIFETIME = timedelta(days=90)
# A refresh token rotated this recently may be presented again, for a retry after a lost response.
REFRESH_REUSE_GRACE = timedelta(minutes=2)
CODE_LIFETIME = timedelta(minutes=2)
AUTHORIZATION_REQUEST_LIFETIME = timedelta(minutes=30)
