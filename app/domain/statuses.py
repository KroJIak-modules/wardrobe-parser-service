from enum import Enum


class SourceStatus(str, Enum):
    ACTIVE = 'active'
    DISABLED = 'disabled'
    ERROR = 'error'
    AUTH_REQUIRED = 'auth_required'


class SourceRunStatus(str, Enum):
    QUEUED = 'queued'
    RUNNING = 'running'
    SUCCESS = 'success'
    PARTIAL = 'partial'
    FAILED = 'failed'
    CANCELED = 'canceled'
