from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib import error, request


# Optional hard override. Leave as None to use config.json.
GOOGLE_DRIVE_FOLDER = None

CONFIG_FILE = Path(__file__).with_name("config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "google_drive_folder": "",
    "input_file_globs": ["*"],
    "last_sync_file": "last_sync.txt",
    "activitywatch_endpoint": "http://localhost:5600/api/v1/buckets/aw-watcher-android-test/events",
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
    google_drive_folder: Path
    input_file_globs: list[str]
    last_sync_file: Path
    activitywatch_endpoint: str
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

    override = GOOGLE_DRIVE_FOLDER
    google_drive_folder = (
        Path(override).expanduser().resolve()
        if override
        else resolve_path(str(raw.get("google_drive_folder", "")), CONFIG_FILE.parent)
    )
    if google_drive_folder is None:
        raise ValueError("google_drive_folder is missing. Set it in config.json or GOOGLE_DRIVE_FOLDER.")

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

    return AppConfig(
        google_drive_folder=google_drive_folder,
        input_file_globs=input_file_globs,
        last_sync_file=last_sync_file,
        activitywatch_endpoint=str(raw["activitywatch_endpoint"]),
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


def file_matches(path: Path, patterns: Iterable[str]) -> bool:
    if not patterns:
        return True
    return any(path.match(pattern) for pattern in patterns)


def find_latest_file(folder: Path, patterns: list[str]) -> Path:
    if not folder.exists():
        raise FileNotFoundError(f"Google Drive folder not found: {folder}")
    files = [
        entry
        for entry in folder.iterdir()
        if entry.is_file() and file_matches(entry, patterns)
    ]
    if not files:
        raise FileNotFoundError(f"No matching files found in folder: {folder}")
    return max(files, key=lambda item: (item.stat().st_mtime, item.name.lower()))


def load_json_records(path: Path, encoding: str) -> list[dict[str, Any]]:
    with path.open("r", encoding=encoding) as handle:
        text = handle.read().strip()
    if not text:
        return []
    try:
        root = json.loads(text)
    except json.JSONDecodeError:
        return []

    if isinstance(root, list):
        items = root
    elif isinstance(root, dict):
        items = None
        for key in ("events", "records", "items", "rows", "data"):
            value = root.get(key)
            if isinstance(value, list):
                items = value
                break
        if items is None:
            items = [root]
    else:
        return []

    records: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            records.append(item)
    return records


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


def load_source_records(path: Path, encoding: str) -> list[dict[str, Any]]:
    records = load_json_records(path, encoding)
    if records:
        return records
    return parse_plain_text_records(path, encoding)


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
    try:
        config = build_config()
        last_sync = read_last_sync(config.last_sync_file)
        latest_file = find_latest_file(config.google_drive_folder, config.input_file_globs)
        log(f"Latest source file: {latest_file}")

        records = load_source_records(latest_file, config.encoding)
        if not records:
            log("No parseable records found. Nothing to send.")
            return 0

        events, newest_timestamp = collect_events(records, config, last_sync)
        if not events:
            log("No new events to import.")
            return 0

        post_events(config.activitywatch_endpoint, events, config.request_timeout_seconds)
        if newest_timestamp is not None:
            write_last_sync(config.last_sync_file, newest_timestamp)
        log(f"Imported {len(events)} event(s) successfully.")
        return 0
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


# Windows autostart:
# 1. Create a .bat file that calls: python "C:\path\to\google_drive_to_activitywatch.py"
# 2. Put the .bat into shell:startup for per-user login autostart, or create a Task Scheduler task
#    that runs once at logon/system start and exits after the script finishes.
