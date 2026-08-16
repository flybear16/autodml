"""Exceptions for autodml."""


class AutodmlError(Exception):
    """Base error."""


class ValidationError(AutodmlError):
    """Raised when a manifest fails validation (errors, not warnings)."""

    def __init__(self, issues):
        self.issues = list(issues)
        msg = "\n".join(f"[{i.severity}] {i.rule}: {i.message}" for i in self.issues)
        super().__init__(msg or "validation failed")


class ParseError(AutodmlError):
    """Raised when YAML/JSON input cannot be parsed into a manifest."""
