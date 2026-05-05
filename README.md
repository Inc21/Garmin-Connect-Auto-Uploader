# Garmin Connect Uploader

Automatically upload workout activities from Wahoo, MyWhoosh, and TrainerDay to Garmin Connect.

Version 1.1.2 | Windows Desktop Application (Nuitka onefile + folder build)

---

## What It Does

This app automatically syncs your workout files to Garmin Connect so your activities appear in your Garmin dashboard without manual uploads.

- **Wahoo** via Dropbox (.FIT files)
- **MyWhoosh** from its local cache (.FIT files)
- **TrainerDay** via Dropbox (.TCX / .FIT files)

**Key Features:**

- ✅ Automatic background syncing
- ✅ Starts with Windows (optional)
- ✅ Secure password encryption
- ✅ Two-Factor Authentication (MFA/2FA) support with Garmin's official mobile SSO
- ✅ One-time MFA login with auto-refreshing tokens (no repeated authentication)
- ✅ Visual login status indicator with "Test & Login" button
- ✅ Detailed activity logging
- ✅ System tray support

---

## ⚠️ Important Sync Behavior

The app handles the two platforms differently based on how they store files:

- **Wahoo (Persistent):** If you connect a Dropbox account that has a history of Wahoo rides, the app **will** detect those files and upload your history to Garmin Connect automatically.
- **MyWhoosh (Volatile):** MyWhoosh only stores the **most recent** activity in its local cache and overwrites it when you start a new session.
  - **The Catch:** Your PC doesn't always have to be on for the sync to work eventually, **but** if you record multiple MyWhoosh activities while the app is closed (or the PC is off), the uploader will only "see" and sync the **very last one** when it finally boots up.
  - **Recommendation:** Use the "Start with Windows" option so the app is always ready to catch MyWhoosh files before they are lost.

---

## 🔒 Security & Privacy

I built this originally as a personal Python script to solve my own manual upload frustrations. Because this app handles Garmin credentials, transparency is a priority:

- **Local Only:** Your credentials are never sent to any server except Garmin’s official Garmin Connect endpoint.
- **Windows Credential Manager:** Your Garmin password is stored primarily in Windows Credential Manager via the `keyring` library. You can remove it at any time via the Windows *Credential Manager* control panel.
- **Config-file fallback (for early boot only):** A simple Base64-encoded copy of your password is kept in `uploader_config.json` as a fallback if Credential Manager is not available at boot. This is **not meant as strong encryption**, just enough to avoid plain text in the config file.
- **No custom crypto:** There is no XOR or “home‑grown” encryption in the current versions; standard libraries are used instead.
- **No registry writes:** Auto-start is handled only via a Startup-folder shortcut (`GarminUploader.lnk`), never the `HKCU\...\Run` registry key.
- **Open Source:** The full source code is available here on GitHub for anyone to audit or rebuild.

---

## Download & Install

### ⚡ Updating from a Previous Version?

**Good news!** The app automatically detects and updates Windows auto-start shortcuts when you first run a new version. Simply:

1. Download the new `GarminUploader-v1.0.x.exe`
2. Place it in the **same folder** as your old version
3. Run it once - if you had "Start with Windows" enabled, the app will detect the old shortcut and offer to update it
4. Your existing settings and logs are preserved automatically (no reconfiguration needed!)

**For folder builds:** If you keep your configuration and log files in a parent folder (for example `C:\GarminUploader\`) and extract each new `GarminUploader-v1.0.x-folder.zip` into a subfolder under that parent (for example `C:\GarminUploader\GarminUploader-v1.0.6-folder\`), the new version will automatically reuse `uploader_config.json`, `garmin_uploader.log`, and `garmin_uploads.log` from the parent folder. You do **not** need to copy these files into each new version folder.

---

### Step 1: Download

**Two download options are available:**

- **Folder build (recommended):** `GarminUploader-v1.1.2-folder.zip` — Most users; less likely to trigger Windows Defender.
- **Single-file build:** `GarminUploader-v1.1.2.exe` — Advanced users who prefer a single executable.

#### Option A: Folder build (recommended)

1. Download `GarminUploader-v1.1.2-folder.zip` from Releases
2. Extract the ZIP to a folder (e.g., `C:\GarminUploader\` or your Desktop)
3. Run `GarminUploader.exe` from the extracted folder

#### Option B: Single-file build

1. Download `GarminUploader-v1.1.2.exe` from Releases
2. Place it anywhere you like (Desktop, Documents, etc.)
3. Double-click to run

**Note:** The single-file build is a packed Nuitka executable which may trigger Windows Defender ML heuristics. If Defender blocks or quarantines it, use the folder build instead. See [Windows Defender / Antivirus Blocks the App](#️-windows-defender--antivirus-blocks-the-app) for details.

---

## First Time Setup

### Step 2: Enter Garmin Credentials & Login

1. Enter your **Garmin Connect email**
2. Enter your **Garmin Connect password**
3. Click **"Test & Login"** to authenticate with Garmin Connect
4. Click **"Save Settings"** button

**🔐 Authentication & Two-Factor (MFA/2FA):**

The app uses Garmin's official mobile SSO authentication (same as the Android app) for secure, reliable login:

- **First login:** Click "Test & Login" to authenticate with Garmin
- **MFA/2FA support:** If you have two-step verification enabled, a dialog will pop up asking for your 6-digit verification code
  - Enter the code from your authenticator app or the code Garmin texts/emails you
  - Authentication tokens are securely saved locally and **auto-refresh indefinitely**
  - You'll only need to enter the MFA code **once** (unless you change your password or clear the app's session data)
- **Visual confirmation:** A green checkmark (✓) and "Logged in" text appear when you have a valid session
- **Persistent login:** Once logged in, the app automatically reuses your saved tokens - no need to re-authenticate on every startup or sync

**Important:** Your password is encrypted and stored in Windows Credential Manager. The app only validates credentials when they change, not every time you save settings. Authentication tokens are stored in `%LOCALAPPDATA%\GarminUploader\session\` and are automatically managed by the app.

### Step 3: Configure Your Folders

You need **at least one folder** configured (Wahoo, MyWhoosh, or TrainerDay):

#### **Option A: Wahoo (via Dropbox)**

1. Click **"📖 Help"** button next to Wahoo Folder
2. Follow the instructions to:
   - Create free Dropbox account
   - Connect Wahoo ELEMNT to Dropbox
   - Install Dropbox on PC
3. Click **"Browse"** and select your Dropbox Wahoo folder:

   ```text
   C:\Users\YourName\Dropbox\Apps\WahooFitness
   ```

#### **Option B: MyWhoosh**

1. Click **"📖 Help"** button next to MyWhoosh Folder
2. Follow the instructions to find your MyWhoosh cache folder
3. Click **"Browse"** and navigate to:

   ```text
   C:\Users\YourName\AppData\Local\MyWhoosh\MyWhoosh\Cache\Cache_Data
   ```

**Tip:** Press `Win + R`, paste `%LOCALAPPDATA%\MyWhoosh\MyWhoosh\Cache\Cache_Data`, press Enter

#### **Option C: TrainerDay (via Dropbox)**

1. Click **"📖 Help"** button next to TrainerDay Folder
2. Follow the instructions to:
   - Open <https://app.trainerday.com> and log in
   - Click your user icon → **Connections** and connect TrainerDay to Dropbox / enable activity sync
3. After the first sync, Dropbox will contain a TrainerDay folder, for example:

   ```text
   C:\Users\YourName\Dropbox\TrainerDay
   C:\Users\YourName\Dropbox\Apps\TrainerDay
   ```

4. Click **"Browse"** and select that TrainerDay folder.

### Step 4: Set Check Interval (Optional)

Default is **5 minutes**. Adjust if you want faster/slower checking.

### Step 5: Save Settings

Click **"Save Settings"** - this will:

- ✅ Validate your Garmin credentials
- ✅ Encrypt your password
- ✅ Save all settings

---

## Daily Use

### Manual Upload (One-Time)

1. Click **"Sync Now"** button
2. App will upload any new .FIT files immediately
3. Check status at bottom of window

### Automatic Background Uploads

**For set-and-forget automation:**

1. ✅ Check **"Start with Windows"**
2. ✅ Check **"Start Auto-Sync"** checkbox
3. Click **"Start Auto-Sync"** button

**What happens:**

- App checks for new files every 5 minutes (or your interval)
- Shows status updates at bottom
- Can minimize to system tray (bottom-right corner)

**To minimize to tray:**

- Click the **[X]** close button
- If auto-sync is running, you'll be asked if you want to minimize to tray
- Click **YES** to keep it running in background
- Look for Garmin icon in system tray

**To restore from tray:**

- Click the Garmin icon in system tray
- Select "Show"

---

## Auto-Start on Windows Boot

**Make it fully automatic:**

1. ✅ Check **"Start with Windows"**
2. ✅ Ensure **"Start Auto-Sync"** is also checked (optional but recommended)
3. Click **"Save Settings"**
4. Restart your computer to test

**What happens on boot:**

- App starts automatically (minimized to tray)
- Begins auto-sync if you have credentials and folders configured
- Runs silently in background
- Check system tray for Garmin icon

**To disable auto-start:**

- Uncheck "Start with Windows"
- Click "Save Settings"

---

## Files Created

The app stores its configuration and log files alongside the app, usually in a shared parent folder so that new versions can reuse them:

1. **`uploader_config.json`** – Your settings (password is encrypted)
2. **`garmin_uploader.log`** – Main activity log with timestamps (auto-rotates at 10MB, keeps 3 backups)
3. **`garmin_uploads.log`** – Dedicated uploads-only log that records successful uploads with daily separators (easier to review your upload history).

**Recommended layout for folder builds (for easy upgrades):**

```text
C:\GarminUploader\
    uploader_config.json
    garmin_uploader.log
    garmin_uploads.log
    GarminUploader-v1.1.2-folder\
        GarminUploader.exe
```

If these files exist in the parent folder (for example `C:\\GarminUploader\\`), any new version you place in a subfolder under that parent will automatically reuse them. You do **not** need to copy the files into each new version folder.

**View the logs:**

- Click **"ℹ️ About"** button
- Click **"📄 View Log"** for the main log
- Click **"📄 View Uploads Log"** for the uploads-only log (read-only viewer)

**What's logged (main log):**

- App startup/shutdown
- Garmin login attempts (success/failure)
- File uploads (filename, timestamp)
- Errors and warnings with visual icons (✅ success, ❌ error, ⚠️ warning)
- Auto-sync start/stop
- Settings changes

**Log retention:**

- `garmin_uploader.log` automatically rotates when it reaches 10MB
- Keeps 3 backup files (~3 months of history)
- `garmin_uploads.log` is a single running file with date markers so you can see what was uploaded each day

---

## Troubleshooting

### ❌ "Invalid Credentials" Error

- Double-check email/password at garmin.com
- Click "Save Settings" again to re-test
- Check log file for detailed error

### ❌ "No Folders Configured" Error

- You must configure at least ONE folder (Wahoo, MyWhoosh, or TrainerDay)
- Click Browse to select folder
- Click Help button for setup instructions

### ❌ Auto-Start Not Working After Reboot

1. Press `Win + R`, type: `shell:startup`, press Enter
2. Look for `GarminUploader.lnk` shortcut
3. If missing: Re-enable "Start with Windows" in app
4. If present: Check log file for startup errors
5. Make sure EXE location hasn't moved

### ❌ Files Not Uploading

- Click "Sync Now" to test immediately
- Check if .FIT files exist in your folders
- View log file for upload attempts
- Verify Garmin credentials are valid
- Check folder paths are correct

### ⚠️ "File Already Uploaded (409)" in Log

- This is normal - means Garmin already has this activity
- File is moved to "uploaded" subfolder anyway
- No action needed

### 🔍 Can't Find System Tray Icon

- Look in bottom-right corner of Windows taskbar
- Click small **^** arrow to show hidden icons
- Garmin logo should appear there

### 🛡️ Windows Defender / Antivirus Blocks the App

Because this app is a small, niche tool that logs in to a website, stores credentials, and can auto-start with Windows, some antivirus programs (especially Windows Defender's ML-based heuristics) may incorrectly flag it as suspicious.

**Why this happens:**

- The app is not code-signed (requires an expensive certificate)
- It combines network activity + credential storage + auto-start — patterns that malware also uses
- Packed single-file executables trip more heuristics than normal installers

**What you can do:**

1. **Try the folder build:** Download `GarminUploader-v1.1.2-folder.zip` instead of the single `.exe`. Unpacked builds are less likely to trigger false positives.

2. **Add an exception:** If you trust the source, add the app folder to Windows Defender's exclusion list:
   - Open **Windows Security** → **Virus & threat protection** → **Manage settings**
   - Scroll to **Exclusions** → **Add or remove exclusions**
   - Add the folder containing `GarminUploader.exe`

3. **Report the false positive to Microsoft:**
   - Go to: <https://www.microsoft.com/en-us/wdsi/filesubmission>
   - Select **Home user** → **Incorrectly detected as malware**
   - Upload the `.exe` file and submit

4. **Build from source:** If you prefer not to trust pre-built binaries:

   ```bash
   git clone https://github.com/Inc21/Garmin-Connect-Auto-Uploader.git
   cd Garmin-Connect-Auto-Uploader
   pip install -r requirements.txt
   python uploader_gui.py
   ```

**Verify authenticity:** Compare the SHA-256 hash of your download against `CHECKSUMS.txt` in the release.

---

## Uninstalling

1. Uncheck "Start with Windows" in app
2. Click "Save Settings"
3. Close the app
4. Delete `GarminUploader.exe`
5. Delete `uploader_config.json` and `garmin_uploader.log` (optional)

---

## Support

**Developer:** [inc21](https://github.com/Inc21)  
**Buy me a coffee:** [☕ Support](https://buymeacoffee.com/inc21)

---

## License

MIT License
