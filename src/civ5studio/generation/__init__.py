"""Civilization project compiler API."""

from .compiler import (
    Compilation,
    CompilationError,
    RenderedArtifact,
    compile_project,
    generate_art_manifest,
    generate_improvements_sql,
    generated_build_type,
    modinfo_filename,
    project_folder_name,
    sql_string,
)
from .contracts import DATABASE_FILE_ORDER, REQUIRED_SCHEMA
from .lua_runtime import (
    generate_lua_runtime,
    lua_effect_manifest,
    lua_effect_manifest_json,
    lua_effect_manifest_markdown,
    registered_lua_hooks,
    selected_lua_effects,
)
from .sqlite_validation import (
    validate_compilation_tree,
    validate_compiled_sql,
    validate_compiled_sql_against_database,
)

__all__ = [
    "Compilation",
    "CompilationError",
    "DATABASE_FILE_ORDER",
    "REQUIRED_SCHEMA",
    "RenderedArtifact",
    "compile_project",
    "generate_art_manifest",
    "generate_improvements_sql",
    "generate_lua_runtime",
    "generated_build_type",
    "modinfo_filename",
    "lua_effect_manifest",
    "lua_effect_manifest_json",
    "lua_effect_manifest_markdown",
    "project_folder_name",
    "registered_lua_hooks",
    "sql_string",
    "selected_lua_effects",
    "validate_compilation_tree",
    "validate_compiled_sql",
    "validate_compiled_sql_against_database",
]
