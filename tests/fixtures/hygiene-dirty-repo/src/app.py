# noqa: E501
"""Sample app with intentional PII and tracking patterns for hygiene testing."""

# PII patterns
ADMIN_EMAIL = "admin@example.com"
SUPPORT_CONTACT = "support@mycompany.corp"

# Internal org reference
API_BASE = "https://api.internal.corp/v2"

# Tracking IDs
ANALYTICS_ID = "UA-12345-1"
GTM_CONTAINER = "GTM-ABC123"
PIXEL_ID = "fbq('init', '1234567890')"

# TODO remove hardcoded credentials before release
# FIXME error handling is missing for API calls
# HACK working around rate limiter by sleeping
# XXX this breaks when timezone is not UTC
