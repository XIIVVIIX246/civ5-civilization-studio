"""Application orchestration services used by the desktop controller.

The public conveniences in this package are loaded lazily.  Generation and
build modules import individual application helpers, so eager re-exports here
would create a compiler -> application -> build -> compiler import cycle in a
fresh Python process.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ImageTransform": (".image_prep", "ImageTransform"),
    "prepare_role_source_image": (".image_prep", "prepare_role_source_image"),
    "prepare_source_image": (".image_prep", "prepare_source_image"),
    "InstallInProgress": (".install", "InstallInProgress"),
    "InstallResult": (".install", "InstallResult"),
    "InstallService": (".install", "InstallService"),
    "default_civ5_mods_path": (".install", "default_civ5_mods_path"),
    "materialize_ui_sources": (".project_adapter", "materialize_ui_sources"),
    "project_from_ui": (".project_adapter", "project_from_ui"),
    "project_to_ui": (".project_adapter", "project_to_ui"),
    "save_ui_project": (".project_adapter", "save_ui_project"),
    "OperationIssue": (".workflow", "OperationIssue"),
    "ProjectWorkflowService": (".workflow", "ProjectWorkflowService"),
    "WorkflowMode": (".workflow", "WorkflowMode"),
    "WorkflowResult": (".workflow", "WorkflowResult"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
