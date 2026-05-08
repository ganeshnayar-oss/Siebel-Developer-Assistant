#!/usr/bin/env python3
"""Prompt-first MCP server for Siebel Open UI automation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from difflib import get_close_matches
from datetime import datetime
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(
    os.environ.get(
        "SIEBEL_PLUGIN_CONFIG",
        str(PLUGIN_ROOT / "scripts" / "siebel_open_ui.config.json"),
    )
)
ADAPTER_SCRIPT = PLUGIN_ROOT / "scripts" / "example_siebel_adapter.py"
PROTOCOL_VERSION = "2025-06-18"

APPLET_TYPES = ("list", "form", "tree", "chart")
FIELD_SPLIT_RE = re.compile(r"\s*(?:,|/|\band\b|\&)\s*", re.IGNORECASE)
SERVICE_NAME_PATTERNS = [
    r"create\s+an?\s+business\s+service\s+called\s+(.+?)(?:\s+with|\s+using|\s+in\s+project|$)",
    r"create\s+an?\s+business\s+service\s+named\s+(.+?)(?:\s+with|\s+using|\s+in\s+project|$)",
    r"create\s+business\s+service\s+(.+?)(?:\s+with|\s+using|\s+in\s+project|$)",
]
BUSINESS_COMPONENT_NAME_PATTERNS = [
    r"create\s+an?\s+business\s+component\s+called\s+(.+?)(?:\s+with|\s+using|\s+based\s+on|\s+on\s+table|\s+in\s+project|$)",
    r"create\s+an?\s+business\s+component\s+named\s+(.+?)(?:\s+with|\s+using|\s+based\s+on|\s+on\s+table|\s+in\s+project|$)",
    r"create\s+business\s+component\s+(.+?)(?:\s+with|\s+using|\s+based\s+on|\s+on\s+table|\s+in\s+project|$)",
]
WORKFLOW_NAME_PATTERNS = [
    r"create\s+(?:a|an)\s+workflow\s+named\s+(.+?)(?:\s+that|\s+with|\s+using|\s+for|\s+in\s+project|$)",
    r"create\s+(?:a|an)\s+workflow\s+called\s+(.+?)(?:\s+that|\s+with|\s+using|\s+for|\s+in\s+project|$)",
    r"create\s+workflow\s+(.+?)(?:\s+that|\s+with|\s+using|\s+for|\s+in\s+project|$)",
]
BUSINESS_OBJECT_ALIASES = {
    "service request": "Service Request",
    " sr ": "Service Request",
    "opportunity": "Opportunity",
    "contact": "Contact",
    "account": "Account",
    "order": "Order Entry (Sales)",
}
BUSINESS_COMPONENT_TABLE_ALIASES = {
    "contact": "S_CONTACT",
    "contacts": "S_CONTACT",
    "account": "S_ORG_EXT",
    "accounts": "S_ORG_EXT",
    "opportunity": "S_OPTY",
    "opportunities": "S_OPTY",
    "service request": "S_SRV_REQ",
    "service requests": "S_SRV_REQ",
    "order": "S_ORDER",
    "orders": "S_ORDER",
    "quote": "S_DOC_QUOTE",
    "quotes": "S_DOC_QUOTE",
}

PROTECTED_SHARED_APPLETS: dict[tuple[str, str], dict[str, Any]] = {
    (
        "Order Entry - Line Items View (Sales)",
        "Order Entry - Order Form Applet Dashboard (Sales)",
    ): {
        "shared_with_views": ["Order Entry - Line Items Detail View (Sales)"],
        "reason": "Shared Sales Order dashboard applet used by multiple line-item views.",
    },
    (
        "Order Entry - Line Items Detail View (Sales)",
        "Order Entry - Order Form Applet Dashboard (Sales)",
    ): {
        "shared_with_views": ["Order Entry - Line Items View (Sales)"],
        "reason": "Shared Sales Order dashboard applet used by multiple line-item views.",
    },
}


TOOLS = [
    {
        "name": "describe_setup",
        "title": "Describe Siebel setup",
        "description": "Show the active connection config, missing fields, and usage guidance.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "test_connection",
        "title": "Test Siebel connection",
        "description": "Validate the configured Siebel connection details.",
        "inputSchema": {"type": "object", "additionalProperties": False},
    },
    {
        "name": "validate_workspace_target",
        "title": "Validate workspace target",
        "description": "Validate the target workspace branch and optionally confirm that a view and applet resolve correctly in that branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "workspace_branch": {"type": "string"},
                "view_name": {"type": "string"},
                "applet_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "plan_applet_request",
        "title": "Plan applet request",
        "description": "Parse a natural-language request into a Siebel applet plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
                "view_name": {"type": "string"},
                "confirm_bc_field_choices": {"type": "boolean"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_applet_from_prompt",
        "title": "Create applet from prompt",
        "description": "Create a Siebel workspace and applet from a natural-language request, with optional view placement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
                "view_name": {"type": "string"},
                "auto_place": {"type": "boolean"},
                "confirm_bc_field_choices": {"type": "boolean"},
                "confirmed_field_choices": {"type": "boolean"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_business_component_request",
        "title": "Plan business component request",
        "description": "Parse a natural-language request into a Siebel business component plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_business_component_from_prompt",
        "title": "Create business component from prompt",
        "description": "Create a Siebel business component from a natural-language request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_business_component",
        "title": "Create business component",
        "description": "Create a Siebel business component using explicit values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "business_component_name": {"type": "string"},
                "project": {"type": "string"},
                "class_name": {"type": "string"},
                "table_name": {"type": "string"},
                "no_insert": {"type": "string"},
                "no_update": {"type": "string"},
                "no_delete": {"type": "string"},
                "comments": {"type": "string"},
            },
            "required": ["business_component_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_workspace",
        "title": "Create Siebel workspace",
        "description": "Create a workspace using explicit values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "branch_name": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["workspace_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_applet",
        "title": "Create Siebel applet",
        "description": "Create an applet using explicit values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "applet_name": {"type": "string"},
                "business_component": {"type": "string"},
                "applet_type": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "project": {"type": "string"},
                "template_name": {"type": "string"},
                "class_name": {"type": "string"},
                "web_template": {"type": "string"},
            },
            "required": ["applet_name", "business_component"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_applet_to_view",
        "title": "Place applet on view",
        "description": "Attach an applet to a Siebel view.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "view_name": {"type": "string"},
                "applet_name": {"type": "string"},
                "mode": {"type": "string"},
                "tab_name": {"type": "string"},
                "sequence": {"type": "string"},
            },
            "required": ["view_name", "applet_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_view_on_screen",
        "title": "Create view on screen",
        "description": "Create a new Siebel view from an existing source view pattern and register it under a screen.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "view_name": {"type": "string"},
                "screen_name": {"type": "string"},
                "source_view_name": {"type": "string"},
                "applet_name": {"type": "string"},
                "project": {"type": "string"},
            },
            "required": ["view_name", "screen_name", "applet_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_business_service_request",
        "title": "Plan business service request",
        "description": "Parse a natural-language request into a Siebel business service plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_workflow_request",
        "title": "Plan workflow request",
        "description": "Parse a natural-language request into a Siebel workflow plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_business_service_from_prompt",
        "title": "Create business service from prompt",
        "description": "Create a Siebel business service from a natural-language request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_workflow_from_prompt",
        "title": "Create workflow from prompt",
        "description": "Create a Siebel workflow process from a natural-language request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "workspace_name": {"type": "string"},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_business_service",
        "title": "Create business service",
        "description": "Create a Siebel business service using explicit values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "business_service_name": {"type": "string"},
                "project": {"type": "string"},
                "class_name": {"type": "string"},
                "cache": {"type": "string"},
                "server_enabled": {"type": "string"},
                "web_service_enabled": {"type": "string"},
                "state_management_type": {"type": "string"},
                "hidden": {"type": "string"},
                "external_use": {"type": "string"},
                "browser_class": {"type": "string"},
                "comments": {"type": "string"},
            },
            "required": ["business_service_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_workflow",
        "title": "Create workflow",
        "description": "Create a Siebel workflow process using explicit values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string"},
                "workflow_name": {"type": "string"},
                "project": {"type": "string"},
                "business_object": {"type": "string"},
                "workflow_mode": {"type": "string"},
                "runnable": {"type": "string"},
                "state_management_type": {"type": "string"},
                "web_service_enabled": {"type": "string"},
                "pass_by_ref_hierarchy_argument": {"type": "string"},
                "replication_level": {"type": "string"},
                "status": {"type": "string"},
                "inactive": {"type": "string"},
                "description": {"type": "string"},
                "comments": {"type": "string"},
            },
            "required": ["workflow_name"],
            "additionalProperties": False,
        },
    },
]


def load_config() -> dict[str, Any]:
    if not DEFAULT_CONFIG.exists():
        return {"connection": {}, "defaults": {}}
    return json.loads(DEFAULT_CONFIG.read_text())


def connection_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("connection", {})


def workflow_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("workflow", {})


def targeting_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("targeting", {})


def effective_missing_connection_fields(connection: dict[str, Any], workspace_branch: str = "") -> list[str]:
    missing = required_connection_fields(connection)
    if workspace_branch and "workspace_branch" in missing:
        missing = [field for field in missing if field != "workspace_branch"]
    return missing


def resolve_workspace_target(
    config: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = overrides or {}
    connection = connection_config(config)
    targeting = targeting_config(config)
    explicit_workspace = str(
        overrides.get("workspace_branch")
        or overrides.get("workspace_name")
        or ""
    ).strip()
    configured_workspace = str(connection.get("workspace_branch", "")).strip()
    require_explicit_workspace = bool(targeting.get("require_explicit_workspace", False))

    if explicit_workspace:
        resolved_workspace = explicit_workspace
        resolution = "explicit_input"
    elif configured_workspace and not require_explicit_workspace:
        resolved_workspace = configured_workspace
        resolution = "config_default"
    else:
        resolved_workspace = ""
        resolution = "missing"

    return {
        "workspace_name": resolved_workspace,
        "workspace_branch": resolved_workspace,
        "branch_name": resolved_workspace,
        "workspace_resolution": resolution,
        "require_explicit_workspace": require_explicit_workspace,
    }


def load_adapter_module() -> Any:
    adapter_dir = str(ADAPTER_SCRIPT.parent)
    if adapter_dir not in sys.path:
        sys.path.insert(0, adapter_dir)
    import example_siebel_adapter as adapter  # type: ignore
    return adapter


def build_adapter_connection(connection: dict[str, Any], workspace_branch: str) -> Any:
    adapter = load_adapter_module()
    return adapter.ConnectionConfig(
        oracle_guid=str(connection.get("oracle_guid", "")),
        webtools_url=str(connection.get("webtools_url", "")),
        workspace_branch=workspace_branch,
        username=str(connection.get("username", "")),
        password=str(connection.get("password", "")),
        verify_tls=bool(connection.get("verify_tls", True)),
    )


def collect_view_applet_references(view: dict[str, Any]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for field_name in ["Thread Applet", "Visibility Applet", *[f"Sector{index} Applet" for index in range(8)]]:
        value = str(view.get(field_name, "")).strip()
        if value:
            references.append({"field_name": field_name, "applet_name": value})
    return references


def infer_rendered_applet(view: dict[str, Any]) -> str:
    thread_applet = str(view.get("Thread Applet", "")).strip()
    if thread_applet:
        return thread_applet
    for index in range(8):
        sector_applet = str(view.get(f"Sector{index} Applet", "")).strip()
        if sector_applet:
            return sector_applet
    return ""


def protected_shared_applet_details(view_name: str, rendered_applet: str) -> dict[str, Any] | None:
    details = PROTECTED_SHARED_APPLETS.get((view_name, rendered_applet))
    if not details:
        return None
    return {
        "rendered_applet": rendered_applet,
        "shared_with_views": details["shared_with_views"],
        "reason": details["reason"],
        "mutation_guidance": (
            "Avoid rewriting the shared applet header. Prefer minimal child-row changes and "
            "compare the applet header against MAIN after mutation."
        ),
    }


def compare_applet_to_main(
    adapter: Any,
    conn: Any,
    applet_name: str,
) -> dict[str, Any]:
    current = adapter.get_resource(conn, "Applet", applet_name)
    main = adapter.request_json(
        conn,
        "GET",
        adapter.build_path("Applet", applet_name),
        branch_name="MAIN",
    )["body"]
    drift = {
        key: {"current": current.get(key), "main": main.get(key)}
        for key in sorted(set(current) | set(main))
        if key != "Link" and current.get(key) != main.get(key)
    }
    return {"has_drift": bool(drift), "drift": drift}


def validate_workspace_target_details(arguments: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    connection = connection_config(config)
    workspace_target = resolve_workspace_target(config, arguments)
    missing = effective_missing_connection_fields(connection, workspace_target["workspace_branch"])
    base_result: dict[str, Any] = {
        "ok": False,
        "workspace": {
            "workspace_name": workspace_target["workspace_name"],
            "workspace_branch": workspace_target["workspace_branch"],
            "workspace_resolution": workspace_target["workspace_resolution"],
            "require_explicit_workspace": workspace_target["require_explicit_workspace"],
        },
        "missing_required_fields": missing,
        "view": None,
        "applet": None,
        "message": "",
    }

    if missing:
        base_result["message"] = "Connection details are incomplete for validating the target workspace."
        return base_result

    if not workspace_target["workspace_branch"]:
        base_result["message"] = "No workspace branch was resolved. Pass workspace_name or set connection.workspace_branch in config."
        return base_result

    adapter = load_adapter_module()
    conn = build_adapter_connection(connection, workspace_target["workspace_branch"])
    try:
        describe = adapter.get_describe(conn)
    except Exception as exc:
        base_result["message"] = f"Workspace branch validation failed: {exc}"
        return base_result

    result = dict(base_result)
    result["describe_status"] = describe.get("status")
    result["describe_url"] = describe.get("url")

    view_name = str(arguments.get("view_name", "")).strip()
    applet_name = str(arguments.get("applet_name", "")).strip()

    if view_name:
        try:
            view = adapter.get_resource(conn, "View", view_name)
            references = collect_view_applet_references(view)
            rendered_applet = infer_rendered_applet(view)
            resolved_references: list[dict[str, Any]] = []
            missing_references: list[dict[str, Any]] = []
            for reference in references:
                try:
                    applet = adapter.get_resource(conn, "Applet", reference["applet_name"])
                    resolved_references.append(
                        {
                            "field_name": reference["field_name"],
                            "applet_name": reference["applet_name"],
                            "inactive": applet.get("Inactive"),
                            "class_name": applet.get("Class"),
                            "project": applet.get("Project Name"),
                        }
                    )
                except Exception as exc:
                    missing_references.append(
                        {
                            "field_name": reference["field_name"],
                            "applet_name": reference["applet_name"],
                            "error": str(exc),
                        }
                    )
            result["view"] = {
                "name": view.get("Name"),
                "inactive": view.get("Inactive"),
                "project": view.get("Project Name"),
                "business_object": view.get("Business Object"),
                "thread_applet": view.get("Thread Applet"),
                "rendered_applet": rendered_applet,
                "referenced_applets": resolved_references,
                "missing_referenced_applets": missing_references,
                "protected_shared_applet": protected_shared_applet_details(view_name, rendered_applet),
            }
        except Exception as exc:
            result["view"] = {"name": view_name, "error": str(exc)}

    if applet_name:
        try:
            applet = adapter.get_resource(conn, "Applet", applet_name)
            result["applet"] = {
                "name": applet.get("Name"),
                "inactive": applet.get("Inactive"),
                "project": applet.get("Project Name"),
                "class_name": applet.get("Class"),
                "business_component": applet.get("Business Component"),
                "compare_to_main": compare_applet_to_main(adapter, conn, applet_name),
            }
        except Exception as exc:
            result["applet"] = {"name": applet_name, "error": str(exc)}

    ok = True
    if result.get("view") and result["view"].get("error"):
        ok = False
    if result.get("view") and result["view"].get("missing_referenced_applets"):
        ok = False
    if result.get("applet") and result["applet"].get("error"):
        ok = False
    if result.get("view") and result.get("applet") and not result["applet"].get("error"):
        referenced = {
            item["applet_name"]
            for item in result["view"].get("referenced_applets", [])
        }
        result["view"]["references_target_applet"] = applet_name in referenced
    result["ok"] = ok
    if ok:
        result["message"] = "Workspace target validation passed."
    elif not result["message"]:
        result["message"] = "Workspace target validation found unresolved view or applet references."
    return result


def preflight_workspace_target(
    arguments: dict[str, Any],
    *,
    require_view_resolution: bool = False,
    require_applet_resolution: bool = False,
) -> dict[str, Any] | None:
    check_args = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "view_name": arguments.get("view_name", "") if require_view_resolution else "",
        "applet_name": arguments.get("applet_name", "") if require_applet_resolution else "",
    }
    validation = validate_workspace_target_details(check_args)
    if validation["ok"]:
        return None
    return render_text("Siebel workspace target validation failed", validation) | {"isError": True}


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        return None

    body = sys.stdin.buffer.read(content_length)
    return json.loads(body.decode("utf-8"))


def send_message(payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def error_response(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def sanitize_connection(connection: dict[str, Any]) -> dict[str, Any]:
    hidden = dict(connection)
    if hidden.get("password"):
        hidden["password"] = "***"
    return hidden


def required_connection_fields(connection: dict[str, Any]) -> list[str]:
    required = [
        "oracle_guid",
        "webtools_url",
        "workspace_branch",
        "username",
        "password",
    ]
    return [field for field in required if not str(connection.get(field, "")).strip()]


def title_case(value: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", value)
    return " ".join(part.capitalize() for part in cleaned.split())


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def tokenized_field_name(value: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", value.lower()) if part}


def infer_applet_type(text: str) -> str:
    lowered = text.lower()
    for applet_type in APPLET_TYPES:
        if f" {applet_type} " in f" {lowered} ":
            return applet_type
    return "list"


def extract_fields(request: str) -> list[str]:
    lowered = request.lower()
    markers = [
        "includes",
        "include",
        "with fields",
        "with columns",
        "with",
        "showing",
    ]
    segment = ""
    for marker in markers:
        idx = lowered.find(marker)
        if idx >= 0:
            segment = request[idx + len(marker) :]
            break
    if not segment:
        return []

    for stopper in [" on ", " in ", " for ", " using ", " under "]:
        lowered_segment = segment.lower()
        idx = lowered_segment.find(stopper)
        if idx >= 0:
            segment = segment[:idx]
            break

    fields = [title_case(item) for item in FIELD_SPLIT_RE.split(segment) if item.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for field in fields:
        key = field.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(field)
    return deduped


def extract_entity(request: str) -> str:
    lowered = request.lower()
    patterns = [
        r"create\s+an?\s+(.+?)\s+(?:list|form|tree|chart)\s+applet",
        r"create\s+(.+?)\s+(?:list|form|tree|chart)\s+applet",
        r"create\s+an?\s+(.+?)\s+applet",
        r"create\s+(.+?)\s+applet",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            candidate = re.sub(r"\bnew\b", "", match.group(1), flags=re.IGNORECASE).strip()
            if candidate:
                return title_case(candidate)
    return "Custom"


def extract_view_name(request: str) -> str:
    match = re.search(r"\bon\s+([a-z0-9 _-]+?)\s+view\b", request, re.IGNORECASE)
    if match:
        return title_case(match.group(1)) + " View"
    return ""


def extract_business_service_name(request: str) -> str:
    for pattern in SERVICE_NAME_PATTERNS:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            candidate = re.sub(r"[\"'.]+$", "", match.group(1).strip())
            candidate = re.sub(r"^[\"'.]+", "", candidate)
            if candidate:
                return candidate
    return "Custom Business Service"


def extract_business_component_name(request: str) -> str:
    for pattern in BUSINESS_COMPONENT_NAME_PATTERNS:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            candidate = re.sub(r"[\"'.]+$", "", match.group(1).strip())
            candidate = re.sub(r"^[\"'.]+", "", candidate)
            if candidate:
                return candidate
    return "Custom Business Component"


def extract_named_value(request: str, labels: list[str]) -> str:
    for label in labels:
        pattern = rf"(?:using|with|class|project)\s+{label}\s+([A-Za-z0-9_#(). -]+)"
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".,")
    return ""


def extract_service_class(request: str) -> str:
    patterns = [
        r"(?:using|with)\s+class\s+([A-Za-z0-9_]+)",
        r"\bclass\s+([A-Za-z0-9_]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def extract_business_component_class(request: str) -> str:
    patterns = [
        r"(?:using|with)\s+class\s+([A-Za-z0-9_]+)",
        r"\bclass\s+([A-Za-z0-9_]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def extract_table_name(request: str) -> str:
    patterns = [
        r"\b(?:based on|using|with)\s+table\s+([A-Za-z0-9_#.$]+)",
        r"\bon\s+table\s+([A-Za-z0-9_#.$]+)",
        r"\btable\s+([A-Za-z0-9_#.$]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".,")
    return ""


def infer_business_component_table(request: str) -> str:
    lowered = f" {request.lower()} "
    for label, table_name in sorted(
        BUSINESS_COMPONENT_TABLE_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if f" {label} " in lowered:
            return table_name
    return ""


def infer_business_component_entity(request: str) -> str:
    lowered = f" {request.lower()} "
    for label in sorted(BUSINESS_COMPONENT_TABLE_ALIASES, key=len, reverse=True):
        if f" {label} " in lowered:
            return label
    return ""


def extract_project_name(request: str) -> str:
    patterns = [
        r"\bin\s+project\s+([A-Za-z0-9_() -]+)",
        r"\bproject\s+([A-Za-z0-9_() -]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".,")
    return ""


def extract_workflow_name(request: str) -> str:
    for pattern in WORKFLOW_NAME_PATTERNS:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip().strip("\"'")
            if candidate:
                return candidate
    return "Custom Workflow"


def extract_business_object_name(request: str) -> str:
    patterns = [
        r"\bfor\s+(?:the\s+)?([A-Za-z0-9_() -]+?)\s+business object\b",
        r"\bfor\s+business object\s+([A-Za-z0-9_() -]+)",
        r"\bon\s+(?:the\s+)?([A-Za-z0-9_() -]+?)\s+business object\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".,")

    lowered = f" {request.lower()} "
    for marker, business_object in BUSINESS_OBJECT_ALIASES.items():
        if marker in lowered:
            return business_object
    return ""


def infer_workflow_mode(request: str) -> str:
    lowered = request.lower()
    if "interactive flow" in lowered:
        return "Interactive Flow"
    if "long running" in lowered:
        return "Long Running"
    if "service flow" in lowered:
        return "Service Flow"
    return "Service Flow"


def human_in_the_loop_required(
    config: dict[str, Any],
    overrides: dict[str, Any],
    *,
    workflow_key: str,
) -> bool:
    if workflow_key in overrides:
        return bool(overrides.get(workflow_key))
    workflow = workflow_config(config)
    hitl = workflow.get("human_in_the_loop", {})
    return bool(hitl.get(workflow_key, False))


def get_bc_field_names(config: dict[str, Any], business_component: str, requested_fields: list[str] | None = None) -> list[str]:
    connection = connection_config(config)
    workspace_target = resolve_workspace_target(config, {})
    missing = effective_missing_connection_fields(connection, workspace_target["workspace_branch"])
    if missing:
        return []

    adapter = load_adapter_module()
    conn = build_adapter_connection(connection, workspace_target["workspace_branch"])
    field_names: list[str] = []
    seen: set[str] = set()
    requested_fields = requested_fields or []

    def add_field(name: str) -> None:
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            field_names.append(name)

    if not requested_fields:
        try:
            result = adapter.fetch_resource_list(
                conn,
                f"Business Component/{business_component}/Field",
                params={
                    "uniformresponse": "Y",
                    "pagination": "Y",
                    "PageSize": 200,
                    "StartRowNum": 0,
                    "fields": "Name",
                },
            )
            items = result.get("body", {}).get("items", [])
            for item in items:
                add_field(str(item.get("Name", "")).strip())
            return field_names
        except Exception:
            return []

    for requested_field in requested_fields:
        alias_probes: list[str] = []
        normalized_requested = normalize_field_name(requested_field)
        if normalized_requested == "address":
            alias_probes = ["Street Address"]
        elif normalized_requested == "phone":
            alias_probes = ["Work Phone #", "Cellular Phone #"]
        elif normalized_requested in {"email", "emailaddress"}:
            alias_probes = ["Email Address"]

        for alias_probe in [requested_field, *alias_probes]:
            try:
                exact = adapter.get_resource(conn, "Business Component", business_component, "Field", alias_probe)
                add_field(str(exact.get("Name", "")).strip())
            except Exception:
                continue

        tokens = [token for token in tokenized_field_name(requested_field) if len(token) >= 3]
        search_terms = tokens or [requested_field.lower()]
        searchspec = " OR ".join(f'[Name] LIKE "*{term.title()}*"' for term in search_terms[:3])
        try:
            result = adapter.fetch_resource_list(
                conn,
                f"Business Component/{business_component}/Field",
                params={
                    "uniformresponse": "Y",
                    "pagination": "Y",
                    "PageSize": 50,
                    "StartRowNum": 0,
                    "fields": "Name",
                    "searchspec": searchspec,
                },
            )
            items = result.get("body", {}).get("items", [])
            for item in items:
                add_field(str(item.get("Name", "")).strip())
        except Exception:
            continue

    return field_names


def rank_field_candidates(requested_field: str, available_fields: list[str]) -> list[str]:
    normalized_requested = normalize_field_name(requested_field)
    requested_tokens = tokenized_field_name(requested_field)
    scored: list[tuple[int, str]] = []
    for field_name in available_fields:
        normalized_field = normalize_field_name(field_name)
        field_tokens = tokenized_field_name(field_name)
        score = 0
        if normalized_field == normalized_requested:
            score += 1000
        if normalized_field.startswith(normalized_requested) or normalized_requested.startswith(normalized_field):
            score += 300
        if normalized_requested and normalized_requested in normalized_field:
            score += 250
        overlap = len(requested_tokens & field_tokens)
        score += overlap * 100
        if requested_tokens and requested_tokens.issubset(field_tokens):
            score += 150
        if "address" in requested_tokens and "street" in field_tokens and "address" in field_tokens:
            score += 500
        if "address" in requested_tokens and normalized_field.startswith("streetaddress"):
            score += 500
        if "phone" in requested_tokens and normalized_field.startswith("workphone"):
            score += 500
        if "phone" in requested_tokens and normalized_field.startswith("cellularphone"):
            score += 300
        if "phone" in requested_tokens and normalized_field.startswith("alternatephone"):
            score += 100
        if "phone" in requested_tokens and "phone" in field_tokens:
            score += 125
        if "email" in requested_tokens and "email" in field_tokens:
            score += 125
        if score > 0:
            scored.append((score, field_name))

    close_matches = get_close_matches(requested_field, available_fields, n=5, cutoff=0.55)
    for index, field_name in enumerate(close_matches):
        scored.append((80 - index, field_name))

    deduped: list[str] = []
    seen: set[str] = set()
    for _, field_name in sorted(scored, key=lambda item: (-item[0], item[1].lower())):
        key = field_name.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(field_name)
    return deduped[:5]


def resolve_field_choices(requested_fields: list[str], available_fields: list[str]) -> list[dict[str, Any]]:
    available_by_normalized = {normalize_field_name(field): field for field in available_fields}
    analysis: list[dict[str, Any]] = []

    for requested_field in requested_fields:
        normalized_requested = normalize_field_name(requested_field)
        exact = available_by_normalized.get(normalized_requested)
        candidates = rank_field_candidates(requested_field, available_fields)
        resolved = exact or (candidates[0] if candidates else "")
        match_type = "unresolved"
        if exact:
            match_type = "exact"
        elif resolved:
            match_type = "inferred"

        analysis.append(
            {
                "requested_field": requested_field,
                "resolved_field": resolved,
                "match_type": match_type,
                "candidates": candidates,
            }
        )

    return analysis


def build_plan(request: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    config = load_config()
    connection = connection_config(config)
    defaults = config.get("defaults", {})
    workspace_target = resolve_workspace_target(config, overrides)

    entity = extract_entity(request)
    applet_type = infer_applet_type(request)
    requested_fields = extract_fields(request)
    inferred_view_name = overrides.get("view_name") or extract_view_name(request)
    workspace_name = workspace_target["workspace_name"]
    applet_name = f"{entity} {title_case(applet_type)} Applet"
    business_component = entity
    default_view_name = inferred_view_name or f"{entity} View"

    template_map = {
        "list": "Base List Applet",
        "form": "Base Form Applet",
        "tree": "Base Tree Applet",
        "chart": "Base Chart Applet",
    }
    class_map = {
        "list": "CSSFrameListWebApplet",
        "form": "CSSFrameBase",
        "tree": "CSSTree",
        "chart": "CSSFrameListWebApplet",
    }

    bc_field_names = get_bc_field_names(config, business_component, requested_fields) if requested_fields else []
    field_analysis = resolve_field_choices(requested_fields, bc_field_names) if requested_fields and bc_field_names else []
    resolved_fields = [item["resolved_field"] for item in field_analysis if item.get("resolved_field")]
    unresolved_fields = [item["requested_field"] for item in field_analysis if item.get("match_type") == "unresolved"]
    inferred_choices = [
        {"requested_field": item["requested_field"], "resolved_field": item["resolved_field"]}
        for item in field_analysis
        if item.get("match_type") == "inferred"
    ]
    confirm_bc_field_choices = human_in_the_loop_required(
        config,
        overrides,
        workflow_key="confirm_bc_field_choices",
    )
    web_template_map = {
        "list": "CCAppletList",
        "form": "CCAppletForm",
        "tree": "CCAppletTree",
        "chart": "CCAppletChart",
    }

    requires_confirmation = bool(inferred_choices or unresolved_fields) and confirm_bc_field_choices
    missing_connection = effective_missing_connection_fields(connection, workspace_target["workspace_branch"])
    ready_to_create = len(missing_connection) == 0 and not unresolved_fields and not requires_confirmation

    return {
        "request": request,
        "workspace_name": workspace_name,
        "workspace_branch": workspace_target["workspace_branch"],
        "branch_name": workspace_target["branch_name"],
        "workspace_resolution": workspace_target["workspace_resolution"],
        "require_explicit_workspace": workspace_target["require_explicit_workspace"],
        "applet_name": applet_name,
        "business_component": business_component,
        "applet_type": applet_type,
        "fields": resolved_fields if resolved_fields else requested_fields,
        "requested_fields": requested_fields,
        "field_analysis": field_analysis,
        "bc_field_names_checked": len(bc_field_names),
        "unresolved_fields": unresolved_fields,
        "inferred_field_choices": inferred_choices,
        "human_in_the_loop": {
            "confirm_bc_field_choices": confirm_bc_field_choices,
            "requires_confirmation": requires_confirmation,
        },
        "project": overrides.get("project") or defaults.get("default_project") or entity,
        "template_name": overrides.get("template_name")
        or (defaults.get("template_name") if applet_type == "list" else "")
        or template_map[applet_type],
        "class_name": overrides.get("class_name")
        or (defaults.get("class_name") if applet_type == "list" else "")
        or class_map[applet_type],
        "web_template": overrides.get("web_template")
        or (defaults.get("web_template") if applet_type == "list" else "")
        or web_template_map[applet_type],
        "view_name": default_view_name,
        "mode": defaults.get("default_mode", "Base"),
        "tab_name": "",
        "sequence": "",
        "auto_place": bool(overrides.get("auto_place", defaults.get("auto_place_on_view", False))),
        "connection_ready": len(missing_connection) == 0,
        "ready_to_create": ready_to_create,
        "confirmation_message": (
            "Confirm the resolved BC fields before creating the applet."
            if requires_confirmation
            else ""
        ),
        "message": (
            "One or more requested fields could not be mapped to Business Component fields."
            if unresolved_fields
            else ""
        ),
    }


def bool_flag_from_request(request: str, *, enabled_markers: list[str], disabled_markers: list[str], default: str) -> str:
    lowered = request.lower()
    for marker in disabled_markers:
        if marker in lowered:
            return "N"
    for marker in enabled_markers:
        if marker in lowered:
            return "Y"
    return default


def build_business_service_plan(request: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    config = load_config()
    connection = connection_config(config)
    defaults = config.get("defaults", {})
    workspace_target = resolve_workspace_target(config, overrides)

    business_service_name = overrides.get("business_service_name") or extract_business_service_name(request)
    workspace_name = workspace_target["workspace_name"]
    missing_connection = effective_missing_connection_fields(connection, workspace_target["workspace_branch"])

    return {
        "request": request,
        "workspace_name": workspace_name,
        "workspace_branch": workspace_target["workspace_branch"],
        "branch_name": workspace_target["branch_name"],
        "workspace_resolution": workspace_target["workspace_resolution"],
        "require_explicit_workspace": workspace_target["require_explicit_workspace"],
        "business_service_name": business_service_name,
        "project": overrides.get("project") or extract_project_name(request) or defaults.get("default_project") or "00Phoenix",
        "class_name": overrides.get("class_name") or extract_service_class(request) or "CSSService",
        "cache": overrides.get("cache") or bool_flag_from_request(
            request,
            enabled_markers=["cache enabled", "cached", "with cache"],
            disabled_markers=["cache disabled", "without cache", "no cache"],
            default="N",
        ),
        "server_enabled": overrides.get("server_enabled") or bool_flag_from_request(
            request,
            enabled_markers=["server enabled", "server-side", "server side"],
            disabled_markers=["server disabled"],
            default="Y",
        ),
        "web_service_enabled": overrides.get("web_service_enabled") or bool_flag_from_request(
            request,
            enabled_markers=["web service enabled", "expose as web service", "web-service enabled"],
            disabled_markers=["web service disabled"],
            default="N",
        ),
        "hidden": overrides.get("hidden") or bool_flag_from_request(
            request,
            enabled_markers=["hidden"],
            disabled_markers=["not hidden", "visible"],
            default="N",
        ),
        "external_use": overrides.get("external_use") or bool_flag_from_request(
            request,
            enabled_markers=["external use", "external-use", "externally available"],
            disabled_markers=["internal only", "no external use"],
            default="Y",
        ),
        "state_management_type": overrides.get("state_management_type") or "Stateful",
        "browser_class": overrides.get("browser_class", ""),
        "comments": overrides.get("comments") or f"Created from prompt: {business_service_name}",
        "connection_ready": len(missing_connection) == 0,
    }


def build_business_component_plan(request: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    config = load_config()
    connection = connection_config(config)
    defaults = config.get("defaults", {})
    workspace_target = resolve_workspace_target(config, overrides)

    business_component_name = (
        overrides.get("business_component_name") or extract_business_component_name(request)
    )
    workspace_name = workspace_target["workspace_name"]
    missing_connection = effective_missing_connection_fields(connection, workspace_target["workspace_branch"])
    lowered = request.lower()
    read_only = "read only" in lowered or "readonly" in lowered
    explicit_class_name = overrides.get("class_name") or extract_business_component_class(request)
    inferred_table_name = infer_business_component_table(request)
    table_name = overrides.get("table_name") or extract_table_name(request) or inferred_table_name
    inferred_entity = infer_business_component_entity(request)

    return {
        "request": request,
        "workspace_name": workspace_name,
        "workspace_branch": workspace_target["workspace_branch"],
        "branch_name": workspace_target["branch_name"],
        "workspace_resolution": workspace_target["workspace_resolution"],
        "require_explicit_workspace": workspace_target["require_explicit_workspace"],
        "business_component_name": business_component_name,
        "project": overrides.get("project") or extract_project_name(request) or defaults.get("default_project") or "00Phoenix",
        "class_name": explicit_class_name,
        "class_name_strategy": "user_provided" if explicit_class_name else "infer_from_repository_or_default",
        "table_name": table_name,
        "business_entity_hint": inferred_entity,
        "table_name_strategy": (
            "user_provided"
            if overrides.get("table_name") or extract_table_name(request)
            else ("inferred_from_business_entity" if inferred_table_name else "not_set")
        ),
        "no_insert": overrides.get("no_insert") or (
            "Y"
            if read_only
            else bool_flag_from_request(
                request,
                enabled_markers=["no insert", "disallow insert", "insert disabled"],
                disabled_markers=["allow insert", "insert enabled"],
                default="N",
            )
        ),
        "no_update": overrides.get("no_update") or (
            "Y"
            if read_only
            else bool_flag_from_request(
                request,
                enabled_markers=["no update", "disallow update", "update disabled"],
                disabled_markers=["allow update", "update enabled"],
                default="N",
            )
        ),
        "no_delete": overrides.get("no_delete") or (
            "Y"
            if read_only
            else bool_flag_from_request(
                request,
                enabled_markers=["no delete", "disallow delete", "delete disabled"],
                disabled_markers=["allow delete", "delete enabled"],
                default="N",
            )
        ),
        "comments": overrides.get("comments")
        or f"Created by Codex from business component prompt request for {business_component_name}.",
        "connection_ready": len(missing_connection) == 0,
        "ready_to_create": len(missing_connection) == 0,
        "shell_only_scope": True,
        "business_user_prompt_supported": True,
        "needs_business_entity_or_table": not bool(table_name),
    }


def build_workflow_plan(request: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    config = load_config()
    connection = connection_config(config)
    defaults = config.get("defaults", {})
    workspace_target = resolve_workspace_target(config, overrides)

    workflow_name = overrides.get("workflow_name") or extract_workflow_name(request)
    workspace_name = workspace_target["workspace_name"]
    business_object = overrides.get("business_object") or extract_business_object_name(request) or "Service Request"
    missing_connection = effective_missing_connection_fields(connection, workspace_target["workspace_branch"])

    return {
        "request": request,
        "workspace_name": workspace_name,
        "workspace_branch": workspace_target["workspace_branch"],
        "branch_name": workspace_target["branch_name"],
        "workspace_resolution": workspace_target["workspace_resolution"],
        "require_explicit_workspace": workspace_target["require_explicit_workspace"],
        "workflow_name": workflow_name,
        "project": overrides.get("project")
        or extract_project_name(request)
        or defaults.get("default_workflow_project")
        or "00Phoenix",
        "business_object": business_object,
        "workflow_mode": overrides.get("workflow_mode") or infer_workflow_mode(request),
        "runnable": overrides.get("runnable")
        or bool_flag_from_request(
            request,
            enabled_markers=["runnable", "run it", "executable"],
            disabled_markers=["not runnable", "non-runnable", "do not run"],
            default="Y",
        ),
        "state_management_type": overrides.get("state_management_type") or (
            "Stateless" if "stateless" in request.lower() else "Stateful"
        ),
        "web_service_enabled": overrides.get("web_service_enabled")
        or bool_flag_from_request(
            request,
            enabled_markers=["web service enabled", "expose as web service", "call as web service"],
            disabled_markers=["web service disabled"],
            default="N",
        ),
        "pass_by_ref_hierarchy_argument": overrides.get("pass_by_ref_hierarchy_argument")
        or bool_flag_from_request(
            request,
            enabled_markers=["pass by ref", "pass-by-ref"],
            disabled_markers=["no pass by ref", "without pass by ref"],
            default="N",
        ),
        "replication_level": overrides.get("replication_level") or "None",
        "status": overrides.get("status") or (
            "Completed" if "completed workflow" in request.lower() else "In Progress"
        ),
        "inactive": overrides.get("inactive")
        or bool_flag_from_request(
            request,
            enabled_markers=["inactive", "disabled workflow"],
            disabled_markers=["active", "not inactive"],
            default="N",
        ),
        "description": overrides.get("description")
        or f"Workflow created from prompt: {request.strip()}",
        "comments": overrides.get("comments")
        or f"Created by Codex from workflow prompt request for {business_object}.",
        "connection_ready": len(missing_connection) == 0,
        "ready_to_create": len(missing_connection) == 0,
    }


def run_adapter(command_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    connection = connection_config(config)
    workspace_target = resolve_workspace_target(config, payload)

    command = ["python3", str(ADAPTER_SCRIPT), command_name]
    mapping = {
        "test-connection": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "session_id",
            "verify_tls",
        ],
        "create-workspace": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "verify_tls",
            "workspace_name",
            "branch_name",
            "reason",
        ],
        "create-applet": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "verify_tls",
            "workspace_name",
            "applet_name",
            "business_component",
            "applet_type",
            "project",
            "template_name",
            "class_name",
            "web_template",
            "fields_json",
        ],
        "add-applet-to-view": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "verify_tls",
            "workspace_name",
            "view_name",
            "applet_name",
            "mode",
            "tab_name",
            "sequence",
        ],
        "create-view-on-screen": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "verify_tls",
            "workspace_name",
            "view_name",
            "screen_name",
            "source_view_name",
            "applet_name",
            "project",
        ],
        "create-business-service": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "verify_tls",
            "workspace_name",
            "business_service_name",
            "project",
            "class_name",
            "cache",
            "server_enabled",
            "web_service_enabled",
            "state_management_type",
            "hidden",
            "external_use",
            "browser_class",
            "comments",
        ],
        "create-business-component": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "verify_tls",
            "workspace_name",
            "business_component_name",
            "project",
            "class_name",
            "table_name",
            "no_insert",
            "no_update",
            "no_delete",
            "comments",
        ],
        "create-workflow": [
            "oracle_guid",
            "webtools_url",
            "workspace_branch",
            "username",
            "password",
            "verify_tls",
            "workspace_name",
            "workflow_name",
            "project",
            "business_object",
            "workflow_mode",
            "runnable",
            "state_management_type",
            "web_service_enabled",
            "pass_by_ref_hierarchy_argument",
            "replication_level",
            "status",
            "inactive",
            "description",
            "comments",
        ],
    }

    merged_payload = dict(payload)
    if workspace_target["workspace_branch"]:
        merged_payload["workspace_branch"] = workspace_target["workspace_branch"]
    if workspace_target["workspace_name"]:
        merged_payload["workspace_name"] = merged_payload.get("workspace_name") or workspace_target["workspace_name"]
    if "branch_name" in merged_payload and not merged_payload.get("branch_name"):
        merged_payload["branch_name"] = workspace_target["workspace_branch"]
    if "fields" in merged_payload and "fields_json" not in merged_payload:
        merged_payload["fields_json"] = json.dumps(merged_payload.get("fields", []))

    for key in mapping.get(command_name, []):
        value = merged_payload.get(key, connection.get(key, ""))
        if value is None:
            continue
        command.extend([f"--{key.replace('_', '-')}", str(value)])

    completed = subprocess.run(
        command,
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    parsed: dict[str, Any] | None = None
    if stdout:
        try:
            raw = json.loads(stdout)
            if isinstance(raw, dict):
                parsed = raw
        except json.JSONDecodeError:
            parsed = None

    result_payload: dict[str, Any] = {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    if parsed is not None:
        result_payload["parsed"] = parsed

    if completed.returncode != 0:
        return {
            "content": [{"type": "text", "text": json.dumps(result_payload, indent=2, sort_keys=True)}],
            "structuredContent": result_payload,
            "isError": True,
        }

    return {
        "content": [{"type": "text", "text": json.dumps(result_payload, indent=2, sort_keys=True)}],
        "structuredContent": result_payload,
    }


def render_text(title: str, payload: Any) -> dict[str, Any]:
    pretty = json.dumps(payload, indent=2, sort_keys=True)
    return {
        "content": [{"type": "text", "text": f"{title}\n{pretty}"}],
        "structuredContent": payload if isinstance(payload, dict) else {"value": payload},
    }


def handle_describe_setup() -> dict[str, Any]:
    config = load_config()
    connection = connection_config(config)
    workflow = workflow_config(config)
    targeting = targeting_config(config)
    missing = required_connection_fields(connection)
    result = {
        "config_path": str(DEFAULT_CONFIG),
        "config_exists": DEFAULT_CONFIG.exists(),
        "connection": sanitize_connection(connection),
        "workflow": workflow,
        "targeting": targeting,
        "missing_required_fields": missing,
        "ready": len(missing) == 0,
        "guidance": [
            "Fill in Oracle GUID, Web Tools URL, workspace branch, username, and password in scripts/siebel_open_ui.config.json.",
            "Use workflow.human_in_the_loop.confirm_bc_field_choices to require a human confirmation step when the plugin maps prompt field names to Business Component fields.",
            "Use targeting.require_explicit_workspace to force every run to name the workspace branch explicitly instead of defaulting to config.",
            "Use validate_workspace_target before making changes when you need to confirm that a view and its referenced applets resolve in the selected branch.",
            "If the environment uses an internal or self-signed certificate, either install the CA locally or set verify_tls to false.",
            "Then ask in chat for what you want, for example: create an opportunity list applet that includes Name, Revenue, and Stage.",
            "The plugin can also plan and create shell business components from business-facing prompts, for example: create a contact capture business component for contacts.",
            "Do not worry about Siebel class names for business components. The plugin infers the class from live repository patterns when possible and falls back safely when it cannot.",
            "The plugin can also plan and create business services, for example: create a business service called Prospect Sync Service using class CSSService.",
            "The plugin can also plan and create workflows, for example: create a workflow named SR Assignment Workflow for the Service Request business object.",
            "Use plan_applet_request, plan_business_component_request, plan_business_service_request, or plan_workflow_request first when you want to review inferred details before execution.",
        ],
    }
    return render_text("Siebel plugin setup", result)


def handle_test_connection() -> dict[str, Any]:
    config = load_config()
    missing = required_connection_fields(config.get("connection", {}))
    if missing:
        return render_text(
            "Siebel connection incomplete",
            {
                "ok": False,
                "missing_required_fields": missing,
                "message": "Populate the missing connection fields before testing.",
            },
        ) | {"isError": True}
    return run_adapter("test-connection", {})


def handle_validate_workspace_target(arguments: dict[str, Any]) -> dict[str, Any]:
    result = validate_workspace_target_details(arguments)
    title = "Siebel workspace target validation"
    rendered = render_text(title, result)
    if not result["ok"]:
        rendered["isError"] = True
    return rendered


def handle_plan_applet_request(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_plan(arguments["request"], arguments)
    return render_text("Siebel applet plan", plan)


def handle_plan_business_component_request(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_business_component_plan(arguments["request"], arguments)
    return render_text("Siebel business component plan", plan)


def handle_plan_business_service_request(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_business_service_plan(arguments["request"], arguments)
    return render_text("Siebel business service plan", plan)


def handle_plan_workflow_request(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_workflow_plan(arguments["request"], arguments)
    return render_text("Siebel workflow plan", plan)


def handle_create_workspace(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "branch_name": arguments.get("branch_name", ""),
        "reason": arguments.get("reason", "Created from Codex"),
    }
    return run_adapter("create-workspace", payload)


def handle_create_applet(arguments: dict[str, Any]) -> dict[str, Any]:
    preflight_error = preflight_workspace_target(arguments)
    if preflight_error:
        return preflight_error
    payload = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "applet_name": arguments.get("applet_name", ""),
        "business_component": arguments.get("business_component", ""),
        "applet_type": arguments.get("applet_type", "list"),
        "fields": arguments.get("fields", []),
        "project": arguments.get("project", ""),
        "template_name": arguments.get("template_name", ""),
        "class_name": arguments.get("class_name", ""),
        "web_template": arguments.get("web_template", ""),
    }
    return run_adapter("create-applet", payload)


def handle_add_applet_to_view(arguments: dict[str, Any]) -> dict[str, Any]:
    preflight_error = preflight_workspace_target(arguments, require_view_resolution=True)
    if preflight_error:
        return preflight_error
    payload = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "view_name": arguments.get("view_name", ""),
        "applet_name": arguments.get("applet_name", ""),
        "mode": arguments.get("mode", "Base"),
        "tab_name": arguments.get("tab_name", ""),
        "sequence": arguments.get("sequence", ""),
    }
    return run_adapter("add-applet-to-view", payload)


def handle_create_view_on_screen(arguments: dict[str, Any]) -> dict[str, Any]:
    preflight_error = preflight_workspace_target(arguments)
    if preflight_error:
        return preflight_error
    payload = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "view_name": arguments.get("view_name", ""),
        "screen_name": arguments.get("screen_name", ""),
        "source_view_name": arguments.get("source_view_name", "All Opportunity List View"),
        "applet_name": arguments.get("applet_name", ""),
        "project": arguments.get("project", ""),
    }
    return run_adapter("create-view-on-screen", payload)


def handle_create_business_service(arguments: dict[str, Any]) -> dict[str, Any]:
    preflight_error = preflight_workspace_target(arguments)
    if preflight_error:
        return preflight_error
    payload = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "business_service_name": arguments.get("business_service_name", ""),
        "project": arguments.get("project", ""),
        "class_name": arguments.get("class_name", ""),
        "cache": arguments.get("cache", ""),
        "server_enabled": arguments.get("server_enabled", ""),
        "web_service_enabled": arguments.get("web_service_enabled", ""),
        "state_management_type": arguments.get("state_management_type", ""),
        "hidden": arguments.get("hidden", ""),
        "external_use": arguments.get("external_use", ""),
        "browser_class": arguments.get("browser_class", ""),
        "comments": arguments.get("comments", ""),
    }
    return run_adapter("create-business-service", payload)


def handle_create_business_component(arguments: dict[str, Any]) -> dict[str, Any]:
    preflight_error = preflight_workspace_target(arguments)
    if preflight_error:
        return preflight_error
    payload = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "business_component_name": arguments.get("business_component_name", ""),
        "project": arguments.get("project", ""),
        "class_name": arguments.get("class_name", ""),
        "table_name": arguments.get("table_name", ""),
        "no_insert": arguments.get("no_insert", ""),
        "no_update": arguments.get("no_update", ""),
        "no_delete": arguments.get("no_delete", ""),
        "comments": arguments.get("comments", ""),
    }
    return run_adapter("create-business-component", payload)


def handle_create_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    preflight_error = preflight_workspace_target(arguments)
    if preflight_error:
        return preflight_error
    payload = {
        "workspace_name": arguments.get("workspace_name", ""),
        "workspace_branch": arguments.get("workspace_branch", ""),
        "workflow_name": arguments.get("workflow_name", ""),
        "project": arguments.get("project", ""),
        "business_object": arguments.get("business_object", ""),
        "workflow_mode": arguments.get("workflow_mode", ""),
        "runnable": arguments.get("runnable", ""),
        "state_management_type": arguments.get("state_management_type", ""),
        "web_service_enabled": arguments.get("web_service_enabled", ""),
        "pass_by_ref_hierarchy_argument": arguments.get("pass_by_ref_hierarchy_argument", ""),
        "replication_level": arguments.get("replication_level", ""),
        "status": arguments.get("status", ""),
        "inactive": arguments.get("inactive", ""),
        "description": arguments.get("description", ""),
        "comments": arguments.get("comments", ""),
    }
    return run_adapter("create-workflow", payload)


def handle_create_applet_from_prompt(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_plan(arguments["request"], arguments)

    if plan["unresolved_fields"]:
        return render_text(
            "Siebel prompt execution blocked",
            {
                "plan": plan,
                "message": "The request includes fields that could not be mapped to the Business Component. Confirm the right BC fields before creating the applet.",
            },
        ) | {"isError": True}

    if plan["human_in_the_loop"]["requires_confirmation"] and not arguments.get("confirmed_field_choices", False):
        return render_text(
            "Siebel applet confirmation required",
            {
                "plan": plan,
                "message": "Human confirmation is required before the applet is created because the plugin inferred one or more BC field choices.",
                "next_step": "Review plan.field_analysis and rerun with confirmed_field_choices=true after approval.",
            },
        )

    preflight_error = preflight_workspace_target(
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "view_name": plan["view_name"] if plan["auto_place"] else "",
        },
        require_view_resolution=plan["auto_place"],
    )
    if preflight_error:
        return preflight_error

    workspace_result = run_adapter(
        "create-workspace",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "branch_name": plan["branch_name"],
            "reason": f"Prompt request: {plan['request']}",
        },
    )
    if workspace_result.get("isError"):
        return workspace_result

    applet_result = run_adapter(
        "create-applet",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "applet_name": plan["applet_name"],
            "business_component": plan["business_component"],
            "applet_type": plan["applet_type"],
            "fields": plan["fields"],
            "project": plan["project"],
            "template_name": plan["template_name"],
            "class_name": plan["class_name"],
            "web_template": plan["web_template"],
        },
    )
    if applet_result.get("isError"):
        return applet_result

    placement_result: dict[str, Any] | None = None
    if plan["auto_place"]:
        placement_result = run_adapter(
            "add-applet-to-view",
            {
                "workspace_name": plan["workspace_name"],
                "workspace_branch": plan["workspace_branch"],
                "view_name": plan["view_name"],
                "applet_name": plan["applet_name"],
                "mode": plan["mode"],
                "tab_name": plan["tab_name"],
                "sequence": plan["sequence"],
            },
        )
        if placement_result.get("isError"):
            return placement_result

    result = {
        "plan": plan,
        "workspace_result": workspace_result.get("structuredContent", {}),
        "applet_result": applet_result.get("structuredContent", {}),
        "placement_result": placement_result.get("structuredContent", {}) if placement_result else None,
    }
    return render_text("Siebel prompt execution", result)


def handle_create_business_service_from_prompt(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_business_service_plan(arguments["request"], arguments)

    preflight_error = preflight_workspace_target(
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
        }
    )
    if preflight_error:
        return preflight_error

    workspace_result = run_adapter(
        "create-workspace",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "branch_name": plan["branch_name"],
            "reason": f"Prompt request: {plan['request']}",
        },
    )
    if workspace_result.get("isError"):
        return workspace_result

    business_service_result = run_adapter(
        "create-business-service",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "business_service_name": plan["business_service_name"],
            "project": plan["project"],
            "class_name": plan["class_name"],
            "cache": plan["cache"],
            "server_enabled": plan["server_enabled"],
            "web_service_enabled": plan["web_service_enabled"],
            "state_management_type": plan["state_management_type"],
            "hidden": plan["hidden"],
            "external_use": plan["external_use"],
            "browser_class": plan["browser_class"],
            "comments": plan["comments"],
        },
    )
    if business_service_result.get("isError"):
        return business_service_result

    result = {
        "plan": plan,
        "workspace_result": workspace_result.get("structuredContent", {}),
        "business_service_result": business_service_result.get("structuredContent", {}),
    }
    return render_text("Siebel business service prompt execution", result)


def handle_create_business_component_from_prompt(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_business_component_plan(arguments["request"], arguments)

    if plan["needs_business_entity_or_table"]:
        return render_text(
            "Siebel business component prompt needs business context",
            {
                "plan": plan,
                "message": "The request does not clearly identify what business entity this component is for. Specify the business entity, such as contacts, accounts, opportunities, service requests, or orders, or provide the base table.",
                "next_step": "Rerun with a business-facing clarification like 'for contacts' or with an explicit base table.",
            },
        ) | {"isError": True}

    preflight_error = preflight_workspace_target(
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
        }
    )
    if preflight_error:
        return preflight_error

    workspace_result = run_adapter(
        "create-workspace",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "branch_name": plan["branch_name"],
            "reason": f"Prompt request: {plan['request']}",
        },
    )
    if workspace_result.get("isError"):
        return workspace_result

    business_component_result = run_adapter(
        "create-business-component",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "business_component_name": plan["business_component_name"],
            "project": plan["project"],
            "class_name": plan["class_name"],
            "table_name": plan["table_name"],
            "no_insert": plan["no_insert"],
            "no_update": plan["no_update"],
            "no_delete": plan["no_delete"],
            "comments": plan["comments"],
        },
    )
    if business_component_result.get("isError"):
        return business_component_result

    result = {
        "plan": plan,
        "workspace_result": workspace_result.get("structuredContent", {}),
        "business_component_result": business_component_result.get("structuredContent", {}),
    }
    return render_text("Siebel business component prompt execution", result)


def handle_create_workflow_from_prompt(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = build_workflow_plan(arguments["request"], arguments)

    preflight_error = preflight_workspace_target(
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
        }
    )
    if preflight_error:
        return preflight_error

    workspace_result = run_adapter(
        "create-workspace",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "branch_name": plan["branch_name"],
            "reason": f"Prompt request: {plan['request']}",
        },
    )
    if workspace_result.get("isError"):
        return workspace_result

    workflow_result = run_adapter(
        "create-workflow",
        {
            "workspace_name": plan["workspace_name"],
            "workspace_branch": plan["workspace_branch"],
            "workflow_name": plan["workflow_name"],
            "project": plan["project"],
            "business_object": plan["business_object"],
            "workflow_mode": plan["workflow_mode"],
            "runnable": plan["runnable"],
            "state_management_type": plan["state_management_type"],
            "web_service_enabled": plan["web_service_enabled"],
            "pass_by_ref_hierarchy_argument": plan["pass_by_ref_hierarchy_argument"],
            "replication_level": plan["replication_level"],
            "status": plan["status"],
            "inactive": plan["inactive"],
            "description": plan["description"],
            "comments": plan["comments"],
        },
    )
    if workflow_result.get("isError"):
        return workflow_result

    result = {
        "plan": plan,
        "workspace_result": workspace_result.get("structuredContent", {}),
        "workflow_result": workflow_result.get("structuredContent", {}),
    }
    return render_text("Siebel workflow prompt execution", result)


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "siebel-open-ui", "version": "0.2.0"},
        }
        return response(message_id, result)

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return response(message_id, {})

    if method == "tools/list":
        return response(message_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        handlers = {
            "describe_setup": lambda: handle_describe_setup(),
            "test_connection": lambda: handle_test_connection(),
            "validate_workspace_target": lambda: handle_validate_workspace_target(arguments),
            "plan_applet_request": lambda: handle_plan_applet_request(arguments),
            "plan_business_component_request": lambda: handle_plan_business_component_request(arguments),
            "plan_business_service_request": lambda: handle_plan_business_service_request(arguments),
            "plan_workflow_request": lambda: handle_plan_workflow_request(arguments),
            "create_applet_from_prompt": lambda: handle_create_applet_from_prompt(arguments),
            "create_business_component_from_prompt": lambda: handle_create_business_component_from_prompt(arguments),
            "create_business_service_from_prompt": lambda: handle_create_business_service_from_prompt(arguments),
            "create_workflow_from_prompt": lambda: handle_create_workflow_from_prompt(arguments),
            "create_workspace": lambda: handle_create_workspace(arguments),
            "create_applet": lambda: handle_create_applet(arguments),
            "create_business_component": lambda: handle_create_business_component(arguments),
            "create_business_service": lambda: handle_create_business_service(arguments),
            "create_workflow": lambda: handle_create_workflow(arguments),
            "add_applet_to_view": lambda: handle_add_applet_to_view(arguments),
            "create_view_on_screen": lambda: handle_create_view_on_screen(arguments),
        }

        if tool_name not in handlers:
            return response(
                message_id,
                {
                    "content": [{"type": "text", "text": f"Unknown tool '{tool_name}'."}],
                    "isError": True,
                },
            )

        return response(message_id, handlers[tool_name]())

    return error_response(message_id, -32601, f"Method not found: {method}")


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        reply = handle_request(message)
        if reply is not None:
            send_message(reply)


if __name__ == "__main__":
    raise SystemExit(main())
