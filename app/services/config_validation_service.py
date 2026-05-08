from app.core.exceptions import ConfigError


class ConfigValidationService:
    @staticmethod
    def require_strategy_sequence(config: dict, allowed: set[str]) -> list[str]:
        sequence = config.get('strategy_sequence')
        if not isinstance(sequence, list) or not sequence:
            raise ConfigError('Missing required source.config.strategy_sequence')
        for item in sequence:
            if not isinstance(item, str) or item not in allowed:
                raise ConfigError(f'Invalid strategy in strategy_sequence: {item}')
        return sequence

    @staticmethod
    def require_retry_limits(config: dict) -> dict[str, int]:
        raw = config.get('retry_limits')
        if not isinstance(raw, dict) or not raw:
            raise ConfigError('Missing required source.config.retry_limits')
        out: dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, int) or value < 0:
                raise ConfigError(f'Invalid retry limit for {key}')
            out[key] = value
        return out

    @staticmethod
    def require_timeouts(config: dict) -> dict[str, int]:
        raw = config.get('timeouts')
        if not isinstance(raw, dict) or not raw:
            raise ConfigError('Missing required source.config.timeouts')
        required = {'product_sec', 'source_run_sec'}
        if not required.issubset(raw.keys()):
            raise ConfigError('Missing required timeout keys: product_sec, source_run_sec')
        out: dict[str, int] = {}
        for key in required:
            value = raw.get(key)
            if not isinstance(value, int) or value <= 0:
                raise ConfigError(f'Invalid timeout value for {key}')
            out[key] = value
        return out
