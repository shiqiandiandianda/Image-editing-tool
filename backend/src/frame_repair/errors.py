class BackendError(Exception):
    """Base error with a stable machine-readable code."""
    code = "BACKEND_ERROR"


class ValidationError(BackendError):
    code = "VALIDATION_ERROR"


class ConflictError(BackendError):
    code = "VERSION_CONFLICT"


class IdempotencyConflict(BackendError):
    code = "IDEMPOTENCY_CONFLICT"


class PersistenceConflict(BackendError):
    """A durable row would be overwritten by a different value."""
    code = "PERSISTENCE_CONFLICT"


class AdapterUnavailable(BackendError):
    code = "CODEX_NOT_READY"


class CodexCliError(BackendError):
    """Base error raised when the Codex CLI adapter cannot produce an artifact."""

    code = "CODEX_CLI_ERROR"


class CodexCliNotFound(CodexCliError):
    code = "CODEX_CLI_NOT_FOUND"


class CodexCliTimeout(CodexCliError):
    code = "CODEX_CLI_TIMEOUT"


class CodexCliFailed(CodexCliError):
    code = "CODEX_CLI_FAILED"


class CodexCliArtifactMissing(CodexCliError):
    code = "CODEX_ARTIFACT_MISSING"


class CodexCliArtifactAmbiguous(CodexCliError):
    code = "CODEX_ARTIFACT_AMBIGUOUS"


class CodexCliArtifactInvalid(CodexCliError):
    code = "CODEX_ARTIFACT_INVALID"


class CodexCliUnreachable(CodexCliError):
    code = "CODEX_UNREACHABLE"


class ArtifactError(BackendError):
    code = "INVALID_IMAGE"
