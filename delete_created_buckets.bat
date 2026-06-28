@echo off
setlocal

rem Deletes the ActivityWatch buckets created by the importer for FloneA54.
rem Adjust the bucket names here if your hostname changes.

set "AW_BASE_URL=http://localhost:5600"

for %%B in (
    aw-import-unlock_FloneA54
    aw-watcher-afk_FloneA54
    aw-watcher-window_FloneA54
) do (
    echo Deleting bucket %%B ...
    curl -f -sS -X DELETE "%AW_BASE_URL%/api/0/buckets/%%B?force=1"
    if errorlevel 1 (
        echo Failed to delete bucket %%B.
        exit /b 1
    )
)

echo Done.
exit /b 0
