"""Custom exception classes for Maha Bhulekh automation."""

class PortalException(Exception):
    """Base exception for all portal errors."""
    pass

class PortalLayoutChanged(PortalException):
    """Raised when an expected DOM control or selector is missing or altered."""
    pass

class DiscoveryError(PortalException):
    """Raised when survey discovery fails or encounters an unrecoverable state."""
    pass

class NetworkTimeout(PortalException):
    """Raised when network requests to Bhulekh portal time out."""
    pass

class SessionExpired(PortalException):
    """Raised when browser session/cookies expire."""
    pass

class CaptchaRequired(PortalException):
    """Raised when CAPTCHA input is requested by the portal."""
    pass

class CaptchaInvalid(PortalException):
    """Raised when human-entered CAPTCHA is rejected by portal."""
    pass
