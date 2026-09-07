"""Reviewed release matrix plus checks of the private interfaces we override."""

from inspect import signature

# Expand only after running the complete behavior suite on that release.
SUPPORTED_CORE = frozenset({"2026.8.3", "2026.9.1"})
SUPPORTED_HAP = frozenset({"5.0.0"})


def compatible(core_version, hap_version, tv_class):
    """Reject untested releases or changed method contracts before patching TYPES."""
    if core_version not in SUPPORTED_CORE or hap_version not in SUPPORTED_HAP:
        return False
    contracts = {
        "_get_ordered_source_list_from_state": ("self", "state"),
        "_async_update_input_state": ("self", "hk_state", "new_state"),
        "set_input_source": ("self", "value"),
        "run": ("self",),
        "async_stop": ("self",),
    }
    for name, expected in contracts.items():
        method = getattr(tv_class, name, None)
        if not callable(method) or tuple(signature(method).parameters) != expected:
            return False
    return True
