from __future__ import annotations


class ProspectDiscoveryError(Exception):
    """Base error with a stable client-facing code."""

    code = "DISCOVERY_ERROR"
    status_code = 500
    message = "Prospect discovery could not be completed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.client_message = message or self.message


class QueryUnderstandingError(ProspectDiscoveryError):
    code = "QUERY_UNDERSTANDING_FAILED"
    status_code = 422
    message = "The query could not be understood. Try a clearer search."


class SearchUnavailableError(ProspectDiscoveryError):
    code = "SEARCH_UNAVAILABLE"
    status_code = 503
    message = "Discovery sources are temporarily unavailable."


class LLMConfigurationError(ProspectDiscoveryError):
    code = "LLM_NOT_CONFIGURED"
    status_code = 503
    message = "The language model is not configured."


class LLMResponseError(ProspectDiscoveryError):
    code = "LLM_INVALID_RESPONSE"
    status_code = 502
    message = "The language model returned an invalid response."


class UnsafeURLError(ProspectDiscoveryError):
    code = "UNSAFE_URL"
    status_code = 400
    message = "A discovered URL was rejected by the safety checks."


class InvalidQueryError(ProspectDiscoveryError):
    code = "INVALID_QUERY"
    status_code = 422
    message = "Query must contain at least 3 characters."
