#!/usr/bin/env python3
"""Real Siebel Web Tools REST adapter for the Siebel Open UI plugin."""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

SEGMENT_ALIASES = {
    "WF Step I/O Argument": "IO Argument",
    "I/O Argument": "IO Argument",
}

PATH_ALIASES = (
    ("/null/O%20Argument", "/IO%20Argument"),
    ("/null/O Argument", "/IO Argument"),
)


@dataclass
class ConnectionConfig:
    oracle_guid: str
    webtools_url: str
    workspace_branch: str
    username: str
    password: str
    verify_tls: bool = True


class SiebelRestError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.details = details


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def sanitize_url(webtools_url: str, workspace_branch: str) -> str:
    parsed = urllib.parse.urlparse(webtools_url)
    path = parsed.path.rstrip("/")
    marker = "/workspace/"
    if marker in path:
        prefix = path.split(marker, 1)[0]
        normalized_path = f"{prefix}{marker}{workspace_branch}"
    else:
        normalized_path = f"{path}{marker}{workspace_branch}"
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, normalized_path, "", "", "")
    )


def auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def parse_body(raw: bytes) -> Any:
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def make_request(
    conn: ConnectionConfig,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", auth_header(conn.username, conn.password))
    if body is not None:
        request.add_header("Content-Type", "application/json")

    ssl_context = ssl.create_default_context()
    if not conn.verify_tls:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(request, context=ssl_context, timeout=60) as response:
            response_body = parse_body(response.read())
            headers = {key: value for key, value in response.headers.items()}
            return response.getcode(), response_body, headers
    except urllib.error.HTTPError as exc:
        response_body = parse_body(exc.read())
        raise SiebelRestError(
            f"Siebel REST request failed with HTTP {exc.code}",
            status=exc.code,
            details={"url": url, "body": response_body},
        ) from exc
    except urllib.error.URLError as exc:
        raise SiebelRestError(f"Unable to reach Siebel Web Tools endpoint: {exc.reason}") from exc


def workspace_base(conn: ConnectionConfig, branch_name: str | None = None) -> str:
    return sanitize_url(conn.webtools_url, branch_name or conn.workspace_branch).rstrip("/")


def encode_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def normalize_segment(value: str) -> str:
    return SEGMENT_ALIASES.get(value, value)


def normalize_path_aliases(path: str) -> str:
    normalized = path
    for source, target in PATH_ALIASES:
        normalized = normalized.replace(source, target)
    return normalized


def build_path(*segments: str) -> str:
    parts: list[str] = []
    for segment in segments:
        cleaned = segment.strip("/")
        if not cleaned:
            continue
        parts.append(encode_path(normalize_segment(cleaned)))
    return "/".join(parts)


def request_json(
    conn: ConnectionConfig,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    branch_name: str | None = None,
) -> dict[str, Any]:
    base = workspace_base(conn, branch_name)
    normalized_path = normalize_path_aliases(path.lstrip("/"))
    status, body, headers = make_request(conn, method, f"{base}/{normalized_path}", payload)
    return {"status": status, "body": body, "headers": headers, "url": f"{base}/{normalized_path}"} 


def fetch_resource_list(
    conn: ConnectionConfig,
    resource: str,
    *,
    params: dict[str, Any] | None = None,
    branch_name: str | None = None,
) -> dict[str, Any]:
    base = workspace_base(conn, branch_name)
    query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value not in (None, "")})
    suffix = f"{build_path(*(urllib.parse.unquote(segment) for segment in resource.strip('/').split('/')))}/"
    suffix = normalize_path_aliases(suffix)
    url = f"{base}/{suffix}"
    if query:
        url = f"{url}?{query}"
    status, body, headers = make_request(conn, "GET", url)
    return {"status": status, "body": body, "headers": headers, "url": url}


def get_describe(conn: ConnectionConfig, path: str = "describe", *, branch_name: str | None = None) -> dict[str, Any]:
    return request_json(conn, "GET", path, branch_name=branch_name)


def build_applet_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "Name": args.applet_name,
        "ProjectName": args.project or args.business_component,
        "UpgradeBehavior": "Preserve",
        "Height": args.height,
        "Width": args.width,
        "Comments": f"Created by Codex for {args.business_component}",
    }
    if args.business_component:
        payload["Business Component"] = args.business_component
    if args.class_name:
        payload["Class"] = args.class_name
    return payload


def build_list_column_payload(field_name: str, project_name: str, index: int) -> dict[str, Any]:
    return {
        "Name": field_name,
        "Field": field_name,
        "Available": "Y",
        "HTML Only": "N",
        "HTML Row Sensitive": "Y",
        "Show Popup": "N",
        "Show In List": "Y",
        "Type": "TextBox",
        "Width": "15",
        "Comments": f"Created by Codex for field {field_name}",
        "Sequence": str(index),
    }


def build_control_payload(field_name: str, project_name: str, index: int) -> dict[str, Any]:
    return {
        "Name": field_name,
        "Field": field_name,
        "Caption": field_name,
        "ProjectName": project_name,
        "Type": "TextBox",
        "HTML Type": "Text",
        "UpgradeBehavior": "Preserve",
        "Comments": f"Created by Codex for field {field_name}",
        "HTML Sequence": index,
        "HTML Width": "200",
    }


def build_view_item_payload(applet_name: str, slot_name: str, mode: str) -> dict[str, Any]:
    return {
        "Name": slot_name,
        "Applet": applet_name,
        "Applet Mode": mode or "Base",
        "Comments": f"Placed by Codex: {applet_name}",
    }


def build_business_service_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "Name": args.business_service_name,
        "ProjectName": args.project,
        "Class": args.class_name,
        "Cache": args.cache,
        "Server Enabled": args.server_enabled,
        "Web Service Enabled": args.web_service_enabled,
        "State Management Type": args.state_management_type,
        "Hidden": args.hidden,
        "External Use": args.external_use,
        "Comments": args.comments or f"Created by Codex business service {args.business_service_name}",
        "Browser Class": args.browser_class,
    }


def build_business_component_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "Name": args.business_component_name,
        "ProjectName": args.project,
        "Class": args.class_name,
        "Table": args.table_name,
        "No Insert": args.no_insert,
        "No Update": args.no_update,
        "No Delete": args.no_delete,
        "Comments": args.comments or f"Created by Codex business component {args.business_component_name}",
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def build_workflow_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "Name": args.workflow_name,
        "Process Name": args.workflow_name,
        "Project Name": args.project,
        "Business Object": args.business_object,
        "Workflow Mode": args.workflow_mode,
        "Runnable": args.runnable,
        "State Management Type": args.state_management_type,
        "Web Service Enabled": args.web_service_enabled,
        "Pass By Ref Hierarchy Argument": args.pass_by_ref_hierarchy_argument,
        "Replication Level": args.replication_level,
        "Status": args.status,
        "Inactive": args.inactive,
        "Comments": args.comments or f"Created by Codex workflow {args.workflow_name}",
        "Description": args.description,
    }


def clone_payload(source: dict[str, Any], allowed_fields: list[str], overrides: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in allowed_fields:
        value = source.get(field, "")
        if value not in (None, ""):
            payload[field] = value
    payload.update({key: value for key, value in overrides.items() if value not in (None, "")})
    return payload


def copy_if_present(payload: dict[str, Any], source: dict[str, Any], source_key: str, target_key: str | None = None) -> None:
    value = source.get(source_key)
    if value not in (None, ""):
        payload[target_key or source_key] = value


def list_items(
    conn: ConnectionConfig,
    resource: str,
    *,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = fetch_resource_list(
        conn,
        resource,
        params={"uniformresponse": "Y", "pagination": "Y", "PageSize": 100, "StartRowNum": 0, **(params or {})},
    )
    body = result["body"]
    if isinstance(body, dict):
        items = body.get("items", [])
        if isinstance(items, list):
            return items
    return []


def get_resource(conn: ConnectionConfig, *segments: str) -> dict[str, Any]:
    return request_json(conn, "GET", build_path(*segments))["body"]


def put_resource(conn: ConnectionConfig, payload: dict[str, Any], *segments: str) -> dict[str, Any]:
    return request_json(conn, "PUT", build_path(*segments), payload)


def replace_applet_name(value: Any, source_applet: str, target_applet: str) -> Any:
    if not isinstance(value, str):
        return value
    return target_applet if value == source_applet else value


def next_sequence(items: list[dict[str, Any]], *, parent_category: str) -> str:
    sequences: list[int] = []
    for item in items:
        if str(item.get("Parent Category", "")).strip() != parent_category:
            continue
        try:
            sequences.append(int(str(item.get("Sequence", "")).strip()))
        except ValueError:
            continue
    return str(max(sequences, default=0) + 1)


def parse_fields(fields_json: str) -> list[str]:
    if not fields_json:
        return []
    try:
        value = json.loads(fields_json)
    except json.JSONDecodeError:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def search_existing_applets(
    conn: ConnectionConfig,
    business_component: str,
    applet_type: str,
) -> list[dict[str, Any]]:
    searchspec = f"[Business Component] = '{business_component}'"
    result = fetch_resource_list(
        conn,
        "Applet",
        params={
            "searchspec": searchspec,
            "PageSize": 20,
            "StartRowNum": 0,
            "uniformresponse": "Y",
            "pagination": "Y",
        },
    )
    body = result["body"]
    items = body.get("items", []) if isinstance(body, dict) else []
    desired_list_name = {
        "list": "List",
        "form": "",
    }.get(applet_type, "")

    filtered: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("Business Component", "")).strip() != business_component:
            continue
        if applet_type == "list" and str(item.get("List Name", "")).strip() != "List":
            continue
        if applet_type == "form" and str(item.get("List Name", "")).strip() == "List":
            continue
        if desired_list_name and str(item.get("List Name", "")).strip() != desired_list_name:
            continue
        filtered.append(item)
    return filtered or items


def search_existing_business_services(
    conn: ConnectionConfig,
    *,
    class_name: str = "",
) -> list[dict[str, Any]]:
    params = {
        "PageSize": 20,
        "StartRowNum": 0,
        "uniformresponse": "Y",
        "pagination": "Y",
    }
    if class_name:
        params["searchspec"] = f"[Class] = '{class_name}'"
    result = fetch_resource_list(conn, "Business Service", params=params)
    body = result["body"]
    items = body.get("items", []) if isinstance(body, dict) else []
    if class_name:
        return [item for item in items if str(item.get("Class", "")).strip() == class_name]
    return items


def infer_applet_defaults(
    conn: ConnectionConfig,
    business_component: str,
    applet_type: str,
) -> dict[str, str]:
    candidates = search_existing_applets(conn, business_component, applet_type)
    if candidates:
        first = candidates[0]
        inferred = {
            "class_name": str(first.get("Class", "")).strip(),
            "height": str(first.get("Height", "")).strip() or ("4" if applet_type == "list" else "1"),
            "width": str(first.get("Width", "")).strip() or "2",
            "project": str(first.get("Project Name", "")).strip(),
        }
        return inferred

    fallback_class = {
        "list": "CSSFrameList",
        "form": "CSSFrameBase",
        "tree": "CSSTree",
        "chart": "CSSFrameList",
    }.get(applet_type, "CSSFrameBase")
    fallback_height = "4" if applet_type == "list" else "1"
    return {
        "class_name": fallback_class,
        "height": fallback_height,
        "width": "2",
        "project": "",
    }


def infer_business_service_defaults(
    conn: ConnectionConfig,
    *,
    class_name: str = "",
) -> dict[str, str]:
    if not class_name:
        return {
            "class_name": "CSSService",
            "project": "",
            "cache": "N",
            "server_enabled": "Y",
            "web_service_enabled": "N",
            "state_management_type": "Stateful",
            "hidden": "N",
            "external_use": "Y",
            "browser_class": "",
        }

    candidates = search_existing_business_services(conn, class_name=class_name)
    preferred = None
    for item in candidates:
        if str(item.get("Hidden", "N")).strip() == "N":
            preferred = item
            break
    if preferred is None and candidates:
        preferred = candidates[0]

    if preferred:
        return {
            "class_name": str(preferred.get("Class", "")).strip() or "CSSService",
            "project": str(preferred.get("Project Name", "")).strip(),
            "cache": str(preferred.get("Cache", "")).strip() or "N",
            "server_enabled": str(preferred.get("Server Enabled", "")).strip() or "Y",
            "web_service_enabled": str(preferred.get("Web Service Enabled", "")).strip() or "N",
            "state_management_type": str(preferred.get("State Management Type", "")).strip() or "Stateful",
            "hidden": str(preferred.get("Hidden", "")).strip() or "N",
            "external_use": str(preferred.get("External Use", "")).strip() or "Y",
            "browser_class": str(preferred.get("Browser Class", "")).strip(),
        }

    return {
        "class_name": class_name or "CSSService",
        "project": "",
        "cache": "N",
        "server_enabled": "Y",
        "web_service_enabled": "N",
        "state_management_type": "Stateful",
        "hidden": "N",
        "external_use": "Y",
        "browser_class": "",
    }


def search_existing_business_components(
    conn: ConnectionConfig,
    *,
    table_name: str = "",
    class_name: str = "",
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "PageSize": 20,
        "StartRowNum": 0,
        "uniformresponse": "Y",
        "pagination": "Y",
    }
    search_clauses: list[str] = []
    if table_name:
        search_clauses.append(f"[Table] = '{table_name}'")
    if class_name:
        search_clauses.append(f"[Class] = '{class_name}'")
    if search_clauses:
        params["searchspec"] = " AND ".join(search_clauses)
    result = fetch_resource_list(conn, "Business Component", params=params)
    body = result["body"]
    items = body.get("items", []) if isinstance(body, dict) else []
    return items


def infer_business_component_defaults(
    conn: ConnectionConfig,
    *,
    table_name: str = "",
    class_name: str = "",
) -> dict[str, str]:
    candidates = search_existing_business_components(conn, table_name=table_name, class_name=class_name)
    preferred = candidates[0] if candidates else None

    if preferred:
        return {
            "class_name": str(preferred.get("Class", "")).strip() or class_name or "CSSBCBase",
            "project": str(preferred.get("Project Name", "")).strip(),
            "table_name": str(preferred.get("Table", "")).strip() or table_name,
            "no_insert": str(preferred.get("No Insert", "")).strip() or "N",
            "no_update": str(preferred.get("No Update", "")).strip() or "N",
            "no_delete": str(preferred.get("No Delete", "")).strip() or "N",
        }

    return {
        "class_name": class_name or "CSSBCBase",
        "project": "",
        "table_name": table_name,
        "no_insert": "N",
        "no_update": "N",
        "no_delete": "N",
    }


def discover_child_path(conn: ConnectionConfig, parent_type: str, parent_name: str, child_type: str) -> str:
    child_type = normalize_segment(child_type)
    direct_path = build_path(parent_type, parent_name, child_type)
    try:
        get_describe(conn, f"{direct_path}/describe")
        return direct_path
    except SiebelRestError:
        describe = get_describe(conn, f"{parent_type}/{encode_path(parent_name)}/describe")
        body = describe["body"]
        if isinstance(body, dict):
            paths = body.get("paths", {})
            if isinstance(paths, dict):
                child_marker = f"/{child_type}/"
                for candidate in paths:
                    if child_marker in candidate and "{key}" in candidate and not candidate.endswith("/describe"):
                        return candidate.lstrip("/")
        raise SiebelRestError(
            f"Unable to locate child repository path for {child_type} under {parent_type}/{parent_name}.",
            details={"parent_type": parent_type, "parent_name": parent_name, "child_type": child_type},
        )


def get_resource_if_exists(conn: ConnectionConfig, path: str) -> dict[str, Any] | None:
    try:
        return request_json(conn, "GET", path)
    except SiebelRestError as exc:
        if exc.status == 404:
            return None
        raise


def ensure_workspace_exists(conn: ConnectionConfig, branch_name: str) -> dict[str, Any]:
    describe = get_describe(conn, "describe", branch_name=branch_name)
    return {
        "ok": True,
        "workspace_name": branch_name,
        "status": "available",
        "describe_url": describe["url"],
        "message": "Repository workspace branch is reachable.",
    }


def create_business_service(conn: ConnectionConfig, args: argparse.Namespace) -> dict[str, Any]:
    inferred = infer_business_service_defaults(conn, class_name=getattr(args, "class_name", ""))
    if not args.class_name:
        args.class_name = inferred["class_name"]
    if not args.project:
        args.project = inferred["project"] or "00Phoenix"
    if not args.cache:
        args.cache = inferred["cache"]
    if not args.server_enabled:
        args.server_enabled = inferred["server_enabled"]
    if not args.web_service_enabled:
        args.web_service_enabled = inferred["web_service_enabled"]
    if not args.state_management_type:
        args.state_management_type = inferred["state_management_type"]
    if not args.hidden:
        args.hidden = inferred["hidden"]
    if not args.external_use:
        args.external_use = inferred["external_use"]
    if not args.browser_class:
        args.browser_class = inferred["browser_class"]

    service_path = build_path("Business Service", args.business_service_name)
    existing_service = get_resource_if_exists(conn, service_path)
    created_service = existing_service or request_json(
        conn,
        "PUT",
        service_path,
        build_business_service_payload(args),
    )

    return {
        "ok": True,
        "business_service": {
            "workspace_name": args.workspace_name,
            "business_service_name": args.business_service_name,
            "project": args.project,
            "class_name": args.class_name,
            "cache": args.cache,
            "server_enabled": args.server_enabled,
            "web_service_enabled": args.web_service_enabled,
            "state_management_type": args.state_management_type,
            "hidden": args.hidden,
            "external_use": args.external_use,
            "browser_class": args.browser_class,
            "status": "created",
            "business_service_request_url": created_service["url"],
            "inferred_from_repository": inferred,
        },
        "response": created_service["body"],
    }


def create_business_component(conn: ConnectionConfig, args: argparse.Namespace) -> dict[str, Any]:
    inferred = infer_business_component_defaults(
        conn,
        table_name=getattr(args, "table_name", ""),
        class_name=getattr(args, "class_name", ""),
    )
    if not args.class_name:
        args.class_name = inferred["class_name"]
    if not args.project:
        args.project = inferred["project"] or "00Phoenix"
    if not args.table_name:
        args.table_name = inferred["table_name"]
    if not args.no_insert:
        args.no_insert = inferred["no_insert"]
    if not args.no_update:
        args.no_update = inferred["no_update"]
    if not args.no_delete:
        args.no_delete = inferred["no_delete"]

    business_component_path = build_path("Business Component", args.business_component_name)
    existing_business_component = get_resource_if_exists(conn, business_component_path)
    created_business_component = existing_business_component or request_json(
        conn,
        "PUT",
        business_component_path,
        build_business_component_payload(args),
    )

    return {
        "ok": True,
        "business_component": {
            "workspace_name": args.workspace_name,
            "business_component_name": args.business_component_name,
            "project": args.project,
            "class_name": args.class_name,
            "table_name": args.table_name,
            "no_insert": args.no_insert,
            "no_update": args.no_update,
            "no_delete": args.no_delete,
            "status": "created",
            "business_component_request_url": created_business_component["url"],
            "inferred_from_repository": inferred,
        },
        "response": created_business_component["body"],
    }


def create_workflow(conn: ConnectionConfig, args: argparse.Namespace) -> dict[str, Any]:
    workflow_path = build_path("Workflow Process", args.workflow_name)
    existing_workflow = get_resource_if_exists(conn, workflow_path)
    created_workflow = existing_workflow or request_json(
        conn,
        "PUT",
        workflow_path,
        build_workflow_payload(args),
    )

    return {
        "ok": True,
        "workflow": {
            "workspace_name": args.workspace_name,
            "workflow_name": args.workflow_name,
            "project": args.project,
            "business_object": args.business_object,
            "workflow_mode": args.workflow_mode,
            "runnable": args.runnable,
            "state_management_type": args.state_management_type,
            "web_service_enabled": args.web_service_enabled,
            "pass_by_ref_hierarchy_argument": args.pass_by_ref_hierarchy_argument,
            "replication_level": args.replication_level,
            "status": args.status,
            "inactive": args.inactive,
            "description": args.description,
            "comments": args.comments,
            "creation_status": "created",
            "workflow_request_url": created_workflow["url"],
        },
        "response": created_workflow["body"],
    }


def create_applet(conn: ConnectionConfig, args: argparse.Namespace) -> dict[str, Any]:
    inferred = infer_applet_defaults(conn, args.business_component, args.applet_type)
    if not args.project:
        args.project = inferred["project"] or args.business_component
    if not args.class_name or args.class_name.endswith("WebApplet"):
        args.class_name = inferred["class_name"]
    if not getattr(args, "height", ""):
        args.height = inferred["height"]
    if not getattr(args, "width", ""):
        args.width = inferred["width"]
    args.web_template = ""

    applet_path = build_path("Applet", args.applet_name)
    applet_payload = build_applet_payload(args)
    existing_applet = get_resource_if_exists(conn, applet_path)
    created_applet = existing_applet or request_json(conn, "POST", applet_path, applet_payload)

    fields = parse_fields(args.fields_json)
    child_results: list[dict[str, Any]] = []
    project_name = args.project or args.business_component

    if args.applet_type == "list":
        list_path = build_path("Applet", args.applet_name, "List", "List")
        list_payload = {"Name": "List"}
        request_json(conn, "PUT", list_path, list_payload)

        for index, field_name in enumerate(fields, start=1):
            payload = build_list_column_payload(field_name, project_name, index)
            child_url_path = build_path(
                "Applet",
                args.applet_name,
                "List",
                "List",
                "List Column",
                field_name,
            )
            child_results.append(request_json(conn, "PUT", child_url_path, payload))
    else:
        child_path = discover_child_path(conn, "Applet", args.applet_name, "Control")
        for index, field_name in enumerate(fields, start=1):
            payload = build_control_payload(field_name, project_name, index)
            child_url_path = child_path.replace("{key}", encode_path(field_name))
            child_results.append(request_json(conn, "PUT", child_url_path, payload))

    return {
        "ok": True,
        "applet": {
            "workspace_name": args.workspace_name,
            "applet_name": args.applet_name,
            "business_component": args.business_component,
            "applet_type": args.applet_type,
            "fields": fields,
            "project": project_name,
            "template_name": args.template_name,
            "class_name": args.class_name,
            "web_template": args.web_template,
            "height": args.height,
            "width": args.width,
            "status": "created",
            "applet_request_url": created_applet["url"],
            "field_request_count": len(child_results),
            "inferred_from_repository": inferred,
        },
        "responses": {
            "applet": created_applet["body"],
            "children": [item["body"] for item in child_results],
        },
    }


def add_applet_to_view(conn: ConnectionConfig, args: argparse.Namespace) -> dict[str, Any]:
    slot_name = args.sequence or args.applet_name
    child_path = discover_child_path(conn, "View", args.view_name, "View Web Template Item")
    payload = build_view_item_payload(args.applet_name, slot_name, args.mode)
    view_url_path = child_path.replace("{key}", encode_path(slot_name))
    result = request_json(conn, "PUT", view_url_path, payload)
    return {
        "ok": True,
        "placement": {
            "workspace_name": args.workspace_name,
            "view_name": args.view_name,
            "applet_name": args.applet_name,
            "mode": args.mode,
            "tab_name": args.tab_name,
            "sequence": args.sequence,
            "status": "placed",
            "placement_request_url": result["url"],
        },
        "response": result["body"],
    }


def create_view_payload(
    source_view: dict[str, Any],
    *,
    view_name: str,
    source_list_applet: str,
    target_list_applet: str,
    project_name: str,
) -> dict[str, Any]:
    payload = clone_payload(
        source_view,
        [
            "Add To History",
            "Admin Mode Flag",
            "Background Bitmap",
            "Bitmap Category",
            "Business Object",
            "Container Web Page",
            "Default Applet Focus",
            "Disable PDQ",
            "Drop Sectors",
            "Explicit Login",
            "HTML Bitmap",
            "HTML Popup Dimension",
            "Help Identifier",
            "ICL Upgrade Path",
            "Inactive",
            "No Borders",
            "Responsive Flag",
            "Screen Menu",
            "Secure",
            "Task",
            "Text Style",
            "Thread Business Component",
            "Thread Field",
            "Thread Title - Base Row",
            "Type",
            "Upgrade Behavior",
            "Vertical Line Position",
            "Visibility Applet Catalog",
            "Visibility Applet Group Hierarchy Direction",
            "Visibility Applet Group Type",
            "Visibility Applet Type",
            "Visibility Business Component",
        ],
        {
            "Name": view_name,
            "ProjectName": project_name,
            "Comments": f"Created by Codex from {source_view.get('Name', '')}",
            "Title - Base Row": view_name,
        },
    )

    for field_name in [
        "Thread Applet",
        "Visibility Applet",
        "Sector0 Applet",
        "Sector1 Applet",
        "Sector2 Applet",
        "Sector3 Applet",
        "Sector4 Applet",
        "Sector5 Applet",
        "Sector6 Applet",
        "Sector7 Applet",
    ]:
        value = source_view.get(field_name)
        if value not in (None, ""):
            payload[field_name] = replace_applet_name(value, source_list_applet, target_list_applet)

    return payload


def create_view_web_template_payload(
    source_template: dict[str, Any],
    *,
    project_name: str,
) -> dict[str, Any]:
    return clone_payload(
        source_template,
        ["Inactive", "Upgrade Behavior", "User Layout", "Web Template"],
        {"Name": str(source_template.get("Name", "Base")), "ProjectName": project_name},
    )


def create_view_web_template_item_payload(
    source_item: dict[str, Any],
    *,
    source_list_applet: str,
    target_list_applet: str,
    project_name: str,
) -> tuple[str, dict[str, Any]]:
    item_name = replace_applet_name(source_item.get("Name", ""), source_list_applet, target_list_applet)
    payload = clone_payload(
        source_item,
        [
            "Applet",
            "Comments",
            "Ext Expression",
            "Inactive",
            "Item Identifier",
            "Markup Language",
            "Sequence",
        ],
        {
            "Name": item_name,
            "ProjectName": project_name,
        },
    )
    if "Applet" in payload:
        payload["Applet"] = replace_applet_name(payload["Applet"], source_list_applet, target_list_applet)
    return str(item_name), payload


def create_screen_view_payload(
    source_screen_view: dict[str, Any],
    *,
    view_name: str,
    sequence: str,
    project_name: str,
) -> dict[str, Any]:
    payload = clone_payload(
        source_screen_view,
        [
            "6 Sectors",
            "8 Sectors",
            "Category",
            "Category Default View",
            "Category Name",
            "Category Viewbar Text - Base Row",
            "Display In Page",
            "Display In Site Map",
            "Inactive",
            "Menu Text - Base Row",
            "Object Manager Restriction",
            "Parent Category",
            "Status Text - Base Row",
            "Type",
            "Upgrade Behavior",
            "Viewbar Text - Base Row",
        ],
        {
            "Name": view_name,
            "View": view_name,
            "ProjectName": project_name,
            "Sequence": sequence,
            "Comments": f"Created by Codex from {source_screen_view.get('Name', '')}",
        },
    )
    payload["Menu Text - Base Row"] = view_name
    payload["Viewbar Text - Base Row"] = view_name
    return payload


def create_view_on_screen(conn: ConnectionConfig, args: argparse.Namespace) -> dict[str, Any]:
    source_view_name = args.source_view_name or "All Opportunity List View"
    screen_name = args.screen_name or "Opportunities Screen"
    project_name = args.project or "00Phoenix"

    existing_view = get_resource_if_exists(conn, build_path("View", args.view_name))
    existing_screen_view = get_resource_if_exists(
        conn,
        build_path("Screen", screen_name, "Screen View", args.view_name),
    )

    source_view = get_resource(conn, "View", source_view_name)
    source_screen_view = get_resource(conn, "Screen", screen_name, "Screen View", source_view_name)
    source_list_applet = str(source_view.get("Sector1 Applet", "")).strip() or str(source_view.get("Visibility Applet", "")).strip()
    if not source_list_applet:
        raise SiebelRestError(
            f"Unable to infer the list applet from source view {source_view_name}.",
            details={"source_view_name": source_view_name},
        )

    created_view = existing_view
    if created_view is None:
        view_payload = create_view_payload(
            source_view,
            view_name=args.view_name,
            source_list_applet=source_list_applet,
            target_list_applet=args.applet_name,
            project_name=project_name,
        )
        created_view = put_resource(conn, view_payload, "View", args.view_name)

    source_templates = list_items(conn, build_path("View", source_view_name, "View Web Template"))
    template_results: list[dict[str, Any]] = []
    item_results: list[dict[str, Any]] = []
    for template in source_templates:
        template_name = str(template.get("Name", "Base")).strip() or "Base"
        put_template = put_resource(
            conn,
            create_view_web_template_payload(template, project_name=project_name),
            "View",
            args.view_name,
            "View Web Template",
            template_name,
        )
        template_results.append(put_template)

        source_items = list_items(
            conn,
            build_path("View", source_view_name, "View Web Template", template_name, "View Web Template Item"),
        )
        for source_item in source_items:
            if str(source_item.get("Inactive", "N")).strip() == "Y":
                continue
            item_name, item_payload = create_view_web_template_item_payload(
                source_item,
                source_list_applet=source_list_applet,
                target_list_applet=args.applet_name,
                project_name=project_name,
            )
            item_results.append(
                put_resource(
                    conn,
                    item_payload,
                    "View",
                    args.view_name,
                    "View Web Template",
                    template_name,
                    "View Web Template Item",
                    item_name,
                )
            )

    screen_view_result = existing_screen_view
    if screen_view_result is None:
        screen_views = list_items(conn, build_path("Screen", screen_name, "Screen View"))
        payload = create_screen_view_payload(
            source_screen_view,
            view_name=args.view_name,
            sequence=next_sequence(screen_views, parent_category=str(source_screen_view.get("Parent Category", "")).strip()),
            project_name=project_name,
        )
        screen_view_result = put_resource(conn, payload, "Screen", screen_name, "Screen View", args.view_name)

    return {
        "ok": True,
        "view": {
            "workspace_name": args.workspace_name,
            "view_name": args.view_name,
            "screen_name": screen_name,
            "applet_name": args.applet_name,
            "source_view_name": source_view_name,
            "project": project_name,
            "status": "created",
            "view_request_url": created_view["url"] if created_view else "",
            "screen_view_request_url": screen_view_result["url"] if screen_view_result else "",
            "template_count": len(template_results),
            "template_item_count": len(item_results),
        },
        "responses": {
            "view": created_view["body"] if created_view else {},
            "templates": [item["body"] for item in template_results],
            "template_items": [item["body"] for item in item_results],
            "screen_view": screen_view_result["body"] if screen_view_result else {},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Siebel Web Tools REST adapter.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    test_connection = subparsers.add_parser("test-connection")
    test_connection.add_argument("--oracle-guid", required=True)
    test_connection.add_argument("--webtools-url", required=True)
    test_connection.add_argument("--workspace-branch", required=True)
    test_connection.add_argument("--username", required=True)
    test_connection.add_argument("--password", required=True)
    test_connection.add_argument("--session-id", default="")
    test_connection.add_argument("--verify-tls", default="True")

    create_workspace_parser = subparsers.add_parser("create-workspace")
    create_workspace_parser.add_argument("--oracle-guid", required=True)
    create_workspace_parser.add_argument("--webtools-url", required=True)
    create_workspace_parser.add_argument("--workspace-branch", required=True)
    create_workspace_parser.add_argument("--username", required=True)
    create_workspace_parser.add_argument("--password", required=True)
    create_workspace_parser.add_argument("--verify-tls", default="True")
    create_workspace_parser.add_argument("--workspace-name", required=True)
    create_workspace_parser.add_argument("--branch-name", default="")
    create_workspace_parser.add_argument("--reason", default="")

    create_applet_parser = subparsers.add_parser("create-applet")
    create_applet_parser.add_argument("--oracle-guid", required=True)
    create_applet_parser.add_argument("--webtools-url", required=True)
    create_applet_parser.add_argument("--workspace-branch", required=True)
    create_applet_parser.add_argument("--username", required=True)
    create_applet_parser.add_argument("--password", required=True)
    create_applet_parser.add_argument("--verify-tls", default="True")
    create_applet_parser.add_argument("--workspace-name", default="")
    create_applet_parser.add_argument("--applet-name", required=True)
    create_applet_parser.add_argument("--business-component", required=True)
    create_applet_parser.add_argument("--applet-type", default="list")
    create_applet_parser.add_argument("--project", default="")
    create_applet_parser.add_argument("--template-name", default="")
    create_applet_parser.add_argument("--class-name", default="")
    create_applet_parser.add_argument("--web-template", default="")
    create_applet_parser.add_argument("--height", default="")
    create_applet_parser.add_argument("--width", default="")
    create_applet_parser.add_argument("--fields-json", default="[]")

    add_to_view = subparsers.add_parser("add-applet-to-view")
    add_to_view.add_argument("--oracle-guid", required=True)
    add_to_view.add_argument("--webtools-url", required=True)
    add_to_view.add_argument("--workspace-branch", required=True)
    add_to_view.add_argument("--username", required=True)
    add_to_view.add_argument("--password", required=True)
    add_to_view.add_argument("--verify-tls", default="True")
    add_to_view.add_argument("--workspace-name", default="")
    add_to_view.add_argument("--view-name", required=True)
    add_to_view.add_argument("--applet-name", required=True)
    add_to_view.add_argument("--mode", default="Base")
    add_to_view.add_argument("--tab-name", default="")
    add_to_view.add_argument("--sequence", default="")

    create_view_parser = subparsers.add_parser("create-view-on-screen")
    create_view_parser.add_argument("--oracle-guid", required=True)
    create_view_parser.add_argument("--webtools-url", required=True)
    create_view_parser.add_argument("--workspace-branch", required=True)
    create_view_parser.add_argument("--username", required=True)
    create_view_parser.add_argument("--password", required=True)
    create_view_parser.add_argument("--verify-tls", default="True")
    create_view_parser.add_argument("--workspace-name", default="")
    create_view_parser.add_argument("--view-name", required=True)
    create_view_parser.add_argument("--screen-name", required=True)
    create_view_parser.add_argument("--source-view-name", default="All Opportunity List View")
    create_view_parser.add_argument("--applet-name", required=True)
    create_view_parser.add_argument("--project", default="")

    create_business_service_parser = subparsers.add_parser("create-business-service")
    create_business_service_parser.add_argument("--oracle-guid", required=True)
    create_business_service_parser.add_argument("--webtools-url", required=True)
    create_business_service_parser.add_argument("--workspace-branch", required=True)
    create_business_service_parser.add_argument("--username", required=True)
    create_business_service_parser.add_argument("--password", required=True)
    create_business_service_parser.add_argument("--verify-tls", default="True")
    create_business_service_parser.add_argument("--workspace-name", default="")
    create_business_service_parser.add_argument("--business-service-name", required=True)
    create_business_service_parser.add_argument("--project", default="")
    create_business_service_parser.add_argument("--class-name", default="")
    create_business_service_parser.add_argument("--cache", default="")
    create_business_service_parser.add_argument("--server-enabled", default="")
    create_business_service_parser.add_argument("--web-service-enabled", default="")
    create_business_service_parser.add_argument("--state-management-type", default="")
    create_business_service_parser.add_argument("--hidden", default="")
    create_business_service_parser.add_argument("--external-use", default="")
    create_business_service_parser.add_argument("--browser-class", default="")
    create_business_service_parser.add_argument("--comments", default="")

    create_business_component_parser = subparsers.add_parser("create-business-component")
    create_business_component_parser.add_argument("--oracle-guid", required=True)
    create_business_component_parser.add_argument("--webtools-url", required=True)
    create_business_component_parser.add_argument("--workspace-branch", required=True)
    create_business_component_parser.add_argument("--username", required=True)
    create_business_component_parser.add_argument("--password", required=True)
    create_business_component_parser.add_argument("--verify-tls", default="True")
    create_business_component_parser.add_argument("--workspace-name", default="")
    create_business_component_parser.add_argument("--business-component-name", required=True)
    create_business_component_parser.add_argument("--project", default="")
    create_business_component_parser.add_argument("--class-name", default="")
    create_business_component_parser.add_argument("--table-name", default="")
    create_business_component_parser.add_argument("--no-insert", default="")
    create_business_component_parser.add_argument("--no-update", default="")
    create_business_component_parser.add_argument("--no-delete", default="")
    create_business_component_parser.add_argument("--comments", default="")

    create_workflow_parser = subparsers.add_parser("create-workflow")
    create_workflow_parser.add_argument("--oracle-guid", required=True)
    create_workflow_parser.add_argument("--webtools-url", required=True)
    create_workflow_parser.add_argument("--workspace-branch", required=True)
    create_workflow_parser.add_argument("--username", required=True)
    create_workflow_parser.add_argument("--password", required=True)
    create_workflow_parser.add_argument("--verify-tls", default="True")
    create_workflow_parser.add_argument("--workspace-name", default="")
    create_workflow_parser.add_argument("--workflow-name", required=True)
    create_workflow_parser.add_argument("--project", default="")
    create_workflow_parser.add_argument("--business-object", default="")
    create_workflow_parser.add_argument("--workflow-mode", default="Service Flow")
    create_workflow_parser.add_argument("--runnable", default="Y")
    create_workflow_parser.add_argument("--state-management-type", default="Stateful")
    create_workflow_parser.add_argument("--web-service-enabled", default="N")
    create_workflow_parser.add_argument("--pass-by-ref-hierarchy-argument", default="N")
    create_workflow_parser.add_argument("--replication-level", default="None")
    create_workflow_parser.add_argument("--status", default="In Progress")
    create_workflow_parser.add_argument("--inactive", default="N")
    create_workflow_parser.add_argument("--description", default="")
    create_workflow_parser.add_argument("--comments", default="")

    args = parser.parse_args()
    conn = ConnectionConfig(
        oracle_guid=args.oracle_guid,
        webtools_url=args.webtools_url,
        workspace_branch=args.workspace_branch,
        username=args.username,
        password=args.password,
        verify_tls=str(getattr(args, "verify_tls", "True")).lower() not in {"false", "0", "no"},
    )

    try:
        if args.command == "test-connection":
            result = get_describe(conn)
            emit(
                {
                    "ok": True,
                    "adapter": "siebel-webtools-rest",
                    "connection": {
                        "oracle_guid": conn.oracle_guid,
                        "webtools_url": workspace_base(conn),
                        "workspace_branch": conn.workspace_branch,
                        "username": conn.username,
                        "status": "verified",
                        "session_id": "",
                    },
                    "message": "Siebel Web Tools repository endpoint verified.",
                    "describe_status": result["status"],
                }
            )
            return 0

        if args.command == "create-workspace":
            branch_name = args.branch_name or conn.workspace_branch
            result = ensure_workspace_exists(conn, branch_name)
            result["workspace_name"] = args.workspace_name or branch_name
            result["message"] = (
                "Workspace creation is not exposed by the published repository REST examples; "
                "the adapter verified that the target workspace branch already exists and is usable."
            )
            emit({"ok": True, "workspace": result})
            return 0

        if args.command == "create-applet":
            emit(create_applet(conn, args))
            return 0

        if args.command == "add-applet-to-view":
            emit(add_applet_to_view(conn, args))
            return 0

        if args.command == "create-view-on-screen":
            emit(create_view_on_screen(conn, args))
            return 0

        if args.command == "create-business-service":
            emit(create_business_service(conn, args))
            return 0

        if args.command == "create-business-component":
            emit(create_business_component(conn, args))
            return 0

        if args.command == "create-workflow":
            emit(create_workflow(conn, args))
            return 0

        emit({"ok": False, "error": "Unsupported command."})
        return 1
    except SiebelRestError as exc:
        emit(
            {
                "ok": False,
                "adapter": "siebel-webtools-rest",
                "error": str(exc),
                "status": exc.status,
                "details": exc.details,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
