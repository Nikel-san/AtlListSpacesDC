#!/usr/bin/env python3
"""List Jira Data Center projects or Confluence Data Center spaces to CSV."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import quote, urlparse

import requests


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise SystemExit(f"Error: {message}\n")


ANSI = {
    "GREEN": "\033[32m",
    "RED": "\033[31m",
    "YELLOW": "\033[33m",
    "CYAN": "\033[36m",
    "RESET": "\033[0m",
}


def colorize(color: str, text: str) -> str:
    return f"{ANSI.get(color, ANSI['RESET'])}{text}{ANSI['RESET']}"


def parse_args() -> argparse.Namespace:
    parser = CliArgumentParser(
        description="List Atlassian Data Center projects or spaces and export them to CSV."
    )
    parser.add_argument(
        "-t",
        "--type",
        choices=["jira", "confluence"],
        required=True,
        help="Type of items to list: jira or confluence.",
    )
    parser.add_argument(
        "-s",
        "--site",
        required=True,
        help="Data Center base URL, such as https://jira.example.com",
    )
    parser.add_argument(
        "-p",
        "--token",
        required=True,
        help="PAT token used for bearer authentication.",
    )
    parser.add_argument(
        "-f",
        "--out",
        default=None,
        help="Output CSV path. Auto-generated when omitted.",
    )

    args = parser.parse_args()
    if not args.site or not args.site.strip():
        raise SystemExit("Error: --site / -s is required and cannot be empty.\n")
    if not args.token or not args.token.strip():
        raise SystemExit("Error: --token / -p is required and cannot be empty.\n")
    return args


def build_default_out(item_type: str, site_url: str) -> str:
    parsed = urlparse(site_url)
    hostname = parsed.netloc or site_url.strip("/")
    safe_host = re.sub(r"[^A-Za-z0-9]+", "_", hostname).strip("_")
    if not safe_host:
        safe_host = "site"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"list_spaces_dc_{item_type}_{safe_host}_{stamp}.csv"


def normalized_site(site_url: str) -> str:
    cleaned = site_url.strip().rstrip("/")
    if not cleaned:
        raise ValueError("Site URL cannot be empty.")
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        raise ValueError("Site URL must include the protocol, such as https://jira.example.com")
    return cleaned


def build_headers() -> List[str]:
    return [
        "Space Name",
        "Space Key",
        "Creation Date",
        "Last Activity Date",
        "Number of Items",
        "Status",
        "Admins",
        "Business Owner",
    ]


def request_json(session: requests.Session, method: str, url: str, token: str, params: Dict[str, Any] | None = None, timeout: int | None = None) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    used_timeout = timeout if isinstance(timeout, (int, float)) and timeout > 0 else 30
    response = session.request(method=method, url=url, headers=headers, params=params, timeout=used_timeout)
    if response.status_code >= 400:
        body = response.text[:500]
        raise RuntimeError(f"HTTP {response.status_code} for {method} {url}: {body}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Failed to parse JSON from {method} {url}: {response.text[:500]}") from exc


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list):
        return ", ".join([safe_text(item) for item in value])
    return str(value)


def flatten_admins(members: Iterable[Any]) -> str:
    names: List[str] = []
    for member in members:
        if isinstance(member, dict):
            for key in ("displayName", "name", "username", "emailAddress"):
                value = member.get(key)
                if value:
                    names.append(str(value))
                    break
        else:
            names.append(str(member))
    return ", ".join(dict.fromkeys(names))


def is_personal_space_key(space_key: str) -> bool:
    return bool(space_key) and space_key.startswith("~")


def extract_group_members(session: requests.Session, base_url: str, token: str, group_name: str, skip_confluence_endpoints: bool = False) -> str:
    candidates = [
        (f"{base_url}/rest/api/2/group/member", {"groupname": group_name, "maxResults": 1000, "startAt": 0}),
        (f"{base_url}/rest/api/group/member", {"groupname": group_name, "maxResults": 1000, "startAt": 0}),
    ]
    if not skip_confluence_endpoints:
        candidates.append((f"{base_url}/rest/api/group/{quote(group_name)}/member", {"limit": 1000}))
    seen: set[str] = set()
    for url, params in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            # Use a short timeout for group/member probes to avoid long delays when an endpoint exists but is slow
            response = request_json(session, "GET", url, token, params=params, timeout=5)
            members: List[Any] = []
            if isinstance(response, dict):
                for key in ("values", "members", "results"):
                    value = response.get(key)
                    if isinstance(value, list):
                        members = value
                        break
                if not members and isinstance(response.get("group"), dict):
                    members = response["group"].get("members", [])
            if isinstance(response, list):
                members = response
            if members:
                return flatten_admins(members)
        except Exception:
            continue
    return ""


def extract_confluence_labels(metadata: Dict[str, Any] | None) -> str:
    labels_block = (metadata.get("metadata") or {}).get("labels") or {}
    results = labels_block.get("results") or []
    return ", ".join(
        item.get("name") for item in results
        if isinstance(item, dict) and item.get("name")
    )


def extract_confluence_created_date(item: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    candidates = [
        item.get("createdDate"),
        item.get("created"),
        metadata.get("createdDate"),
        metadata.get("created"),
        (metadata.get("history") or {}).get("createdDate"),
        (metadata.get("history") or {}).get("created"),
        metadata.get("_homepage_created"),
    ]
    for candidate in candidates:
        value = safe_text(candidate)
        if value:
            return value
    return ""


def earliest_date(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    return str(value)


def jira_project_admins(session: requests.Session, base_url: str, token: str, project_key: str) -> str:
    group_name = f"{project_key}-administrators"
    return extract_group_members(session, base_url, token, group_name, skip_confluence_endpoints=True)


def confluence_space_admins(session: requests.Session, base_url: str, token: str, space_key: str) -> str:
    group_name = f"{space_key}-administrators"
    return extract_group_members(session, base_url, token, group_name)


def resolve_jira_project_status(project: Dict[str, Any]) -> str:
    lead = project.get("lead") or {}
    lead_name = (lead.get("name") or lead.get("displayName") or "").strip()
    archived = bool(project.get("archived"))
    if lead_name == "ArchiveUser" or archived:
        return "Archived"
    return "Active"


def resolve_confluence_space_status(space: Dict[str, Any]) -> str:
    status_value = safe_text(space.get("status") or space.get("spaceStatus") or space.get("statusValue"))
    if status_value.lower() == "archived":
        return "Archived"
    return "Active"


def find_last_updated_date_from_issues(session: requests.Session, base_url: str, token: str, project_key: str) -> str:
    query = (
            f'project = "{project_key}" ORDER BY updated DESC'
    )
    url = f"{base_url}/rest/api/2/search"
    params = {"jql": query, "maxResults": 1, "fields": "updated"}
    try:
        data = request_json(session, "GET", url, token, params=params)
        issues = data.get("issues", [])
        if not issues:
            return ""
        fields = issues[0].get("fields", {})
        return safe_text(fields.get("updated"))
    except Exception:
        return ""


def get_jira_projects(session: requests.Session, base_url: str, token: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    start_at = 0
    while True:
        project_list = request_json(
            session,
            "GET",
            f"{base_url}/rest/api/2/project",
            token,
            params={"startAt": start_at, "maxResults": 50},
        )
        values = project_list.get("values", []) if isinstance(project_list, dict) else project_list
        if not isinstance(values, list):
            break
        for item in values:
            key = safe_text(item.get("key"))
            if not key:
                continue
            detail = request_json(
                session,
                "GET",
                f"{base_url}/rest/api/2/project/{quote(key)}",
                token,
            )
            issue_count = 0
            try:
                count_response = request_json(
                    session,
                    "GET",
                    f"{base_url}/rest/api/2/search",
                    token,
                                    params={"jql": f'project = "{key}"', "maxResults": 0, "fields": "id"},
                )
                issue_count = int(count_response.get("total", 0) or 0)
            except Exception:
                issue_count = 0
            rows.append(
                {
                    "name": safe_text(detail.get("name") or item.get("name")),
                    "key": key,
                    "created": safe_text(detail.get("created") or item.get("createdDate")),
                    "updated": find_last_updated_date_from_issues(session, base_url, token, key),
                    "count": issue_count,
                    "status": resolve_jira_project_status(detail),
                    "admins": jira_project_admins(session, base_url, token, key),
                    "business_owner": safe_text((detail.get("projectCategory") or {}).get("name")),
                }
            )
        if len(values) < 50:
            break
        start_at += len(values)
    return rows


def collect_confluence_space_metadata(session: requests.Session, base_url: str, token: str, space_key: str) -> Dict[str, Any]:
    try:
        meta = request_json(
            session,
            "GET",
            f"{base_url}/rest/api/space/{quote(space_key)}",
            token,
            params={"expand": "metadata.labels,history,homepage"},
        )
        # Fallback: fetch homepage content history to derive creation date when space.history is not populated
        homepage = meta.get("homepage") or {}
        homepage_id = homepage.get("id")
        if homepage_id:
            try:
                page_data = request_json(
                    session,
                    "GET",
                    f"{base_url}/rest/api/content/{quote(str(homepage_id))}",
                    token,
                    params={"expand": "history"},
                )
                created = (page_data.get("history") or {}).get("createdDate") or (page_data.get("history") or {}).get("created")
                if created:
                    meta["_homepage_created"] = created
            except Exception:
                # ignore failures fetching homepage history
                pass
        return meta
    except Exception:
        return {}


def get_confluence_space_page_count(session: requests.Session, base_url: str, token: str, space_key: str) -> int:
    try:
        for url, params in (
            (
                f"{base_url}/rest/api/search",
                {"cql": f'space = "{space_key}" AND type = page', "limit": 1, "start": 0},
            ),
            (
                f"{base_url}/rest/api/content",
                {"spaceKey": space_key, "type": "page", "limit": 1, "start": 0},
            ),
        ):
            page_data = request_json(session, "GET", url, token, params=params)
            if isinstance(page_data, dict):
                total = page_data.get("total")
                if total is None:
                    total = page_data.get("totalSize")
                if total is not None:
                    return int(total or 0)
            elif isinstance(page_data, list):
                return len(page_data)
        return 0
    except Exception:
        return 0


def get_confluence_last_activity(session: requests.Session, base_url: str, token: str, space_key: str) -> str:
    try:
        query = (
            f"space = \"{space_key}\" AND type = page ORDER BY lastmodified DESC"
        )
        response = request_json(
            session,
            "GET",
            f"{base_url}/rest/api/search",
            token,
            params={"cql": query, "limit": 1},
        )
        results = response.get("results", [])
        if not results:
            return ""
        return safe_text(results[0].get("lastModified") or results[0].get("lastmodified") or results[0].get("history", {}).get("lastUpdated"))
    except Exception:
        return ""


def get_confluence_spaces(session: requests.Session, base_url: str, token: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    start = 0
    while True:
        space_list = request_json(
            session,
            "GET",
            f"{base_url}/rest/api/space",
            token,
            params={"limit": 200, "start": start},
        )
        results = space_list.get("results", [])
        for item in results:
            key = safe_text(item.get("key"))
            if not key or is_personal_space_key(key):
                continue
            metadata = collect_confluence_space_metadata(session, base_url, token, key)
            categories = extract_confluence_labels(metadata)
            rows.append(
                {
                    "name": safe_text(item.get("name")),
                    "key": key,
                    "created": extract_confluence_created_date(item, metadata),
                    "updated": get_confluence_last_activity(session, base_url, token, key),
                    "count": get_confluence_space_page_count(session, base_url, token, key),
                    "status": resolve_confluence_space_status(item),
                    "admins": confluence_space_admins(session, base_url, token, key),
                    "business_owner": categories,
                }
            )
        if len(results) < 200:
            break
        start += len(results)
    return rows


def write_csv(file_path: str, rows: List[Dict[str, Any]], item_type: str) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_headers())
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Space Name": row.get("name", ""),
                    "Space Key": row.get("key", ""),
                    "Creation Date": row.get("created", ""),
                    "Last Activity Date": row.get("updated", ""),
                    "Number of Items": row.get("count", ""),
                    "Status": row.get("status", ""),
                    "Admins": row.get("admins", ""),
                    "Business Owner": row.get("business_owner", ""),
                }
            )
    print(colorize("GREEN", f"CSV written to {path}"))


def main() -> int:
    try:
        args = parse_args()
    except SystemExit as exc:
        if str(exc):
            print(str(exc), end="")
        return 1

    item_type = args.type.lower()
    site = normalized_site(args.site)
    token = args.token.strip()
    if not token:
        print(colorize("RED", "Error: --token / -p is required and cannot be empty."))
        return 1
    output_path = args.out if args.out else build_default_out(item_type, site)

    print(colorize("CYAN", f"Collecting {item_type} data for {site} ..."))
    session = requests.Session()
    try:
        if item_type == "jira":
            rows = get_jira_projects(session, site, token)
        else:
            rows = get_confluence_spaces(session, site, token)
        write_csv(output_path, rows, item_type)
        print(colorize("GREEN", f"Completed: {len(rows)} records exported."))
        return 0
    except Exception as exc:
        print(colorize("RED", f"Error: {exc}"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
