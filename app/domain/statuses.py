from enum import Enum


class SourceStatus(str, Enum):
    ACTIVE = 'active'
    DISABLED = 'disabled'
    ERROR = 'error'
    AUTH_REQUIRED = 'auth_required'


class SourceProductStatus(str, Enum):
    AVAILABLE = 'available'
    OUT_OF_STOCK = 'out_of_stock'
    UNAVAILABLE = 'unavailable'


class SourceRunStatus(str, Enum):
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    SUCCESS = 'success'
    PARTIAL = 'partial'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
