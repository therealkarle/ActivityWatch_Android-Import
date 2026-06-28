from __future__ import annotations

import fnmatch
import json
import socket
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib import error, request


CONFIG_FILE = Path(__file__).with_name("config.json")
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

DEFAULT_CONFIG: dict[str, Any] = {
    "google_drive_folder_id": "",
    "google_drive_service_account_file": "",
    "input_file_globs": ["*"],
    "last_sync_file": "last_sync.txt",
    "activitywatch_base_url": "http://localhost:5600",
    "activitywatch_hostname": "AndroidDevice",
    "timestamp_fields": ["timestamp", "time", "datetime", "date", "start", "created_at"],
    "duration_fields": ["duration", "length", "seconds"],
    "payload_fields": ["data", "event", "payload"],
    "encoding": "utf-8",
    "request_timeout_seconds": 15,
}

ISO_LIKE_PREFIX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)"
)
TS_ONLY = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?)"
)


@dataclass(frozen=True)
class AppConfig:
    google_drive_folder_id: str | None
    google_drive_service_account_file: Path | None
    input_file_globs: list[str]
    last_sync_file: Path
    activitywatch_base_url: str
    activitywatch_hostname: str
    timestamp_fields: list[str]
    duration_fields: list[str]
    payload_fields: list[str]
    encoding: str
    request_timeout_seconds: int


def log(message: str) -> None:
    print(message, flush=True)


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        content = handle.read().strip()
    if not content:
        return {}
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file must contain a JSON object: {path}")
    return data


def resolve_path(value: str | None, base_dir: Path) -> Path | None:
    if not value or not str(value).strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def build_config() -> AppConfig:
    raw = dict(DEFAULT_CONFIG)
    raw.update(load_json_file(CONFIG_FILE))

    google_drive_folder_id = str(raw.get("google_drive_folder_id", "")).strip() or None
    service_account_file = resolve_path(
        str(raw.get("google_drive_service_account_file", "")),
        CONFIG_FILE.parent,
    )
    if google_drive_folder_id:
        if service_account_file is None:
            raise ValueError(
                "google_drive_service_account_file is required when google_drive_folder_id is set."
            )
    else:
        raise ValueError("google_drive_folder_id is missing. Set it in config.json.")

    last_sync_file = resolve_path(str(raw.get("last_sync_file", "last_sync.txt")), CONFIG_FILE.parent)
    if last_sync_file is None:
        last_sync_file = CONFIG_FILE.with_name("last_sync.txt")

    input_file_globs = raw.get("input_file_globs", ["*"])
    if (
        not isinstance(input_file_globs, list)
        or not input_file_globs
        or not all(isinstance(item, str) and item for item in input_file_globs)
    ):
        raise ValueError("input_file_globs must be a non-empty list of strings.")

    activitywatch_base_url = str(raw.get("activitywatch_base_url", "http://localhost:5600")).strip() or "http://localhost:5600"
    activitywatch_hostname = str(raw.get("activitywatch_hostname", "")).strip()

    return AppConfig(
        google_drive_folder_id=google_drive_folder_id,
        google_drive_service_account_file=service_account_file,
        input_file_globs=input_file_globs,
        last_sync_file=last_sync_file,
        activitywatch_base_url=activitywatch_base_url,
        activitywatch_hostname=activitywatch_hostname,
        timestamp_fields=[str(item) for item in raw.get("timestamp_fields", []) if str(item)],
        duration_fields=[str(item) for item in raw.get("duration_fields", []) if str(item)],
        payload_fields=[str(item) for item in raw.get("payload_fields", []) if str(item)],
        encoding=str(raw.get("encoding", "utf-8")),
        request_timeout_seconds=int(raw.get("request_timeout_seconds", 15)),
    )


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Unsupported timestamp type: {type(value)!r}")

    text = value.strip()
    if not text:
        raise ValueError("Empty timestamp string")
    normalized = text.replace("Z", "+00:00")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            raise
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_last_sync(path: Path) -> datetime | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return parse_timestamp(content)


def write_last_sync(path: Path, timestamp: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_timestamp(timestamp) + "\n", encoding="utf-8")


def file_matches(name: str, patterns: Iterable[str]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def build_activitywatch_urls(base_url: str, bucket_id: str) -> tuple[str, str]:
    base = base_url.rstrip("/")
    bucket_url = f"{base}/api/0/buckets/{bucket_id}"
    events_url = f"{bucket_url}/events"
    return bucket_url, events_url


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str


def build_drive_session(service_account_file: Path):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=[DRIVE_READONLY_SCOPE],
    )
    return AuthorizedSession(credentials)


def aw_request(url: str, method: str, timeout_seconds: int, body: bytes | None = None) -> bytes:
    req = request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=timeout_seconds) as response:
        status = getattr(response, "status", response.getcode())
        if status >= 300:
            raise RuntimeError(f"Unexpected HTTP status {status} from ActivityWatch.")
        return response.read()


def ensure_activitywatch_bucket(base_url: str, bucket: ExportBucket, hostname_override: str, timeout_seconds: int) -> None:
    bucket_url, _ = build_activitywatch_urls(base_url, bucket.bucket_id)
    bucket_hostname = hostname_override or bucket.hostname or socket.gethostname()
    bucket_payload = {
        "client": bucket.client or "google_drive_to_activitywatch",
        "hostname": bucket_hostname,
        "type": bucket.bucket_type or "manual",
    }
    if bucket.data:
        bucket_payload["data"] = bucket.data

    try:
        aw_request(bucket_url, "POST", timeout_seconds, json.dumps(bucket_payload).encode("utf-8"))
        log(f"Ensured ActivityWatch bucket exists: {bucket.bucket_id}")
    except error.HTTPError as exc:
        if exc.code in {200, 201, 204, 304, 409}:
            return
        if exc.code == 405:
            raise RuntimeError(
                f"ActivityWatch rejected bucket creation at {bucket_url} with 405. "
                "Check that ActivityWatch is running and accepts bucket creation on the /api/0 REST route."
            ) from exc
        raise


def find_latest_drive_file(session: Any, folder_id: str, patterns: list[str], timeout_seconds: int) -> DriveFile:
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,modifiedTime,mimeType)",
            "orderBy": "modifiedTime desc,name desc",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token

        response = session.get(
            f"{DRIVE_API_BASE}/files",
            params=params,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        for item in payload.get("files", []):
            name = str(item.get("name", ""))
            if not file_matches(name, patterns):
                continue
            return DriveFile(
                id=str(item["id"]),
                name=name,
                mime_type=str(item.get("mimeType", "")),
            )

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    raise FileNotFoundError(
        f"No matching files found in Google Drive folder: {folder_id}"
    )


def download_drive_file(session: Any, drive_file: DriveFile, destination: Path, timeout_seconds: int) -> Path:
    if drive_file.mime_type.startswith("application/vnd.google-apps."):
        raise ValueError(
            f"Drive file {drive_file.name} is a Google Docs item. Export it as a regular file before syncing."
        )

    response = session.get(
        f"{DRIVE_API_BASE}/files/{drive_file.id}",
        params={
            "alt": "media",
            "supportsAllDrives": "true",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    safe_name = re.sub(r'[<>:"/\\\\|?*]+', "_", Path(drive_file.name).name).strip() or "downloaded_source"
    destination = destination.with_name(safe_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def load_json_records(path: Path, encoding: str) -> list[dict[str, Any]]:
    with path.open("r", encoding=encoding) as handle:
        text = handle.read().strip()
    if not text:
        return []
    try:
        root = json.loads(text)
    except json.JSONDecodeError:
        return []

    def collect_items(value: Any) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                collected.extend(collect_items(item))
            return collected

        if not isinstance(value, dict):
            return collected

        if "timestamp" in value:
            collected.append(value)

        buckets = value.get("buckets")
        if isinstance(buckets, dict):
            for bucket in buckets.values():
                if isinstance(bucket, dict):
                    events = bucket.get("events")
                    if isinstance(events, list):
                        for event in events:
                            collected.extend(collect_items(event))
                    elif isinstance(events, dict):
                        for event_list in events.values():
                            if isinstance(event_list, list):
                                for event in event_list:
                                    collected.extend(collect_items(event))

        for key in ("events", "records", "items", "rows", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                for item in nested:
                    collected.extend(collect_items(item))
            elif isinstance(nested, dict):
                for item in nested.values():
                    collected.extend(collect_items(item))

        return collected

    return collect_items(root)


def parse_plain_text_records(path: Path, encoding: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding=encoding) as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            match = ISO_LIKE_PREFIX.match(line) or TS_ONLY.match(line)
            if not match:
                continue
            timestamp_text = match.group("ts")
            remainder = line[len(timestamp_text) :].lstrip(" :-\t")
            records.append(
                {
                    "timestamp": timestamp_text,
                    "message": remainder,
                    "_line": line_no,
                    "_raw": line,
                }
            )
    return records


@dataclass(frozen=True)
class ExportBucket:
    bucket_id: str
    bucket_type: str
    client: str
    hostname: str
    data: dict[str, Any]
    records: list[dict[str, Any]]


def collect_json_records(value: Any) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            collected.extend(collect_json_records(item))
        return collected

    if not isinstance(value, dict):
        return collected

    if "timestamp" in value:
        collected.append(value)

    for key in ("events", "records", "items", "rows", "data"):
        nested = value.get(key)
        if isinstance(nested, list):
            for item in nested:
                collected.extend(collect_json_records(item))
        elif isinstance(nested, dict):
            for item in nested.values():
                collected.extend(collect_json_records(item))

    return collected


def load_export_buckets(path: Path, encoding: str) -> list[ExportBucket]:
    with path.open("r", encoding=encoding) as handle:
        text = handle.read().strip()
    if not text:
        return []

    try:
        root = json.loads(text)
    except json.JSONDecodeError:
        plain_records = parse_plain_text_records(path, encoding)
        return [
            ExportBucket(
                bucket_id="imported",
                bucket_type="manual",
                client="google_drive_to_activitywatch",
                hostname="",
                data={},
                records=plain_records,
            )
        ] if plain_records else []

    exports: list[ExportBucket] = []
    if isinstance(root, dict) and isinstance(root.get("buckets"), dict):
        for fallback_bucket_id, bucket_value in root["buckets"].items():
            if not isinstance(bucket_value, dict):
                continue
            records = collect_json_records(bucket_value.get("events"))
            if not records:
                continue
            bucket_id = str(bucket_value.get("id") or fallback_bucket_id).strip() or str(fallback_bucket_id)
            bucket_type = str(bucket_value.get("type", "manual"))
            client = str(bucket_value.get("client", "google_drive_to_activitywatch"))
            hostname = str(bucket_value.get("hostname", "") or "")
            data_value = bucket_value.get("data")
            data = data_value if isinstance(data_value, dict) else {}
            exports.append(
                ExportBucket(
                    bucket_id=bucket_id,
                    bucket_type=bucket_type,
                    client=client,
                    hostname=hostname,
                    data=data,
                    records=records,
                )
            )
        return exports

    records = collect_json_records(root)
    if records:
        exports.append(
            ExportBucket(
                bucket_id="imported",
                bucket_type="manual",
                client="google_drive_to_activitywatch",
                hostname="",
                data={},
                records=records,
            )
        )
    return exports


def pick_first(value: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in value and value[key] not in (None, ""):
            return value[key]
    return None


def normalize_event(record: dict[str, Any], config: AppConfig) -> dict[str, Any] | None:
    timestamp_value = pick_first(record, config.timestamp_fields) or record.get("timestamp")
    if timestamp_value is None:
        return None

    timestamp = parse_timestamp(timestamp_value)
    duration_value = pick_first(record, config.duration_fields)
    payload = None
    for key in config.payload_fields:
        value = record.get(key)
        if isinstance(value, dict):
            payload = value
            break

    if payload is None:
        payload = {
            key: value
            for key, value in record.items()
            if key not in set(config.timestamp_fields + config.duration_fields + config.payload_fields)
            and not key.startswith("_")
        }
    event: dict[str, Any] = {
        "timestamp": format_timestamp(timestamp),
        "data": payload,
    }
    if duration_value is not None:
        try:
            event["duration"] = float(duration_value)
        except (TypeError, ValueError):
            event["duration"] = 0.0
    else:
        event["duration"] = 0.0
    return event


def collect_events(records: list[dict[str, Any]], config: AppConfig, last_sync: datetime | None) -> tuple[list[dict[str, Any]], datetime | None]:
    events: list[dict[str, Any]] = []
    newest: datetime | None = last_sync
    for record in records:
        event = normalize_event(record, config)
        if event is None:
            continue
        timestamp = parse_timestamp(event["timestamp"])
        if last_sync is not None and timestamp <= last_sync:
            continue
        events.append(event)
        if newest is None or timestamp > newest:
            newest = timestamp
    events.sort(key=lambda item: item["timestamp"])
    return events, newest


def post_events(endpoint: str, events: list[dict[str, Any]], timeout_seconds: int) -> None:
    body = json.dumps(events, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for method in ("POST", "PUT"):
        req = request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                status = getattr(response, "status", response.getcode())
                if status >= 300:
                    raise RuntimeError(f"Unexpected HTTP status {status} from ActivityWatch endpoint.")
                return
        except error.HTTPError as exc:
            last_error = exc
            if exc.code not in {404, 405, 501} or method == "PUT":
                raise
        except Exception as exc:
            last_error = exc
            if method == "PUT":
                raise
    if last_error is not None:
        raise last_error


def main() -> int:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        config = build_config()
        last_sync = read_last_sync(config.last_sync_file)
        service_account_file = config.google_drive_service_account_file
        assert service_account_file is not None
        assert config.google_drive_folder_id is not None
        session = build_drive_session(service_account_file)
        drive_file = find_latest_drive_file(
            session,
            config.google_drive_folder_id,
            config.input_file_globs,
            config.request_timeout_seconds,
        )
        temp_dir = tempfile.TemporaryDirectory()
        latest_file = download_drive_file(
            session,
            drive_file,
            Path(temp_dir.name) / Path(drive_file.name).name,
            config.request_timeout_seconds,
        )
        log(f"Latest source file from Google Drive: {drive_file.name}")
        log(f"Latest source file: {latest_file}")

        bucket_exports = load_export_buckets(latest_file, config.encoding)
        if not bucket_exports:
            log("No parseable bucket exports found in the downloaded export. Nothing to send.")
            return 0

        total_events = 0
        newest_timestamp = last_sync
        for bucket_export in bucket_exports:
            events, bucket_newest = collect_events(bucket_export.records, config, last_sync)
            if not events:
                continue

            ensure_activitywatch_bucket(
                config.activitywatch_base_url,
                bucket_export,
                config.activitywatch_hostname,
                config.request_timeout_seconds,
            )
            bucket_endpoint = build_activitywatch_urls(
                config.activitywatch_base_url,
                bucket_export.bucket_id,
            )[1]
            post_events(bucket_endpoint, events, config.request_timeout_seconds)
            total_events += len(events)
            if bucket_newest is not None and (newest_timestamp is None or bucket_newest > newest_timestamp):
                newest_timestamp = bucket_newest
            log(f"Imported {len(events)} event(s) into bucket {bucket_export.bucket_id}.")

        if total_events == 0:
            if last_sync is None:
                log("No importable events found in the source export.")
            else:
                log(f"No new events to import after last_sync={format_timestamp(last_sync)}.")
            return 0

        if newest_timestamp is not None:
            write_last_sync(config.last_sync_file, newest_timestamp)
        log(f"Imported {total_events} event(s) across {len(bucket_exports)} bucket export(s) successfully.")
        return 0
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())


# Windows autostart:
# 1. Create a .bat file that calls: python "C:\path\to\google_drive_to_activitywatch.py"
# 2. Put the .bat into shell:startup for per-user login autostart, or create a Task Scheduler task
#    that runs once at logon/system start and exits after the script finishes.
