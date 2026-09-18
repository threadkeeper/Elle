import os


_TRUE_VALUES = {"1", "true"}
_FALSE_VALUES = {"", "0", "false"}


def bare_metal_enabled(value: str | None = None) -> bool:
    normalized = (os.environ.get("ELLE_BARE_METAL_MODE", "") if value is None else value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError("ELLE_BARE_METAL_MODE must be true, false, 1, or 0")


def disable_optional_runtime_work() -> None:
    os.environ["AGENT_FRAMEWORK_USER_AGENT_DISABLED"] = "true"
    os.environ["AGENT_FRAMEWORK_FEATURE_MASK_DISABLED"] = "true"
    os.environ["ENABLE_INSTRUMENTATION"] = "false"
    os.environ["OTEL_SDK_DISABLED"] = "true"