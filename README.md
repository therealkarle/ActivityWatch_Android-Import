# ActivityWatch Google Drive Import

## Intro

I wanted a script that takes the latest exported Android activity file from Google Drive and imports it into ActivityWatch, so I built this.

ActivityWatch Google Drive Import downloads the newest matching file from a shared Google Drive folder, parses ActivityWatch export data, and uploads the events into your local ActivityWatch instance. It can also mirror selected window buckets into AFK buckets, so Android window activity shows up with sensible AFK state instead of a second device-specific bucket.

It is designed for:
- people who want to export ActivityWatch data from Android to Google Drive
- anyone who wants a simple, incremental import into a local ActivityWatch instance
- users who want AFK duplication for imported window buckets
- GitHub repositories that need clear, reproducible setup instructions

## Main Features

- Downloads the newest matching file from a Google Drive folder.
- Uses a Google Cloud service account for authentication.
- Imports ActivityWatch export JSON, nested bucket exports, or flattened event lists.
- Supports incremental sync through `last_sync.txt`.
- Creates missing ActivityWatch buckets automatically.
- Can mirror selected buckets into `aw-watcher-afk_*` buckets.
- Can keep or skip the original bucket when AFK duplication is enabled.
- Accepts both JSON exports and plain-text timestamped event logs.
- Supports configurable timestamp, duration, and payload field names.

## Quickstart Guide

1. Create a Google Cloud project and enable the Google Drive API.
2. Create a service account and download its JSON key.
3. Share the target Google Drive folder with the service account email address.
4. Copy `config.example.json` to `config.json`.
5. Point `google_drive_service_account_file` to your downloaded key.
6. Set `google_drive_folder_id` to the Drive folder ID.
7. Make sure ActivityWatch is running locally.
8. Run `python aw_sync_android_gdrive.py`.

## Table of Contents

- [Intro](#intro)
- [Main Features](#main-features)
- [Quickstart Guide](#quickstart-guide)
- [All Features Explained](#all-features-explained)
- [Extensive Installation Guide](#extensive-installation-guide)
- [Google Cloud Setup](#google-cloud-setup)
- [Android Export Setup](#android-export-setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [ActivityWatch Buckets](#activitywatch-buckets)
- [Windows Autostart](#windows-autostart)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Security and Privacy](#security-and-privacy)
- [How It Works](#how-it-works)

## All Features Explained

### Google Drive Source

The script connects to the Google Drive API through a service account. It scans the configured folder, sorts files by modification time, and selects the newest file that matches the configured glob patterns.

### Incremental Import

The importer remembers the newest imported timestamp in `last_sync.txt`. On the next run it only imports records with a timestamp strictly greater than the stored value.

### Export Format Handling

The importer understands several export shapes:
- a regular ActivityWatch export JSON with a `buckets` object
- a flattened JSON array or object tree containing event records
- a plain-text log with ISO-like timestamps at the beginning of each line

### ActivityWatch Import

For each parsed record the script:
- normalizes the timestamp
- copies or derives the payload
- preserves duration when it exists
- uploads the event into the target bucket
- creates the bucket first if it does not already exist

### AFK Duplication

You can list bucket IDs in `afk_duplicate_bucket_ids` to mirror them into a matching `aw-watcher-afk_*` bucket. For window buckets, the script converts the imported events into alternating `not-afk` and `afk` spans using a fixed 2-minute idle gap.

### Original Bucket Control

If `afk_duplicate_upload_original_bucket` is `true`, the original bucket is uploaded in addition to the AFK copy. If it is `false`, only the AFK bucket gets the events.

### Hostname Handling

The script rewrites imported bucket IDs so they do not collide with local ActivityWatch bucket naming. If imported metadata does not contain a usable hostname, it falls back to `activitywatch_hostname` or the local machine hostname.

### Logging

The script prints progress messages to the console. Errors are written to stderr and the process exits with a non-zero status code.

## Extensive Installation Guide

### 1. Install Python

Use Python 3.10 or newer. Confirm it is available:

```powershell
python --version
```

### 2. Clone the Repository

```powershell
git clone https://github.com/<your-user>/<your-repo>.git
cd <your-repo>
```

### 3. Create a Virtual Environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, use the CMD activation script instead:

```powershell
.venv\Scripts\activate.bat
```

### 4. Install Dependencies

Install the packages used by the importer:

```powershell
python -m pip install google-auth[requests]
```

The script also uses the Python standard library modules that ship with Python.

### 5. Create the Local Configuration

Copy the example configuration:

```powershell
Copy-Item config.example.json config.json
```

Then edit `config.json` and provide:
- the Google Drive folder ID
- the path to the service account JSON key
- your ActivityWatch base URL
- the host name ActivityWatch should use as fallback
- the bucket IDs that should be duplicated into AFK buckets

### 6. Verify ActivityWatch

Make sure the local ActivityWatch app is running and accepting requests on the configured base URL before you launch the importer.

### 7. Run the Program

Start the main script from the repository root:

```powershell
python aw_sync_android_gdrive.py
```

## Google Cloud Setup

This is the part that usually blocks first-time setup, so here is the full flow.

### 1. Create or Select a Project

Open the Google Cloud Console and choose a project for this importer, or create a new one.

### 2. Enable the Drive API

Enable the Google Drive API for that project. The script calls the Drive API directly, so this step is required.

### 3. Create a Service Account

Create a service account for the importer. The service account is the identity the script uses to access the Drive folder.

### 4. Download a JSON Key

Generate and download a JSON key for the service account.

Store the key locally, for example in:

```text
env\GoogleServiceAcountKey.json
```

You can use a different path, but the path in `config.json` must match the real file location.

### 5. Share the Drive Folder

Share the target Google Drive folder with the service account email address.

This is important:
- sharing the folder is what gives the service account read access
- the script uses the Drive folder ID, not a personal Drive login
- if the folder is not shared, the API call will fail even if the JSON key is valid

### 6. Use the Folder ID

Copy the folder ID from the Drive folder URL and place it into `google_drive_folder_id`.

Example:

```text
https://drive.google.com/drive/u/0/folders/1li1VUemrnpItesekEeeHN-_6COnUHgLc
```

The folder ID in that example is:

```text
1li1VUemrnpItesekEeeHN-_6COnUHgLc
```

### 7. Keep the Key Local

Do not commit the service account key file. It is a secret credential and should stay on your machine only.

## Android Export Setup

If your source data comes from an Android export workflow, keep the exported file format stable so the importer can recognize it reliably.

### Recommended Export Shape

The script works best with:
- a raw ActivityWatch export JSON file
- a file containing bucket data under `buckets`
- a flattened event list where each item includes a timestamp

### Full Android Export Flow

The recommended setup is:
- MacroDroid triggers a nightly export
- ActivityWatch is briefly opened so the local server is awake
- the export is fetched from `http://localhost:5600/api/0/export`
- the file is saved directly into the shared Google Drive folder
- the PC importer picks up the newest file on the next run

### MacroDroid Setup on Samsung

Create one MacroDroid macro with a nightly trigger and these actions:

#### Trigger

1. Open **MacroDroid** and create a new macro.
2. Add a trigger.
3. Choose **Date/Time**.
4. Select **Regular Time**.
5. Set the time to something like `02:00`.

#### Actions

1. Add an action to **start the ActivityWatch app**.
2. Add a short **delay of 3 seconds**.
3. Add an **HTTP Request** action.
4. Set the request method to `GET`.
5. Use this URL:

```text
http://localhost:5600/api/0/export
```

6. Enable **Save to File**.
7. Open the file picker.
8. In the Samsung/Android file manager, open the side menu and select **Google Drive**.
9. Navigate to the shared folder `ActivityWatch_Android`.
10. Save the file as `aw_export.json`.
11. Enable **Overwrite existing file** so the importer always sees the latest export.

### Constraints

Add constraints so the macro only runs in good conditions:
- connected to your home Wi-Fi
- device plugged in

### Samsung Battery Optimization

Disable battery optimization for both apps:
- `MacroDroid`
- `ActivityWatch`

Set both apps to **Unrestricted** so Android does not kill them overnight.

### Timestamp and Field Names

If your export uses different field names, adjust these config values:
- `timestamp_fields`
- `duration_fields`
- `payload_fields`

The defaults already cover common variants like:
- `timestamp`
- `time`
- `datetime`
- `date`
- `start`
- `created_at`

### Plain-Text Export

If the file is plain text, each line should begin with an ISO-like timestamp. The importer will extract the timestamp and treat the rest of the line as the message payload.

### Google Drive Upload Target

Make sure the file you upload to Google Drive is a normal file, not a Google Docs document. The importer downloads the file content directly and does not export Google Docs automatically.

## Configuration

The application reads `config.json` from the repository root. Keep this file out of version control. The repository already ignores common local secrets and runtime files.

### Top-Level Settings

| Setting | Type | Description |
| --- | --- | --- |
| `google_drive_folder_id` | string | ID of the shared Drive folder that contains the newest export file. |
| `google_drive_service_account_file` | string | Path to the Google service account JSON key file. |
| `input_file_globs` | array of strings | Filename patterns used to filter the newest file. |
| `last_sync_file` | string | Local file that stores the newest imported timestamp. |
| `activitywatch_base_url` | string | Base URL of your ActivityWatch server. Default: `http://localhost:5600`. |
| `activitywatch_hostname` | string | Fallback hostname used when imported metadata does not include one. |
| `afk_duplicate_bucket_ids` | array of strings | Bucket IDs that should also be mirrored into AFK buckets. |
| `afk_duplicate_upload_original_bucket` | boolean | Upload the original bucket as well as the AFK copy. |
| `timestamp_fields` | array of strings | Candidate field names for timestamps. |
| `duration_fields` | array of strings | Candidate field names for durations. |
| `payload_fields` | array of strings | Candidate field names for nested payload objects. |
| `encoding` | string | File encoding used when reading the source export. |
| `request_timeout_seconds` | integer | Timeout for Google Drive and ActivityWatch HTTP calls. |

### Example

```json
{
  "google_drive_folder_id": "1li1VUemrnpItesekEeeHN-_6COnUHgLc",
  "google_drive_service_account_file": "env\\GoogleServiceAcountKey.json",
  "input_file_globs": ["*"],
  "last_sync_file": "last_sync.txt",
  "activitywatch_base_url": "http://localhost:5600",
  "activitywatch_hostname": "FloneA54",
  "afk_duplicate_bucket_ids": ["aw-watcher-window_FloneA54"],
  "afk_duplicate_upload_original_bucket": true,
  "timestamp_fields": ["timestamp", "time", "datetime", "date", "start", "created_at"],
  "duration_fields": ["duration", "length", "seconds"],
  "payload_fields": ["data", "event", "payload"],
  "encoding": "utf-8",
  "request_timeout_seconds": 15
}
```

## Usage

All commands below assume you run them from the repository root.

### Normal Run

```powershell
python aw_sync_android_gdrive.py
```

The script runs once, finds the newest matching file in Google Drive, imports any new events, and updates `last_sync.txt`.

### Repeated Runs

Use Windows Task Scheduler or another scheduler if you want regular syncs. The script is idempotent with respect to already imported timestamps, so repeated runs do not re-import the same events.

## ActivityWatch Buckets

### Bucket Creation

The importer creates the target bucket on first use if it is missing. This keeps setup simple and avoids manual bucket bootstrapping.

### Android Window Buckets

Android window exports are treated specially:
- the original imported bucket keeps the event data
- the AFK mirror bucket is built from the window activity and uses a not-afk/afk timeline

### Duplicate Protection

The script will not re-import events that are older than or equal to the timestamp stored in `last_sync.txt`.

## Windows Autostart

Two startup helpers are mentioned in the source comments for manual setup:

1. Create a `.bat` file that runs `python "C:\path\to\aw_sync_android_gdrive.py"`.
2. Put the batch file into the Windows startup folder or schedule it with Task Scheduler.

If you prefer a hidden startup workflow, launch the batch file through a `.vbs` wrapper.

## Testing

Run the unit tests with the Python standard library:

```powershell
python -m unittest discover -s tests
```

You can also run the specific test module:

```powershell
python -m unittest tests.test_google_drive_to_activitywatch
```

The test suite covers:
- config parsing for AFK duplication
- AFK bucket ID rewriting
- original bucket upload toggling
- duration preservation for imported window events
- AFK state generation from window activity

## Troubleshooting

### `google_drive_folder_id` is missing

- Set `google_drive_folder_id` in `config.json`.
- Use the folder ID from the Drive URL, not the full URL itself.

### Service account file cannot be found

- Check `google_drive_service_account_file`.
- Use a path that exists on your machine.
- If you use a relative path, it is resolved relative to the repository root.

### Google Drive returns no matching files

- Verify that the folder contains at least one file.
- Check `input_file_globs`.
- Make sure the filename actually matches the glob patterns.

### Access is denied by Google Drive

- Confirm that the folder is shared with the service account email address.
- Confirm that the Drive API is enabled in the Google Cloud project.
- Confirm that the JSON key belongs to the service account you intended to use.

### ActivityWatch API is unavailable

- Confirm ActivityWatch is running.
- Verify the value of `activitywatch_base_url`.
- The default is `http://localhost:5600`.

### No events are imported

- The file may already have been imported.
- Check whether `last_sync.txt` contains a timestamp newer than the source data.
- Make sure the source export actually contains timestamped records.

### AFK duplication does not happen

- Add the exact bucket ID to `afk_duplicate_bucket_ids`.
- Check whether the source bucket is recognized as a window bucket.
- Remember that the script only builds AFK spans from window activity, not from every export type.

## Security and Privacy

- `config.json` contains local secrets and should stay out of version control.
- The service account JSON key is sensitive and should not be shared.
- `last_sync.txt` is local state and usually should not be committed.
- Imported ActivityWatch data can still contain sensitive app names, window titles, and usage patterns.

## How It Works

1. The script loads `config.json`.
2. It authenticates to Google Drive with the service account JSON key.
3. It finds the newest matching file in the target Drive folder.
4. It downloads that file to a temporary directory.
5. It parses the export into bucket records or event lists.
6. It skips records that are already covered by `last_sync.txt`.
7. It normalizes the events for ActivityWatch.
8. It creates target buckets if needed.
9. It uploads the events into ActivityWatch.
10. It writes the newest imported timestamp back to `last_sync.txt`.

## License

Add your project license here if you plan to publish the repository publicly.
