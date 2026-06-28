# Android ActivityWatch Setup via MacroDroid

This documentation describes the automated logging of window and app activities on the Android device and the passive export to a synchronized Google Drive folder. From there, the data is automatically imported into ActivityWatch on the PC.

---

## 1. Prerequisites & Apps

* **Android Device** with **MacroDroid** installed (Pro version recommended for unlimited macros).
* **Google Drive** App (logged in with the account that has access to the target sync folder).
* **ActivityWatch Android Watcher** (acting as the background logging source).

---

## 2. MacroDroid Configuration

The setup relies on automated HTTP requests and file operations triggered at specific intervals.

### Macro 1: Log Intervals & HTTP Requests
* **Trigger:** Regular Interval (e.g., every 10–15 minutes) or specific system events.
* **Actions:** * Wakes the ActivityWatch app to ensure the local server is running.
    * Fetches the current activity log data from the local ActivityWatch API (`http://localhost:5600/api/0/export`).
    * Saves the response locally as a temporary JSON file.

### Macro 2: Google Drive Export
* **Trigger:** Once a day at a specified night-time slot (e.g., `23:30`) or when charging.
* **Actions:**
    * Collects the generated log files.
    * Automatically uploads and overwrites the latest file in the dedicated Google Drive directory.
* **Target Folder (Google Drive):** `https://drive.google.com/drive/u/0/folders/1li1VUemrnpItesekEeeHN-_6COnUHgLc`

---

## 3. Data Structure & Validation

The exported data is written to the target bucket `aw-watcher-android-test`. A successful pass validates the following structure:

* **Format:** Events contain precise ISO timestamps (`timestamp`) along with the respective app and window metadata.
* **Chronology:** Data is captured seamlessly up to the execution timestamp.
* **Incremental Sync:** The PC importer uses a local tracking file (`last_sync.txt`) to process *only* events with a timestamp strictly greater than the last recorded entry, completely preventing duplicate events in the bucket.

---

## 4. Troubleshooting & Maintenance

* **API Timeout Errors:** If MacroDroid runs into a `SocketTimeoutException` (e.g., trying to hit `127.0.0.1` while the app is sleeping), ensure that **Battery Optimization** is set to **Unrestricted** for both ActivityWatch and MacroDroid in the Android system settings. Adding a 3-second delay action right after launching the app gives the local API server enough time to initialize.
* **Google Drive Sync Delay:** The PC-side runner searches for the file based on its *modification time* on the local drive. Make sure "Google Drive for Desktop" is actively running on your PC so the background sync is completed before the script executes.