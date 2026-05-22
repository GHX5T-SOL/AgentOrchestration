"""Helpers for building safe exception-tracking context."""

from typing import Any, Dict, Mapping, Optional


_CONTAINER_KEYS = {
    "context",
    "event",
    "exception_context",
    "frame",
    "frames",
    "local_variables",
    "locals",
    "metadata",
    "task",
}


def build_exception_event(
    task: Mapping[str, Any],
    exc: BaseException,
    local_variables: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    """Build the allow-listed context sent to exception tracking hooks."""
    context: Dict[str, Any] = {"task": task, "exception": exc}
    if local_variables:
        context["locals"] = local_variables

    event = sanitize_exception_context(context)
    event.setdefault("error_class", type(exc).__name__)
    return event


def sanitize_local_variables(
    local_variables: Mapping[str, Any],
    exc: Optional[BaseException] = None,
) -> Dict[str, str]:
    """Reduce captured frame locals to dashboard-safe lookup fields."""
    context: Dict[str, Any] = {"locals": local_variables}
    if exc is not None:
        context["exception"] = exc
    return sanitize_exception_context(context)


def sanitize_exception_context(context: Mapping[str, Any]) -> Dict[str, str]:
    """Return only fields approved for shared exception tooling."""
    sanitized: Dict[str, str] = {}

    task_id = _find_task_id(context)
    if task_id is not None:
        sanitized["task_id"] = task_id

    error_class = _find_error_class(context)
    if error_class is not None:
        sanitized["error_class"] = error_class

    return sanitized


def _find_task_id(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        direct = _safe_text(value.get("task_id"))
        if direct is not None:
            return direct

        task = value.get("task")
        if isinstance(task, Mapping):
            task_id = _safe_text(task.get("task_id"))
            if task_id is not None:
                return task_id
            task_id = _safe_text(task.get("id"))
            if task_id is not None:
                return task_id

        for key in _CONTAINER_KEYS:
            nested = value.get(key)
            if nested is None:
                continue
            task_id = _find_task_id(nested)
            if task_id is not None:
                return task_id
        return None

    if isinstance(value, (list, tuple)):
        for item in value:
            task_id = _find_task_id(item)
            if task_id is not None:
                return task_id
    return None


def _find_error_class(value: Any) -> Optional[str]:
    if isinstance(value, BaseException):
        return type(value).__name__

    if isinstance(value, type) and issubclass(value, BaseException):
        return value.__name__

    if isinstance(value, Mapping):
        for key in ("error_class", "error_type", "exception_class"):
            error_class = _safe_text(value.get(key))
            if error_class is not None:
                return error_class

        for key in ("exception", "error", *_CONTAINER_KEYS):
            nested = value.get(key)
            if nested is None:
                continue
            error_class = _find_error_class(nested)
            if error_class is not None:
                return error_class
        return None

    if isinstance(value, (list, tuple)):
        for item in value:
            error_class = _find_error_class(item)
            if error_class is not None:
                return error_class
    return None


def _safe_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        text = str(value)
        if text:
            return text
    return None
