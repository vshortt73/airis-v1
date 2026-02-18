"""
Node2 availability checker.

Provides a single function to check if a Node2-dependent feature is enabled.
Combines the master NODE2_ENABLED flag with per-service flags.
"""


def is_node2_service_enabled(service_flag: str) -> bool:
    """
    Check if a Node2-dependent service is enabled.

    Returns True only if both NODE2_ENABLED and the per-service flag are True.

    Args:
        service_flag: The per-service config key, e.g. 'STT_ENABLED'
    """
    from app import config  # lazy import to avoid circular import at startup
    node2_enabled = getattr(config, 'NODE2_ENABLED', True)
    service_enabled = getattr(config, service_flag, True)
    return node2_enabled and service_enabled
