"""
Custom exception hierarchy for the application.
"""


class EtsyAutomationError(Exception):
    """Base exception for all application errors."""


class ValidationError(EtsyAutomationError):
    """Raised when a business rule validator fails."""


class ConfigurationError(EtsyAutomationError):
    """Raised when required configuration is missing or invalid."""


class EtsyAPIError(EtsyAutomationError):
    """Raised when the Etsy API returns an error."""


class EtsyPartialListingError(EtsyAPIError):
    """A draft listing was created on Etsy but a later publish step failed.

    Carries the orphaned draft's listing_id so the caller can record it
    instead of losing track of it — the draft still exists on Etsy (and
    counts against the daily listing quota) even though our own pipeline
    never reached activate_listing for it.
    """

    def __init__(self, listing_id: str, message: str) -> None:
        super().__init__(message)
        self.listing_id = listing_id


class ImagePipelineError(EtsyAutomationError):
    """Raised when the AI image pipeline fails."""


class ContentGenerationError(EtsyAutomationError):
    """Raised when the LLM content pipeline fails."""
