class ApiError(Exception):
    """Raised when the backend responds with a non-2xx status.

    Wraps the {"detail": ..., "code": ...} error body FastAPI returns.
    """

    def __init__(self, detail: str, code: str, status_code: int):
        self.detail = detail
        self.code = code
        self.status_code = status_code
        super().__init__(detail)


class NetworkError(Exception):
    """Raised when the request never received an HTTP response
    (connection refused, timeout, DNS failure, etc).
    """
    pass
