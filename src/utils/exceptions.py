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


class ImagePipelineError(EtsyAutomationError):
    """Raised when the AI image pipeline fails."""


class ContentGenerationError(EtsyAutomationError):
    """Raised when the LLM content pipeline fails."""
