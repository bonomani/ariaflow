#!/usr/bin/env python3
"""Generate openapi.yaml from webapp dispatch tables + route docstrings.

Usage:
    python scripts/gen_openapi.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT / "src" / "ariaflow_server"

sys.path.insert(0, str(_PROJECT / "src"))
try:
    from ariaflow_server.openapi_schemas import RESPONSE_SCHEMAS
except Exception:
    RESPONSE_SCHEMAS = {}

# Tag assignment by path prefix
_TAG_MAP = {
    "/api/downloads": "Queue",
    "/api/scheduler": "Scheduler",
    "/api/declaration": "Config",
    "/api/aria2": "aria2",
    "/api/bandwidth": "Bandwidth",
    "/api/torrents": "Torrents",
    "/api/sessions": "Sessions",
    "/api/lifecycle": "Lifecycle",
    "/api/log": "Observability",
    "/api/events": "Observability",
    "/api/health": "Observability",
    "/api/status": "Queue",
    "/api/docs": "Meta",
    "/api/openapi": "Meta",
    "/api/tests": "Meta",
    "/api": "Meta",
}


def _tag_for_path(path: str) -> str:
    for prefix, tag in sorted(_TAG_MAP.items(), key=lambda x: -len(x[0])):
        if path.startswith(prefix):
            return tag
    return "Other"


def _extract_dispatch_tables() -> tuple[dict[str, str], dict[str, str]]:
    """Extract GET and POST dispatch tables from webapp.py."""
    text = (_SRC / "webapp.py").read_text()
    get_match = re.search(r"_GET_ROUTES.*?\{(.*?)\}", text, re.DOTALL)
    post_match = re.search(r"_POST_ROUTES.*?\{(.*?)\}", text, re.DOTALL)
    gets = dict(re.findall(r'"(/[^"]+)":\s*routes\.(\w+)', get_match.group(1)))
    posts = dict(re.findall(r'"(/[^"]+)":\s*routes\.(\w+)', post_match.group(1)))
    return gets, posts


def _extract_docstrings() -> dict[str, str]:
    """Extract first line of each route function docstring."""
    docs = {}
    routes_dir = _SRC / "routes"
    for py_file in sorted(routes_dir.glob("*.py")):
        text = py_file.read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                doc = ast.get_docstring(node)
                if doc:
                    docs[node.name] = doc.split("\n")[0].strip()
                else:
                    docs[node.name] = ""
    return docs


def _parameterized_routes() -> list[tuple[str, str, str]]:
    """Return (method, path_template, func_name) for parameterized routes."""
    return [
        ("get", "/api/downloads/{id}/files", "get_item_files"),
        ("get", "/api/torrents/{infohash}.torrent", "get_torrent_file"),
        ("post", "/api/downloads/{id}/pause", "post_item_action"),
        ("post", "/api/downloads/{id}/resume", "post_item_action"),
        ("post", "/api/downloads/{id}/remove", "post_item_action"),
        ("post", "/api/downloads/{id}/retry", "post_item_action"),
        ("post", "/api/downloads/{id}/priority", "post_item_action"),
        ("post", "/api/downloads/{id}/files", "post_item_files"),
        ("post", "/api/torrents/{infohash}/stop", "post_torrent_stop"),
        ("post", "/api/lifecycle/{target}/{action}", "post_lifecycle_action"),
        ("patch", "/api/declaration/preferences", "patch_declaration_preferences"),
    ]


_SUMMARIES: dict[str, str] = {
    # GET
    "get_health": "Health check",
    "get_openapi_yaml": "OpenAPI specification (YAML)",
    "get_docs": "Swagger UI",
    "get_tests": "Run test suite",
    "get_api": "API discovery",
    "get_scheduler": "Scheduler status",
    "get_events": "SSE event stream (real-time state changes)",
    "get_bandwidth": "Bandwidth status and probe data",
    "get_status": "Queue status with items, state, and summary",
    "get_log": "Action log entries",
    "get_torrents": "List seeded torrents",
    "get_declaration": "UIC declaration (gates, preferences, policies)",
    "get_aria2_global_option": "aria2 global options",
    "get_aria2_option": "aria2 per-GID options",
    "get_aria2_option_tiers": "Option tiers (managed/safe/unsafe)",
    "get_lifecycle": "Install and service status",
    "get_archive": "Archived (removed/completed) downloads",
    "get_sessions": "Session history",
    "get_session_stats": "Session statistics",
    "get_item_files": "File list for torrent/metalink download",
    "get_torrent_file": "Download .torrent file",
    # POST
    "post_bandwidth_probe": "Trigger manual bandwidth probe",
    "post_add": "Add URLs to download queue",
    "post_cleanup": "Archive stale completed/error downloads",
    "post_scheduler_start": "Start the scheduler",
    "post_scheduler_stop": "Stop the scheduler",
    "post_pause": "Pause all active transfers",
    "post_resume": "Resume all paused transfers",
    "post_preflight": "Run preflight checks",
    "post_ucc": "Execute UCC cycle",
    "post_declaration": "Save UIC declaration",
    "post_aria2_change_global_option": "Change aria2 global options (3-tier safety)",
    "post_aria2_change_option": "Change aria2 per-GID options",
    "post_aria2_set_limits": "Set managed bandwidth and seed limits",
    "post_item_action": "Per-download action (pause/resume/remove/retry/priority)",
    "post_item_files": "Select torrent/metalink files for download",
    "post_torrent_stop": "Stop seeding a torrent",
    "post_lifecycle_action": "Install or uninstall a component (macOS)",
    # PATCH
    "patch_declaration_preferences": "Atomic partial preference update",
}


def _summary_from_func(func_name: str, docstrings: dict[str, str], path: str, method: str) -> str:
    """Generate summary from known map, docstring, or path."""
    if func_name in _SUMMARIES:
        return _SUMMARIES[func_name]
    doc = docstrings.get(func_name, "")
    if doc:
        return doc
    # Fallback
    parts = path.strip("/").split("/")
    action = parts[-1] if not parts[-1].startswith("{") else parts[-2] if len(parts) > 2 else ""
    resource = parts[1] if len(parts) > 1 else ""
    return f"{method.upper()} {resource} {action}".strip()


def _path_params(path: str) -> list[dict]:
    """Extract path parameters."""
    params = []
    for m in re.finditer(r"\{(\w+)\}", path):
        params.append({
            "name": m.group(1),
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        })
    return params


def _needs_body(method: str) -> bool:
    return method in ("post", "patch")


def _emit_scalar(lines: list, key: str, value: object, indent: str) -> None:
    """Emit a `key: value` line for a scalar OpenAPI field."""
    if isinstance(value, bool):
        lines.append(f"{indent}{key}: {str(value).lower()}")
    elif isinstance(value, (int, float)):
        lines.append(f"{indent}{key}: {value}")
    else:
        # Strings (type names, descriptions, enum values)
        lines.append(f"{indent}{key}: {value}")


def _emit_schema_node(lines: list, node: dict, indent: str) -> None:
    """Emit one OpenAPI schema fragment of arbitrary nesting depth.

    Recognized keys: $ref, type, nullable, description, enum, properties, items.
    A node containing $ref is emitted as a single `$ref: "..."` line and any
    sibling keys are dropped (per OpenAPI 3.0 — siblings of $ref are ignored).
    """
    if "$ref" in node:
        lines.append(f'{indent}$ref: "{node["$ref"]}"')
        return
    # Scalar fields first, sorted for stable output.
    for key in sorted(node.keys()):
        if key in ("properties", "items"):
            continue
        _emit_scalar(lines, key, node[key], indent)
    if "items" in node:
        items = node["items"]
        if isinstance(items, dict):
            lines.append(f"{indent}items:")
            _emit_schema_node(lines, items, indent + "  ")
        else:
            lines.append(f"{indent}items: {items}")
    if "properties" in node:
        props = node["properties"]
        lines.append(f"{indent}properties:")
        _emit_properties(lines, props, indent + "  ")


def _emit_properties(lines: list, props: dict, indent: str) -> None:
    """Emit a `properties:` block. Each value is itself a schema node."""
    for pname in sorted(props.keys()):
        pdef = props[pname]
        lines.append(f"{indent}{pname}:")
        _emit_schema_node(lines, pdef, indent + "  ")


def _generate_path_entry(method: str, path: str, func_name: str, docstrings: dict) -> dict:
    """Generate a single path operation."""
    tag = _tag_for_path(path)
    summary = _summary_from_func(func_name, docstrings, path, method)
    # Look up explicit response schema (BG-3)
    schema_key = f"{method.upper()} {path}"
    response_schema: dict
    if schema_key in RESPONSE_SCHEMAS:
        props = RESPONSE_SCHEMAS[schema_key]
        response_schema = {
            "type": "object",
            "properties": dict(props),
        }
    else:
        response_schema = {"type": "object"}
    entry: dict = {
        "tags": [tag],
        "summary": summary,
        "responses": {
            "200": {"description": "Success", "content": {"application/json": {"schema": response_schema}}},
        },
    }
    params = _path_params(path)
    if params:
        entry["parameters"] = params
    if _needs_body(method):
        entry["requestBody"] = {
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    # Add common error responses for POST/PATCH
    if method in ("post", "patch"):
        entry["responses"]["400"] = {"description": "Bad request"}
    if "{id}" in path or "{infohash}" in path:
        entry["responses"]["404"] = {"description": "Not found"}
    return entry


def _load_components() -> str:
    """Load the components section from existing spec."""
    text = (_SRC / "openapi.yaml").read_text()
    match = re.search(r"^(components:.*)$", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def _load_header() -> str:
    """Load the header (info, servers, tags) from existing spec.

    Injects the live package version into ``info.version`` (BG-4).
    """
    text = (_SRC / "openapi.yaml").read_text()
    # Everything before "paths:"
    idx = text.index("\npaths:")
    header = text[:idx]
    # Replace info.version with current __version__
    try:
        from ariaflow_server import __version__ as _v
        header = re.sub(
            r"^(\s*version:\s*)\S+",
            r"\g<1>" + _v,
            header,
            count=1,
            flags=re.MULTILINE,
        )
    except Exception:
        pass
    return header


def _yaml_str(s: str) -> str:
    """Quote a string for YAML if needed."""
    if any(c in s for c in ":{}\n\"'"):
        return f'"{s}"'
    return s


def _indent(text: str, level: int) -> str:
    prefix = "  " * level
    return "\n".join(prefix + line if line.strip() else "" for line in text.split("\n"))


def render_yaml(gets: dict, posts: dict, parameterized: list, docstrings: dict) -> str:
    """Render the complete OpenAPI YAML."""
    header = _load_header()
    components = _load_components()

    # Collect all paths
    paths: dict[str, dict[str, dict]] = {}

    for path, func in gets.items():
        paths.setdefault(path, {})["get"] = _generate_path_entry("get", path, func, docstrings)

    for path, func in posts.items():
        paths.setdefault(path, {})["post"] = _generate_path_entry("post", path, func, docstrings)

    for method, path, func in parameterized:
        paths.setdefault(path, {})[method] = _generate_path_entry(method, path, func, docstrings)

    # Render paths as YAML
    lines = [header, "\npaths:"]
    for path in sorted(paths.keys()):
        lines.append(f"  {path}:")
        for method in ("get", "post", "patch", "put", "delete"):
            if method not in paths[path]:
                continue
            entry = paths[path][method]
            lines.append(f"    {method}:")
            lines.append(f"      tags: [{entry['tags'][0]}]")
            lines.append(f"      summary: {_yaml_str(entry['summary'])}")
            if "parameters" in entry:
                lines.append("      parameters:")
                for p in entry["parameters"]:
                    lines.append(f"        - name: {p['name']}")
                    lines.append(f"          in: {p['in']}")
                    lines.append(f"          required: {str(p['required']).lower()}")
                    lines.append("          schema:")
                    lines.append(f"            type: {p['schema']['type']}")
            if "requestBody" in entry:
                lines.append("      requestBody:")
                lines.append("        content:")
                lines.append("          application/json:")
                lines.append("            schema:")
                lines.append("              type: object")
            lines.append("      responses:")
            for code, resp in sorted(entry["responses"].items()):
                lines.append(f'        "{code}":')
                lines.append(f"          description: {resp['description']}")
                if "content" in resp:
                    lines.append("          content:")
                    lines.append("            application/json:")
                    lines.append("              schema:")
                    schema = resp["content"]["application/json"]["schema"]
                    lines.append("                type: object")
                    props = schema.get("properties")
                    if props:
                        lines.append("                properties:")
                        _emit_properties(lines, props, indent="                  ")

    lines.append("")
    lines.append(components)
    return "\n".join(lines) + "\n"


def main() -> None:
    gets, posts = _extract_dispatch_tables()
    docstrings = _extract_docstrings()
    parameterized = _parameterized_routes()

    yaml_text = render_yaml(gets, posts, parameterized, docstrings)

    out = _SRC / "openapi.yaml"
    out.write_text(yaml_text, encoding="utf-8")

    root_copy = _PROJECT / "openapi.yaml"
    root_copy.write_text(yaml_text, encoding="utf-8")

    # Count paths
    path_count = len(gets) + len(posts) + len(parameterized)
    print(f"Generated {out} ({path_count} operations)")


if __name__ == "__main__":
    main()
