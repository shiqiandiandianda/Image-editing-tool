class BackendError(Exception):
    """Base error with a stable machine-readable code."""
    code = "BACKEND_ERROR"


class ValidationError(BackendError):
    code = "VALIDATION_ERROR"


class ConflictError(BackendError):
    code = "VERSION_CONFLICT"


class IdempotencyConflict(BackendError):
    code = "IDEMPOTENCY_CONFLICT"


class AdapterUnavailable(BackendError):
    code = "CODEX_NOT_READY"


class ArtifactError(BackendError):
    code = "INVALID_IMAGE"
