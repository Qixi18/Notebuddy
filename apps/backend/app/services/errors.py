"""Framework independent errors raised by application services."""


class ApplicationError(Exception):
    """Base class for expected application failures."""

    status_code = 400

    def __init__(self, status_code: int, detail: object):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class ResourceNotFoundError(ApplicationError):
    status_code = 404


class ResourceConflictError(ApplicationError):
    status_code = 409


class InvalidOperationError(ApplicationError):
    status_code = 422
