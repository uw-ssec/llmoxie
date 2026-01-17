"""Exceptions for data extraction operations."""


class ExtractionError(Exception):
    """Base exception for extraction failures."""

    pass


class FileWriteError(ExtractionError):
    """Raised when writing output files fails."""

    pass
