# Changelog

All notable changes to Garmin Connect Uploader will be documented in this file.

## ⚡ IMPORTANT: How to Update

From **v1.0.1** onwards, the app includes a "Smart Migration" feature to handle older versions automatically. To update correctly:

1. **Keep it in the family:** Place the new `.exe` in the same folder as your previous version. This ensures your settings (`uploader_config.json`) and logs are preserved.
2. **Run the new version:** Once launched, the app will detect if the auto-start shortcut points to a previous file.
3. **One-Click Update:** A prompt will appear asking if you'd like to update the shortcut. Simply click **Yes** to ensure the new version is the one that launches at boot.

> [!IMPORTANT]  
> Your settings and logs are safe as long as the new EXE is in the same location as the old one. You can safely delete the old version's EXE file once the startup entry has been updated.
>
> **Upgrading from v1.0.2 or earlier:** The old Startup-folder shortcut (`GarminUploader.lnk`) and XOR-encrypted password in `uploader_config.json` are automatically migrated on first launch of v1.0.3. No manual steps required.

## [1.1.0] - TBD

### 🔐 Major Authentication Upgrade (1.1.0)

- **NEW: Mobile SSO Authentication:** Upgraded to `garminconnect` v0.3.1 which uses Garmin's official mobile SSO authentication flow (same as the Android app). This replaces the deprecated `garth` library that was causing authentication failures and rate limiting issues.
- **More reliable authentication:** The new mobile SSO endpoint (`sso.garmin.com/mobile/api/login`) is actively maintained by Garmin and significantly more stable than the previous method.
- **Automatic token refresh:** Authentication tokens now auto-refresh indefinitely without user interaction, eliminating the need for periodic re-authentication.

### Added (1.1.0)

- **Two-Factor Authentication (MFA/2FA) support:** The app now fully supports Garmin accounts with two-step verification enabled. When logging in for the first time (or when credentials change), you'll be prompted to enter your 6-digit verification code. Authentication tokens are securely saved and automatically reused, so you only need to enter the MFA code once.
- **Test & Login button:** Added a dedicated "Test & Login" button next to the password field in Garmin Settings. Use this to manually verify your Garmin credentials and save authentication tokens without triggering a full sync.
- **Visual login status indicator:** A green checkmark (✓) and "Logged in" text appear next to the password field when you have a valid Garmin session, providing clear visual feedback.
- **Smart auto-start behavior:** When the app starts with Windows:
  - If you have saved tokens: Silently resumes session and starts monitoring without any login prompts
  - If no tokens exist: Keeps window open and prompts you to click "Test & Login" instead of attempting automatic authentication
- **Experimental Wahoo Edge spoof mode:** Added an opt-in setting to process Wahoo uploads through a best-effort Garmin Edge compatibility path. Modified files are written to `uploaded/modified`, and detailed logs now show whether each upload used conversion, metadata modification, or fallback.
- **In-app update checker:** Added a `Check for updates` button in the About window that reads `version.json` from GitHub and compares against the running app version.
- **Clickable release destination:** When an update is available, the app now shows a clean `GitHub Releases` link plus an `Open` button.

### Changed (1.1.0)

- **Smarter credential validation:** The app now only prompts to test Garmin credentials when they've actually changed, preventing unnecessary MFA prompts every time you save settings. The login state is tracked and preserved across sessions.
- **Eliminated retry loops:** Login attempts are now single-try instead of 3 retries to avoid triggering Garmin's rate limiting. If login fails, you'll get a clear error message instead of multiple failed attempts.
- **Better rate limit handling:** Added specific error detection and user-friendly messaging for Garmin's rate limiting (HTTP 429 errors), with clear instructions on what to do.
- **Persistent login state:** Once you successfully login with "Test & Login", the app remembers you're logged in and won't attempt to re-authenticate when you start auto-sync or save settings.
- **Experimental spoof fallback behavior:** In experimental Wahoo mode, conversion/modification now retries automatically and, if still unsuccessful, uploads the original file unchanged (without creating an extra fallback copy).
- **Cleaner bottom action layout:** Removed the old `Actions` heading/icon, moved core controls upward, and placed `About & update` on its own row for better visual balance.
- **Updated experimental mode naming/help text:** Renamed the setting to `Experimental Garmin mode` and refreshed the info dialog wording to clarify challenge credit and metric timing expectations.

### Fixed (1.1.0)

- **Fixed authentication failures** caused by Garmin deprecating the old `garth` library authentication method. The new mobile SSO flow is the official, supported method.
- **Fixed rate limiting issues** where the app would trigger Garmin's security measures by making too many login attempts on startup or during normal operation.
- **Fixed redundant login attempts** - the app now properly reuses saved authentication tokens instead of logging in every time you start auto-sync or restart the application.

## [1.0.6] - 2026-03-20

### Changed (1.0.6)

- **TrainerDay activity titles:** When uploading TrainerDay workouts, filenames like `2026-03-20 18-32-32 - Torque Blocks.tcx` are now parsed so that the Garmin activity name is set to the part after the dash (for example, "Torque Blocks").
- **More reliable TrainerDay title mapping:** Added a short polling step after each TrainerDay upload to wait for Garmin to finish processing and then identify the newly created activity before renaming it, reducing the chance of renaming the wrong activity.

## [1.0.5] - 2026-02-25

### Added (1.0.5)

- **TrainerDay support** as a third app source alongside Wahoo and MyWhoosh. TrainerDay uses the same Dropbox-based folder structure as Wahoo and the same upload-and-move-to-`uploaded` behaviour, and supports both `.FIT` and `.TCX` workout files.

### Changed (1.0.5)

- **Refined Folder Settings UI** with collapsible sections and status-only app headers for Wahoo, MyWhoosh, and TrainerDay. Each header shows a status pill (for example: *Not configured*, *Folder missing*, *Ready*), and the sync logic automatically skips apps that are not in a ready state.
- **Improved visuals and layout:** Larger app logos for better readability and automatic window height adjustment based on the expanded/collapsed sections, reducing empty space when sections are collapsed.
- **TrainerDay quality-of-life tweaks:** Added an in-app TrainerDay help dialog explaining how to connect TrainerDay to Dropbox and where to find the exported folder on disk.
- **Dual-build releases:** Now shipping both a single-file `.exe` and a folder build (`.zip`). The folder build is less likely to trigger Windows Defender ML heuristics. See README for details.
- **Added `CHECKSUMS.txt`** with SHA-256 hashes for verifying release authenticity.

## [1.0.4] - 2026-02-09

### Changed (1.0.4)

- **Reverted auto-start from registry back to Startup-folder shortcuts**, using a lightweight temporary VBScript executed by `cscript.exe` to create the `.lnk` file. The Python exe itself never calls COM or PowerShell directly. The registry `HKCU\...\Run` approach introduced in v1.0.3 triggered `Wacapew.A!ml` detections in Windows Defender.
- Any leftover registry `Run` entry from v1.0.3 is automatically cleaned up on first launch.

### Fixed (1.0.4)

- **Fixed Windows Defender `Wacapew.A!ml` false positive** by removing all `winreg` registry writes. The exe no longer modifies `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
- **Fixed settings/config not loading at Windows startup.** The config file path was relative, so when Windows launched the app at boot (working directory `C:\Windows\System32`) it couldn't find `uploader_config.json`. The path is now resolved to an absolute path based on the exe's directory.
- **Fixed "OAuth1 token is required" upload error** caused by stale Garmin sessions not being detected. The app now verifies the session before each sync and re-authenticates if expired. Failed session logins also properly reset the client so credential-based login can take over.
- **Improved early-boot password retrieval.** Added a retry with short delay for Windows Credential Manager reads, plus a safe base64 config-file fallback so credentials are always available even if keyring isn't ready yet.

## [1.0.3] - 2026-02-05

### Changed (1.0.3)

- **Windows auto-start now uses the registry** (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`) instead of dropping a `.lnk` shortcut in the Startup folder. This is the standard, Defender-friendly approach and eliminates the need for `WScript.Shell` COM objects and PowerShell.
- **Password storage moved to Windows Credential Manager** via the `keyring` library, replacing the old XOR + Base64 obfuscation. A simple base64 fallback is kept in `uploader_config.json` for early-boot resilience.
- Removed dependency on `pywin32` / `win32com.client`; replaced with the built-in `winreg` module and the `keyring` package.

### Fixed (1.0.3)

- **Reduced Windows Defender false-positive triggers** by removing all PowerShell invocations (including `-ExecutionPolicy Bypass`), COM-based shortcut manipulation, and XOR + Base64 encoding patterns that match common malware heuristics.

### Migration (1.0.3)

- On first launch, any existing `GarminUploader.lnk` in the Startup folder is automatically deleted and replaced with a registry entry.
- Existing XOR-encrypted passwords in `uploader_config.json` are automatically migrated to Windows Credential Manager and removed from the config file.

## [1.0.2] - 2026-01-01

### Added (1.0.2)

- Windows build now uses a standalone **Nuitka onefile** executable to reduce antivirus false positives (especially Windows Defender) while keeping everything self-contained.
- Dedicated **uploads-only** log file `garmin_uploads.log` that records just successful upload events, with clear daily separators.
- New **"View Uploads Log"** button in the About dialog to inspect upload history directly from the app.
- More robust resource bundling for compiled builds so the main icon, app logo, developer logo, and GitHub logo all display correctly in the About window.

### Fixed (1.0.2)

- Improved handling of Garmin **session tokens** so that stale sessions are detected and recovered more reliably instead of silently failing uploads.
- Fixed edge cases in Windows auto-start shortcut migration when upgrading between versions compiled with different toolchains.
- Resolved layout issues in the About dialog where the Close button could be partially hidden on some DPI / scaling combinations.

### Changed (1.0.2)

- Logging now consists of:
  - The main rotating log `garmin_uploader.log` (10MB, 3 backups), and
  - A separate non-rotating upload log `garmin_uploads.log` for a clean history of uploaded files.
- Logs are always written next to the running executable (for both script and compiled modes), making upgrades and troubleshooting simpler.
- Simplified text in the About dialog – log file paths are now accessed via the built-in log viewers instead of being shown directly.

## [1.0.1] - 2025-12-29

### Added

- MyWhoosh sync behavior warning in main window with link to detailed documentation
- Log file auto-rotation (10MB limit with 3 backup files for ~3 months of history)
- Built-in log viewer that opens at the latest entries instead of external text editor
- Visual icons in logs for easier scanning (✅ success, ❌ error, ⚠️ warning)
- Persistent last sync/upload status that survives app restarts
- Automatic detection and update of old version auto-start shortcuts on first launch
- Interactive close button behavior: prompts user to run in background or close app
- "Minimize to Tray" button in Actions section for explicit tray minimization

### Fixed

- Bug where app would try to upload files from the "uploaded" subfolder
- GitHub repository link now points to correct URL
- Log viewer now allows text search (Ctrl+F) and selection while preventing edits
- GUI window scaling issues on high-DPI displays (user report) - added DPI awareness
- Unclear minimize to tray behavior - users weren't aware of tray functionality (user report)

### Changed

- Log viewer now auto-scrolls to show latest entries first
- Updated README with new log retention policy and viewer behavior
- Optimized startup timing for Windows auto-start (reduced from 3.5s to 1s)
- Improved folder settings layout with wider entry fields and compact help buttons
- Enhanced MyWhoosh warning with larger icon, improved layout, and clearer messaging
- Adjusted window size to 600x825 with enforced minimum dimensions
- Cleaner UI spacing and alignment throughout

## [1.0.0] - 2025-12-28

### Initial Release

- Automatic upload of Wahoo and MyWhoosh .FIT files to Garmin Connect
- Secure password encryption using hardware-linked keys
- Auto-sync with configurable check intervals
- System tray support with minimize functionality
- Windows auto-start on boot
- Custom GUI with logo and developer attribution
- Detailed activity logging
- Folder validation and credential testing
