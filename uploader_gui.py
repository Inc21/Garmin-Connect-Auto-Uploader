# flake8: noqa: E501
# GUI application for Garmin Connect automatic uploader
# Line length limit relaxed for readability in GUI code

# Fix DPI scaling issues on Windows (must be before tkinter import)
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import json
import os
import sys
import threading
import time
import datetime
import logging
import base64
import tempfile
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from garminconnect import Garmin
from PIL import Image, ImageTk
from pystray import Icon, Menu, MenuItem
import webbrowser
import shutil
try:
    import fitdecode
except ImportError:
    fitdecode = None
try:
    import keyring
except ImportError:
    keyring = None  # Falls back to config file storage if not available

# Configuration file (resolved to absolute path after _get_base_and_log_dirs)
_CONFIG_FILENAME = "uploader_config.json"

# Compute stable base/log directories so compiled builds reuse the same log in the exe folder
def _get_base_and_log_dirs():
    # Prefer the real executable/launcher location (handles Nuitka/PyInstaller onefile)
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        exe_path = os.path.abspath(sys.argv[0]) if sys.argv else os.path.abspath(sys.executable)
        exe_dir = os.path.dirname(exe_path)
        # BASE_DIR remains the embedded resource dir when available; fall back to exe dir
        base_dir = getattr(sys, "_MEIPASS", exe_dir)
        return base_dir, exe_dir
    # Script mode
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return script_dir, script_dir

def _resolve_existing_or_default(filename, default_dir):
    """Return a path for config/log files, preferring existing files.

    Priority:
    - Existing file in the parent of default_dir (shared across versioned folders)
    - Existing file in default_dir (legacy behavior)
    - Otherwise, create in the parent of default_dir when safe, else in default_dir
    """
    parent_dir = os.path.dirname(default_dir) if default_dir else ""
    parent_path = os.path.join(parent_dir, filename) if parent_dir else ""

    # Prefer an existing file in the parent directory so multiple versioned
    # folders (or different builds) automatically share the same files.
    if parent_path and os.path.isfile(parent_path):
        return parent_path

    # Fall back to any existing file in the current (exe) directory to remain
    # compatible with older versions that wrote files there.
    current_path = os.path.join(default_dir, filename) if default_dir else filename
    if os.path.isfile(current_path):
        return current_path

    # No existing file anywhere: decide where to create a new one.
    # Prefer the parent directory when it is a normal folder (not a drive root),
    # so future versioned folders will automatically reuse it.
    def _is_drive_root(path: str) -> bool:
        if not path:
            return False
        drive, tail = os.path.splitdrive(path)
        tail = tail.replace("/", "\\").rstrip("\\")
        # e.g. "C:\\" -> tail == ""
        return bool(drive) and tail == ""

    if parent_dir and not _is_drive_root(parent_dir):
        return parent_path

    # As a last resort (e.g. onefile exe placed directly in an app folder
    # whose parent is the drive root), create the file next to the exe.
    return current_path

BASE_DIR, LOG_DIR = _get_base_and_log_dirs()
CONFIG_FILE = _resolve_existing_or_default(_CONFIG_FILENAME, LOG_DIR)

def find_resource(filename):
    """Return first existing path for bundled/static assets."""
    candidates = [
        os.path.join(BASE_DIR, filename),
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv else "", filename),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)) if hasattr(sys, "executable") else "", filename),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return os.path.join(BASE_DIR, filename)

LOGO_PATH = find_resource(os.path.join("assets", "garmin-uploader-logo.PNG"))
DEV_LOGO_PATH = find_resource(os.path.join("assets", "inc21.webp"))
GITHUB_LOGO_PATH = find_resource(os.path.join("assets", "github_logo.png"))
WAHOO_LOGO_PATH = find_resource(os.path.join("assets", "wahoo.png"))
MYWHOOSH_LOGO_PATH = find_resource(os.path.join("assets", "mywhoosh.png"))
TRAINERDAY_LOGO_PATH = find_resource(os.path.join("assets", "trainerday.png"))
VERSION = "1.1.0"
GITHUB_REPO_URL = "https://github.com/Inc21/Garmin-Connect-Auto-Uploader"
VERSION_JSON_URL = "https://raw.githubusercontent.com/Inc21/Garmin-Connect-Auto-Uploader/main/version.json"
LEGACY_VERSION_JSON_URL = "https://raw.githubusercontent.com/Inc21/Wahoo-and-MyWhoos-to-Garmin-Conect-Auto-Uploader/main/version.json"
LOG_FILE = _resolve_existing_or_default("garmin_uploader.log", LOG_DIR)
# Upload log (single file; month separators written when month changes)
UPLOAD_LOG_FILE = _resolve_existing_or_default("garmin_uploads.log", LOG_DIR)
MAX_LOG_SIZE_MB = 10  # Rotate log after 10MB

# Setup logging with rotation (standard format without icons by default)
from logging.handlers import RotatingFileHandler

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=MAX_LOG_SIZE_MB * 1024 * 1024,  # 10MB
    backupCount=3,  # Keep 3 backup files (~ 3 months of logs)
    encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

# Dedicated upload-only logger (separate file, no rotation; date markers in file)
upload_logger = logging.getLogger("upload_log")
upload_handler = logging.FileHandler(UPLOAD_LOG_FILE, encoding='utf-8')
upload_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
upload_logger.setLevel(logging.INFO)
# Avoid duplicate propagation to root; we want a clean uploads-only file
upload_logger.propagate = False
upload_logger.handlers = [upload_handler]

# Custom log functions with icons for specific events
def log_success(message):
    """Log a success message with green checkmark"""
    logger.info(f"✅ {message}")

def log_error(message):
    """Log an error message with red X"""
    logger.error(f"❌ {message}")

def log_warning(message):
    """Log a warning message with warning sign"""
    logger.warning(f"⚠️ {message}")

def log_info(message):
    """Log an info message (no icon)"""
    logger.info(message)

def log_separator():
    """Add a blank line separator in logs for better grouping"""
    # Write directly to handlers to create a true blank line
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.stream.write("\n")
            handler.flush()

KEYRING_SERVICE = "GarminConnectUploader"


def store_password(email, password):
    """Store password securely using Windows Credential Manager via keyring"""
    if not password or not email:
        return
    if keyring:
        try:
            keyring.set_password(KEYRING_SERVICE, email, password)
            return
        except Exception:
            pass
    logger.warning("keyring not available; password only in config file fallback")


def _encode_fallback(password):
    """Simple base64 encoding for config-file fallback (not a security measure)"""
    if not password:
        return ""
    return "b64:" + base64.b64encode(password.encode('utf-8')).decode('utf-8')


def _decode_fallback(encoded):
    """Decode base64 config-file fallback password"""
    if not encoded:
        return ""
    if encoded.startswith("b64:"):
        try:
            return base64.b64decode(encoded[4:].encode('utf-8')).decode('utf-8')
        except Exception:
            return ""
    # Try legacy XOR+Base64 format
    return _legacy_decrypt_password(encoded)


def retrieve_password(email):
    """Retrieve password from Windows Credential Manager via keyring"""
    if not email:
        return ""
    if keyring:
        try:
            pw = keyring.get_password(KEYRING_SERVICE, email)
            if pw:
                return pw
        except Exception:
            pass
    return ""


def delete_password(email):
    """Remove stored password from keyring"""
    if not email:
        return
    if keyring:
        try:
            keyring.delete_password(KEYRING_SERVICE, email)
        except Exception:
            pass


def _legacy_decrypt_password(encrypted_password):
    """Decrypt password from old XOR+Base64 format for migration only"""
    if not encrypted_password:
        return ""
    try:
        key = "GarminUploaderV1SecretKey2024"
        decoded = base64.b64decode(
            encrypted_password.encode('utf-8')
        ).decode('latin-1')
        decrypted = ''.join(
            chr(ord(c) ^ ord(key[i % len(key)]))
            for i, c in enumerate(decoded)
        )
        return decrypted
    except Exception:  # noqa: E722
        return ""


class ConnectUploaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Garmin Connect Uploader v{VERSION}")
        # Get DPI scaling factor
        scaling = self.root.tk.call('tk', 'scaling')
        self.scaling = scaling  # Store for use in dialog windows
        
        # Base dimensions at 96 DPI (1.0 scaling)
        base_width = 600
        base_min_height = 650  # Minimum for small screens
        base_max_height = 900  # Maximum initial height
        
        # Adjust for actual DPI scaling
        width = int(base_width * (scaling / 1.33))
        min_height = int(base_min_height * (scaling / 1.33))
        max_height = int(base_max_height * (scaling / 1.33))
        
        # Start with minimum height, will auto-size after UI is built
        self.root.geometry(f"{width}x{min_height}")
        self.root.minsize(width, min_height)
        self.root.resizable(True, True)
        
        # Store base and max dimensions for later use
        self._base_width = width
        self._min_height = min_height
        self._max_height = max_height
        
        # Set modern styling
        style = ttk.Style()
        style.theme_use('clam')  # More modern theme
        
        # Configure colors
        style.configure('TLabel', background='#f0f0f0')
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TButton', padding=6)
        style.configure('Header.TLabel', font=('Arial', 11, 'bold'), background='#f0f0f0')
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'), background='#f0f0f0', foreground='#2c3e50')
        
        # Set window background
        self.root.configure(bg='#f0f0f0')
        
        # Set window icon
        try:
            if os.path.exists(LOGO_PATH):
                logo_img = Image.open(LOGO_PATH)
                logo_photo = ImageTk.PhotoImage(logo_img)
                self.root.iconphoto(True, logo_photo)
                self.logo_image = logo_photo  # Keep reference
        except Exception as e:
            print(f"Could not load logo: {e}")
        
        # Load saved configuration
        self.config = self.load_config()
        
        # Monitoring state
        self.is_monitoring = False
        self.monitor_thread = None
        self.garmin_client = None
        self.tray_icon = None
        self.check_interval = 300  # Default 5 minutes
        self.settings_changed = False  # Track if settings have been modified
        self._upload_log_day = None  # Track day marker for uploads log
        
        self.create_widgets()
        self.load_settings()
        self.load_last_sync_from_log()  # Restore last sync/upload info
        self.check_old_version_shortcut()  # Check and update old version shortcuts
        
        # Handle window close (minimize to tray if monitoring)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
            
        # Initialize garmin session directory
        self.session_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "GarminUploader", "session")
        os.makedirs(self.session_dir, exist_ok=True)
            
        # Initialize login state (will be set by try_session_login if successful)
        self.garmin_client = None
        self.is_logged_in = False
        
        # Try to login quietly with saved session on startup
        self.try_session_login()
        
    def prompt_mfa_code(self):
        """Prompt user for MFA code using a tkinter dialog"""
        mfa_code = tk.StringVar()
        dialog = tk.Toplevel(self.root)
        dialog.title("Two-Factor Authentication")
        dialog.geometry("400x180")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        frame = ttk.Frame(dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="🔐 Two-Factor Authentication Required", font=('Segoe UI', 11, 'bold')).pack(pady=(0, 10))
        ttk.Label(frame, text="Enter the verification code from your authenticator app:", wraplength=350).pack(pady=(0, 10))
        
        entry = ttk.Entry(frame, textvariable=mfa_code, font=('Segoe UI', 11), width=20, justify='center')
        entry.pack(pady=(0, 15))
        entry.focus_set()
        
        def on_submit():
            dialog.destroy()
        
        entry.bind('<Return>', lambda e: on_submit())
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack()
        ttk.Button(btn_frame, text="Submit", command=on_submit).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=lambda: [mfa_code.set(''), dialog.destroy()]).pack(side=tk.LEFT, padx=5)
        
        dialog.wait_window()
        return mfa_code.get().strip()
    
    def try_session_login(self):
        """Try to login using saved session tokens (garminconnect 0.3.1 API)"""
        try:
            email = self.garmin_email.get() if self.garmin_email else self.config.get('garmin_email', '')
            password = self.garmin_password.get() if self.garmin_password else self.config.get('garmin_password', '')
                
            if not email or not password:
                return False
                
            # Create session directory specific to this user
            user_session_dir = os.path.join(self.session_dir, email.replace('@', '_').replace('.', '_'))
            
            # Try to resume session using saved tokens
            if os.path.exists(user_session_dir):
                try:
                    # Create Garmin client and try to login with saved tokens
                    self.garmin_client = Garmin()
                    self.garmin_client.login(user_session_dir)
                    logger.info("Successfully resumed session using saved tokens (no login required)")
                    self.update_status("Logged in using saved session", "green")
                    self.update_login_status(True)
                    return True
                except Exception as e:
                    # Session failed, fall back to credentials
                    self.garmin_client = None
                    logger.warning(f"Session login failed, will use credentials: {str(e)}")
                    pass
        except Exception as e:
            self.garmin_client = None
            logger.warning(f"Session login failed: {str(e)}")
            pass
            
        return False
        
    def create_widgets(self):
        # Create canvas with scrollbar for content
        canvas = tk.Canvas(self.root, bg='#f0f0f0', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        
        # Main container inside canvas
        main_frame = ttk.Frame(canvas, padding="20")
        self._canvas = canvas
        self._main_frame = main_frame
        
        # Configure grid weights for responsive layout
        main_frame.columnconfigure(1, weight=1)  # Column 1 (entry fields) expands
        main_frame.columnconfigure(2, weight=1)  # Column 2 also expands
        
        # Configure canvas
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack scrollbar and canvas
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Create window in canvas
        canvas_frame = canvas.create_window((0, 0), window=main_frame, anchor="nw")
        
        # Create a single global scroll handler
        def on_mousewheel(event):
            # event.delta works for Windows; use factor of 120 for smooth scrolling
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        
        # Bind the wheel only when the mouse enters the canvas area
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))
        
        # Add Linux support (optional but good practice)
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units")), add="+")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units")), add="+")
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<Button-4>"), add="+")
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<Button-5>"), add="+")
        
        # Update scroll region and make frame fill canvas width
        def on_frame_configure(event):
            # Only enable scrolling when content exceeds canvas size
            canvas.update_idletasks()  # Ensure sizes are calculated
            frame_height = main_frame.winfo_reqheight()
            canvas_height = canvas.winfo_height()
            
            if frame_height > canvas_height:
                # Content exceeds canvas, enable scrolling
                canvas.configure(scrollregion=canvas.bbox("all"))
            else:
                # Content fits, disable scrolling
                canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), canvas_height))
        
        # Bind mousewheel to canvas
        def on_mousewheel(event):
            # Scroll the canvas regardless of content size
            # Use the event.delta to determine scroll direction
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"  # Prevent propagation
        
        def on_canvas_configure(event):
            # Make the frame fill the canvas width
            canvas.itemconfig(canvas_frame, width=event.width)
            # Update scroll region when canvas is resized
            canvas.update_idletasks()  # Ensure sizes are calculated
            frame_height = main_frame.winfo_reqheight()
            canvas_height = canvas.winfo_height()
            
            if frame_height > canvas_height:
                # Content exceeds canvas, enable scrolling
                canvas.configure(scrollregion=canvas.bbox("all"))
            else:
                # Content fits, disable scrolling
                canvas.configure(scrollregion=(0, 0, event.width, canvas_height))
        
        main_frame.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        
        # Title with logo
        title_frame = ttk.Frame(main_frame)
        title_frame.grid(row=0, column=0, columnspan=3, pady=(0, 25))
        
        # Load and display logo
        try:
            logo_img = Image.open(LOGO_PATH)
            logo_img.thumbnail((45, 45))  # Resize to 45x45
            self.title_logo = ImageTk.PhotoImage(logo_img)
            logo_label = ttk.Label(title_frame, image=self.title_logo)
            logo_label.pack(side=tk.LEFT, padx=(0, 10))
        except Exception:
            pass  # If logo fails to load, just skip it
        
        # Title text
        ttk.Label(title_frame, text="Garmin Connect Uploader", style='Title.TLabel').pack(side=tk.LEFT)
        
        # Garmin Settings
        ttk.Label(main_frame, text="🔑 Garmin Connect Settings", style='Header.TLabel').grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(10, 5))
        
        # Quick link to Garmin Connect
        garmin_link = ttk.Label(
            main_frame,
            text="Open Garmin Connect in Browser",
            foreground='blue',
            cursor='hand2',
            font=('Arial', 9, 'underline')
        )
        garmin_link.grid(row=1, column=2, sticky=tk.E, pady=(10, 5))
        garmin_link.bind(
            "<Button-1>",
            lambda e: webbrowser.open("https://connect.garmin.com")
        )
        
        ttk.Label(main_frame, text="Email:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.garmin_email = ttk.Entry(main_frame, width=35)
        self.garmin_email.grid(row=2, column=1, sticky=tk.W, pady=5, padx=5)
        self.garmin_email.bind('<KeyRelease>', lambda e: self.on_credentials_changed())
        
        ttk.Label(main_frame, text="Password:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.garmin_password = ttk.Entry(main_frame, show="*", width=35)
        self.garmin_password.grid(row=3, column=1, sticky=tk.W, pady=5, padx=5)
        self.garmin_password.bind('<KeyRelease>', lambda e: self.on_credentials_changed())
        
        # Test Connection button and login status indicator
        test_btn = ttk.Button(main_frame, text="Test & Login", command=self.test_garmin_connection)
        test_btn.grid(row=3, column=2, sticky=tk.W, pady=5, padx=5)
        
        # Login status indicator (initially hidden)
        self.login_status_label = ttk.Label(main_frame, text="", foreground="green", font=('Segoe UI', 9))
        self.login_status_label.grid(row=2, column=2, sticky=tk.W, pady=5, padx=5)
        
        # Folder Settings
        ttk.Label(main_frame, text="📁 Folder Settings", style='Header.TLabel').grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(20, 5))

        # Per-app expanded state for collapsible sections (default collapsed)
        self.wahoo_expanded = tk.BooleanVar(value=False)
        self.mywhoosh_expanded = tk.BooleanVar(value=False)
        self.trainerday_expanded = tk.BooleanVar(value=False)

        # Wahoo section (checkbox header + collapsible body)
        self.wahoo_section = ttk.Frame(main_frame)
        self.wahoo_section.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E))

        wahoo_header = ttk.Frame(self.wahoo_section)
        wahoo_header.pack(fill='x', pady=(2, 0))
        wahoo_header.bind("<Button-1>", lambda e: self._on_header_click("wahoo", e))
        self.wahoo_toggle = ttk.Label(wahoo_header, text="▶", width=2)
        self.wahoo_toggle.pack(side='left')
        self.wahoo_toggle.bind("<Button-1>", lambda e: self._on_header_click("wahoo", e))

        try:
            wahoo_img = Image.open(WAHOO_LOGO_PATH)
            wahoo_img.thumbnail((28, 28))
            self.wahoo_logo_image = ImageTk.PhotoImage(wahoo_img)
            wahoo_logo_label = ttk.Label(wahoo_header, image=self.wahoo_logo_image)
            wahoo_logo_label.pack(side='left', padx=(2, 4))
            wahoo_logo_label.bind("<Button-1>", lambda e: self._on_header_click("wahoo", e))
        except Exception:
            self.wahoo_logo_image = None

        # App name label (no checkbox; status-only header)
        wahoo_name_label = ttk.Label(wahoo_header, text="Wahoo (Dropbox)")
        wahoo_name_label.pack(side='left')
        wahoo_name_label.bind("<Button-1>", lambda e: self._on_header_click("wahoo", e))

        # Status label on the right (e.g. Not configured / Folder missing / ✅ Ready)
        self.wahoo_status_label = ttk.Label(wahoo_header, text="", foreground='gray')
        self.wahoo_status_label.pack(side='right')
        self.wahoo_status_label.bind("<Button-1>", lambda e: self._on_header_click("wahoo", e))

        self.wahoo_body = ttk.Frame(self.wahoo_section)
        self.wahoo_body.pack(fill='x', padx=(24, 0), pady=(0, 4))
        self.wahoo_body.columnconfigure(0, weight=1)

        self.wahoo_folder = ttk.Entry(self.wahoo_body)
        self.wahoo_folder.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=(0, 2))
        self.wahoo_folder.bind('<KeyRelease>', lambda e: (self.mark_settings_changed(), self._update_app_status_icons()))
        ttk.Button(self.wahoo_body, text="Browse", command=lambda: self.browse_folder(self.wahoo_folder)).grid(row=0, column=1, padx=(0, 3), pady=(0, 2))
        help_btn = ttk.Button(self.wahoo_body, text="?", command=self.show_wahoo_help, width=2)
        help_btn.grid(row=0, column=2, pady=(0, 2))

        ttk.Label(
            self.wahoo_body,
            text="Example: C\\Users\\YourName\\Dropbox\\Apps\\WahooFitness",
            font=('Arial', 8),
            foreground='gray',
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W)

        # MyWhoosh section
        self.mywhoosh_section = ttk.Frame(main_frame)
        self.mywhoosh_section.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E))

        mywhoosh_header = ttk.Frame(self.mywhoosh_section)
        mywhoosh_header.pack(fill='x', pady=(8, 0))
        mywhoosh_header.bind("<Button-1>", lambda e: self._on_header_click("mywhoosh", e))
        self.mywhoosh_toggle = ttk.Label(mywhoosh_header, text="▶", width=2)
        self.mywhoosh_toggle.pack(side='left')
        self.mywhoosh_toggle.bind("<Button-1>", lambda e: self._on_header_click("mywhoosh", e))

        try:
            mywhoosh_img = Image.open(MYWHOOSH_LOGO_PATH)
            mywhoosh_img.thumbnail((28, 28))
            self.mywhoosh_logo_image = ImageTk.PhotoImage(mywhoosh_img)
            mywhoosh_logo_label = ttk.Label(mywhoosh_header, image=self.mywhoosh_logo_image)
            mywhoosh_logo_label.pack(side='left', padx=(2, 4))
            mywhoosh_logo_label.bind("<Button-1>", lambda e: self._on_header_click("mywhoosh", e))
        except Exception:
            self.mywhoosh_logo_image = None

        mywhoosh_name_label = ttk.Label(mywhoosh_header, text="MyWhoosh")
        mywhoosh_name_label.pack(side='left')
        mywhoosh_name_label.bind("<Button-1>", lambda e: self._on_header_click("mywhoosh", e))

        self.mywhoosh_status_label = ttk.Label(mywhoosh_header, text="", foreground='gray')
        self.mywhoosh_status_label.pack(side='right')
        self.mywhoosh_status_label.bind("<Button-1>", lambda e: self._on_header_click("mywhoosh", e))

        self.mywhoosh_body = ttk.Frame(self.mywhoosh_section)
        self.mywhoosh_body.pack(fill='x', padx=(24, 0), pady=(0, 4))
        self.mywhoosh_body.columnconfigure(0, weight=1)

        self.mywhoosh_folder = ttk.Entry(self.mywhoosh_body)
        self.mywhoosh_folder.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=(0, 2))
        self.mywhoosh_folder.bind('<KeyRelease>', lambda e: (self.mark_settings_changed(), self._update_app_status_icons()))
        ttk.Button(self.mywhoosh_body, text="Browse", command=lambda: self.browse_folder(self.mywhoosh_folder)).grid(row=0, column=1, padx=(0, 3), pady=(0, 2))
        help_btn2 = ttk.Button(self.mywhoosh_body, text="?", command=self.show_mywhoosh_help, width=2)
        help_btn2.grid(row=0, column=2, pady=(0, 2))

        ttk.Label(
            self.mywhoosh_body,
            text="Example: C\\Users\\YourName\\AppData\\Local\\...\\MyWhoosh\\Content\\Data",
            font=('Arial', 8),
            foreground='gray',
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W)

        # MyWhoosh warning and link inside the body
        warning_frame = ttk.Frame(self.mywhoosh_body)
        warning_frame.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))

        icon_label = ttk.Label(warning_frame, text="⚠️", font=('Arial', 20), foreground='#ff6600')
        icon_label.grid(row=0, column=0, rowspan=2, sticky='n', padx=(0, 10))

        ttk.Label(
            warning_frame,
            text="MyWhoosh only keeps the latest activity in the cache folder.",
            font=('Arial', 9),
            foreground='#ff6600',
        ).grid(row=0, column=1, sticky='w')

        ttk.Label(
            warning_frame,
            text="Multiple rides while app is closed = only the last one syncs!",
            font=('Arial', 9),
            foreground='#ff6600',
        ).grid(row=1, column=1, sticky='w')

        link_frame = ttk.Frame(self.mywhoosh_body)
        link_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))
        readme_link = ttk.Label(
            link_frame,
            text="Read more on GitHub",
            foreground='blue',
            cursor='hand2',
            font=('Arial', 9, 'underline'),
        )
        readme_link.pack(anchor='center')
        readme_link.bind(
            "<Button-1>",
            lambda e: webbrowser.open(
                "https://github.com/Inc21/Wahoo-and-MyWhoosh-to-Garmin-Conect-Auto-Uploader#%EF%B8%8F-important-sync-behavior"
            ),
        )

        # TrainerDay section (similar structure to Wahoo)
        self.trainerday_section = ttk.Frame(main_frame)
        self.trainerday_section.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E))

        trainerday_header = ttk.Frame(self.trainerday_section)
        trainerday_header.pack(fill='x', pady=(8, 0))
        trainerday_header.bind("<Button-1>", lambda e: self._on_header_click("trainerday", e))
        self.trainerday_toggle = ttk.Label(trainerday_header, text="▶", width=2)
        self.trainerday_toggle.pack(side='left')
        self.trainerday_toggle.bind("<Button-1>", lambda e: self._on_header_click("trainerday", e))

        try:
            trainerday_img = Image.open(TRAINERDAY_LOGO_PATH)
            trainerday_img.thumbnail((28, 28))
            self.trainerday_logo_image = ImageTk.PhotoImage(trainerday_img)
            trainerday_logo_label = ttk.Label(trainerday_header, image=self.trainerday_logo_image)
            trainerday_logo_label.pack(side='left', padx=(2, 4))
            trainerday_logo_label.bind("<Button-1>", lambda e: self._on_header_click("trainerday", e))
        except Exception:
            self.trainerday_logo_image = None

        trainerday_name_label = ttk.Label(trainerday_header, text="TrainerDay (Dropbox)")
        trainerday_name_label.pack(side='left')
        trainerday_name_label.bind("<Button-1>", lambda e: self._on_header_click("trainerday", e))

        self.trainerday_status_label = ttk.Label(trainerday_header, text="", foreground='gray')
        self.trainerday_status_label.pack(side='right')
        self.trainerday_status_label.bind("<Button-1>", lambda e: self._on_header_click("trainerday", e))

        self.trainerday_body = ttk.Frame(self.trainerday_section)
        self.trainerday_body.pack(fill='x', padx=(24, 0), pady=(0, 4))
        self.trainerday_body.columnconfigure(0, weight=1)

        self.trainerday_folder = ttk.Entry(self.trainerday_body)
        self.trainerday_folder.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=(0, 2))
        self.trainerday_folder.bind('<KeyRelease>', lambda e: (self.mark_settings_changed(), self._update_app_status_icons()))
        ttk.Button(self.trainerday_body, text="Browse", command=lambda: self.browse_folder(self.trainerday_folder)).grid(row=0, column=1, padx=(0, 3), pady=(0, 2))
        help_btn3 = ttk.Button(self.trainerday_body, text="?", command=self.show_trainerday_help, width=2)
        help_btn3.grid(row=0, column=2, pady=(0, 2))

        ttk.Label(
            self.trainerday_body,
            text="Example: C\\Users\\YourName\\Dropbox\\Apps\\TrainerDay",
            font=('Arial', 8),
            foreground='gray',
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W)

        # Experimental spoof setting
        self.experimental_edge_spoof = tk.BooleanVar(value=False)
        experimental_frame = ttk.Frame(main_frame)
        experimental_frame.grid(row=12, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(8, 2))

        ttk.Checkbutton(
            experimental_frame,
            text="Experimental Garmin mode",
            variable=self.experimental_edge_spoof,
            command=self.mark_settings_changed,
        ).pack(side='left', anchor='w')

        ttk.Button(
            experimental_frame,
            text="i",
            width=2,
            command=self.show_experimental_spoof_info,
        ).pack(side='left', padx=(6, 0))
        
        # Separator
        ttk.Separator(main_frame, orient='horizontal').grid(row=13, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=15)
        
        # Auto-Start Settings
        ttk.Label(main_frame, text="⏰ Auto-Start Settings", style='Header.TLabel').grid(row=14, column=0, columnspan=3, sticky=tk.W, pady=(5, 5))
        
        # Helpful note
        note_text = "💡 Tip: Enable both 'Start with Windows' AND 'Start Auto-Sync' for automatic background uploads"
        ttk.Label(main_frame, text=note_text, font=('Arial', 8, 'italic'), foreground='#0066cc', wraplength=600).grid(row=15, column=0, columnspan=3, sticky=tk.W, pady=(0, 5))
        
        # Start with Windows checkbox
        self.start_with_windows = tk.BooleanVar()
        ttk.Checkbutton(main_frame, text="Start with Windows (run in background at startup)", variable=self.start_with_windows, command=self.toggle_autostart).grid(row=16, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Check interval
        interval_frame = ttk.Frame(main_frame)
        interval_frame.grid(row=17, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        ttk.Label(interval_frame, text="Check for new activities every:").pack(side=tk.LEFT, padx=(0, 5))
        self.interval_var = tk.IntVar(value=5)
        interval_spinbox = ttk.Spinbox(interval_frame, from_=1, to=30, textvariable=self.interval_var, width=5, command=self.mark_settings_changed)
        interval_spinbox.pack(side=tk.LEFT)
        ttk.Label(interval_frame, text="minutes").pack(side=tk.LEFT, padx=(5, 0))
        
        # Separator
        ttk.Separator(main_frame, orient='horizontal').grid(row=18, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        # Primary action buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=19, column=0, columnspan=3, pady=(4, 2))
        
        ttk.Button(btn_frame, text="Save Settings", command=self.save_settings).pack(side='left', padx=3)
        self.sync_button = ttk.Button(btn_frame, text="Sync Now", command=self.sync_now)
        self.sync_button.pack(side='left', padx=3)
        self.monitor_button = ttk.Button(btn_frame, text="Start Auto-Sync", command=self.toggle_monitoring)
        self.monitor_button.pack(side='left', padx=3)
        self.minimize_button = ttk.Button(btn_frame, text="Minimize to Tray", command=self.minimize_to_tray)
        self.minimize_button.pack(side='left', padx=3)

        # Secondary action row
        about_frame = ttk.Frame(main_frame)
        about_frame.grid(row=20, column=0, columnspan=3, pady=(0, 6))
        ttk.Button(about_frame, text="About & update", command=self.show_about).pack()
        
        # Status
        self.status_label = ttk.Label(main_frame, text="Status: Idle", foreground='blue', font=('Arial', 9))
        self.status_label.grid(row=21, column=0, columnspan=3, pady=(6, 0))
        
        # Last sync time
        self.last_sync_label = ttk.Label(main_frame, text="Last sync: Never", foreground='gray', font=('Arial', 8))
        self.last_sync_label.grid(row=22, column=0, columnspan=3)
        
        # Last upload info
        self.last_upload_label = ttk.Label(main_frame, text="Last upload: None", foreground='gray', font=('Arial', 8))
        self.last_upload_label.grid(row=23, column=0, columnspan=3)
        
        # View full log link
        log_link = ttk.Label(
            main_frame,
            text="View Full Log",
            foreground='blue',
            cursor='hand2',
            font=('Arial', 8, 'underline')
        )
        log_link.grid(row=24, column=0, columnspan=3, pady=(5, 10))
        log_link.bind("<Button-1>", lambda e: self.open_log_file())
        
        # Auto-size window to content after UI is built
        self._auto_size_to_content()
        
    def update_app_sections(self):
        """Show/hide app folder sections based on expanded state only.

        Default is headers only (collapsed). When an app is expanded, its body is
        shown and the arrow icon points down; otherwise the body is hidden and
        the arrow points right.
        """
        # Wahoo
        if getattr(self, 'wahoo_expanded', None):
            if self.wahoo_expanded.get():
                self.wahoo_body.pack(fill='x', padx=(24, 0), pady=(0, 4))
                self.wahoo_toggle.config(text="▼")
            else:
                self.wahoo_body.pack_forget()
                self.wahoo_toggle.config(text="▶")

        # MyWhoosh
        if getattr(self, 'mywhoosh_expanded', None):
            if self.mywhoosh_expanded.get():
                self.mywhoosh_body.pack(fill='x', padx=(24, 0), pady=(0, 4))
                self.mywhoosh_toggle.config(text="▼")
            else:
                self.mywhoosh_body.pack_forget()
                self.mywhoosh_toggle.config(text="▶")

        # TrainerDay
        if getattr(self, 'trainerday_expanded', None):
            if self.trainerday_expanded.get():
                self.trainerday_body.pack(fill='x', padx=(24, 0), pady=(0, 4))
                self.trainerday_toggle.config(text="▼")
            else:
                self.trainerday_body.pack_forget()
                self.trainerday_toggle.config(text="▶")

        self._update_app_status_icons()
        # Adjust window height when sections are expanded/collapsed
        self._auto_size_to_content()

    def _auto_size_to_content(self):
        """Auto-size the main window height to fit current content.

        Uses the requested height of the main frame, capped at _max_height,
        and preserves scroll position. This keeps the window from leaving
        a large empty area when sections are collapsed.
        """
        try:
            if not hasattr(self, "_main_frame") or not hasattr(self, "_canvas"):
                return

            canvas = self._canvas
            main_frame = self._main_frame

            # Force layout calculation
            self.root.update_idletasks()

            required_height = main_frame.winfo_reqheight() + 40  # Add padding
            actual_height = min(required_height, self._max_height)

            # Get current geometry width/height
            current_width = self.root.winfo_width()

            # Capture scroll position before resize
            try:
                current_pos = canvas.yview()
            except Exception:
                current_pos = None

            # Apply new geometry and allow window to shrink to this height,
            # while keeping the base minimum width
            self.root.geometry(f"{current_width}x{actual_height}")
            self.root.minsize(getattr(self, "_base_width", current_width), actual_height)

            # Restore scroll position
            try:
                if current_pos:
                    if current_pos[0] == 0.0:
                        canvas.yview_moveto(0)
                    else:
                        canvas.yview_moveto(current_pos[0])
            except Exception:
                pass
        except Exception:
            # Never let sizing errors break the UI
            pass

    def toggle_app_section(self, app_name):
        """Toggle expanded/collapsed state for a given app section.

        Clicking the arrow/header will expand/collapse. There is no separate
        enable/disable state for apps; readiness is derived from the folder
        configuration. This method only controls visibility of the details.
        """
        if app_name == "wahoo":
            self.wahoo_expanded.set(not self.wahoo_expanded.get())
        elif app_name == "mywhoosh":
            self.mywhoosh_expanded.set(not self.mywhoosh_expanded.get())
        elif app_name == "trainerday":
            self.trainerday_expanded.set(not self.trainerday_expanded.get())

        self.update_app_sections()
        self.mark_settings_changed()

    def _on_header_click(self, app_name, event=None):
        """Handle clicks on app header areas (arrow, logo, status, background).

        This toggles expand/collapse for that app's section.
        """
        self.toggle_app_section(app_name)

    def _update_app_status_icons(self):
        """Update header status text/icons based on folder configuration.

        States per app:
        - No folder text          -> "Not configured" (gray)
        - Text but folder missing -> "Folder missing" (orange)
        - Existing directory      -> "✅ Ready" (green)
        """
        try:
            # Wahoo
            wahoo = self.wahoo_folder.get().strip()
            if not wahoo:
                self.wahoo_status_label.config(text="Not configured", foreground='gray')
            elif not os.path.isdir(wahoo):
                self.wahoo_status_label.config(text="Folder missing", foreground='orange')
            else:
                self.wahoo_status_label.config(text="✅ Ready", foreground='green')

            # MyWhoosh
            mywhoosh = self.mywhoosh_folder.get().strip()
            if not mywhoosh:
                self.mywhoosh_status_label.config(text="Not configured", foreground='gray')
            elif not os.path.isdir(mywhoosh):
                self.mywhoosh_status_label.config(text="Folder missing", foreground='orange')
            else:
                self.mywhoosh_status_label.config(text="✅ Ready", foreground='green')

            # TrainerDay
            trainerday = self.trainerday_folder.get().strip() if hasattr(self, 'trainerday_folder') else ""
            if not trainerday:
                self.trainerday_status_label.config(text="Not configured", foreground='gray')
            elif not os.path.isdir(trainerday):
                self.trainerday_status_label.config(text="Folder missing", foreground='orange')
            else:
                self.trainerday_status_label.config(text="✅ Ready", foreground='green')
        except Exception:
            # UI-only helper; never raise
            pass

    def show_wahoo_help(self):
        # Create a new window with selectable text
        help_window = tk.Toplevel(self.root)
        help_window.title("Wahoo Setup Instructions")
        
        # Apply DPI scaling
        base_width, base_height = 550, 500
        width = int(base_width * (self.scaling / 1.33))
        height = int(base_height * (self.scaling / 1.33))
        help_window.geometry(f"{width}x{height}")
        help_window.resizable(False, False)
        
        # Title
        title_label = ttk.Label(help_window, text="How to Setup Wahoo with Dropbox", font=('Arial', 12, 'bold'))
        title_label.pack(pady=10)
        
        # Dropbox install link button
        dropbox_btn = ttk.Button(
            help_window,
            text="📥 Download Dropbox Desktop App",
            command=lambda: webbrowser.open("https://www.dropbox.com/install")
        )
        dropbox_btn.pack(pady=(0, 10))
        
        # Scrollable text area
        text_area = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, width=65, height=20, font=('Arial', 9))
        text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        help_text = """1. Create a Dropbox account (free):
   → Go to dropbox.com and sign up

2. Connect Wahoo to Dropbox:
   → Open Wahoo ELEMNT app on your phone
   → Go to Settings → Cloud Services
   → Enable Dropbox and authorize

3. Install Dropbox on your PC:
   → Download from dropbox.com/install
   → Sign in with your account
   → Let it sync

4. Find the Wahoo folder:
   → Open File Explorer
   → Navigate to:
   
   C:\\Users\\YourName\\Dropbox\\Apps\\WahooFitness
   
   → Copy this path and paste it in the Wahoo Folder field

Note: The app will automatically create an 'uploaded' subfolder to move processed .fit files there.

You can select and copy text from this window!"""
        
        text_area.insert(1.0, help_text)
        text_area.config(state='normal')  # Keep it editable so users can select/copy
        
        # Close button
        close_btn = ttk.Button(help_window, text="Close", command=help_window.destroy)
        close_btn.pack(pady=10)
    
    def show_trainerday_help(self):
        """Show instructions for configuring the TrainerDay Dropbox folder."""
        help_window = tk.Toplevel(self.root)
        help_window.title("TrainerDay Dropbox Folder Instructions")

        # Apply DPI scaling
        base_width, base_height = 550, 420
        width = int(base_width * (self.scaling / 1.33))
        height = int(base_height * (self.scaling / 1.33))
        help_window.geometry(f"{width}x{height}")
        help_window.resizable(False, False)

        # Title
        title_label = ttk.Label(help_window, text="How to Setup TrainerDay with Dropbox", font=('Arial', 12, 'bold'))
        title_label.pack(pady=10)

        # Scrollable text area
        text_area = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, width=65, height=16, font=('Arial', 9))
        text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        help_text = """TrainerDay can export your workouts to a Dropbox folder.

1. In your browser, open https://app.trainerday.com and log in.

2. Click your user icon in the top-right corner and choose "Connections".

3. In the "Connection to Dropbox" section, click "Connect" (or "Sync activities") to link TrainerDay to Dropbox.

4. After the first sync, Dropbox will contain a TrainerDay folder, for example:

   C:\\Users\\YourName\\Dropbox\\TrainerDay
   or
   C:\\Users\\YourName\\Dropbox\\Apps\\TrainerDay

5. On this PC, open File Explorer and navigate to that TrainerDay folder.

6. Copy the full path and paste it into the TrainerDay Folder field in this app.

Note: This app will automatically create an 'uploaded' subfolder inside the TrainerDay folder to move processed .fit files after they are uploaded."""

        text_area.insert(1.0, help_text)
        text_area.config(state='normal')  # Keep it editable so users can select/copy

        # Close button
        close_btn = ttk.Button(help_window, text="Close", command=help_window.destroy)
        close_btn.pack(pady=10)

    def show_mywhoosh_help(self):
        # Create a new window with selectable text
        help_window = tk.Toplevel(self.root)
        help_window.title("MyWhoosh Folder Instructions")
        
        # Apply DPI scaling
        base_width, base_height = 600, 500
        width = int(base_width * (self.scaling / 1.33))
        height = int(base_height * (self.scaling / 1.33))
        help_window.geometry(f"{width}x{height}")
        help_window.resizable(False, False)
        
        # Title
        title_label = ttk.Label(help_window, text="How to Find MyWhoosh Cache Folder", font=('Arial', 12, 'bold'))
        title_label.pack(pady=10)
        
        # Scrollable text area
        text_area = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, width=70, height=24, font=('Arial', 9))
        text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        help_text = """MyWhoosh only keeps the LAST activity in its cache folder.
This folder is hidden deep in Windows AppData.

How to find it:

1. Open File Explorer

2. In the address bar, paste this and press Enter:

   %localappdata%\\Packages

3. Look for a folder starting with:

   MyWhooshTechnologyService.644173E064ED2
   
   Full example:
   MyWhooshTechnologyService.644173E064ED2_eps1123pz0kt0

4. Open that folder, then navigate to:

   LocalCache\\Local\\MyWhoosh\\Content\\Data

5. Full path example (copy this format):

   C:\\Users\\YourName\\AppData\\Local\\Packages\\MyWhooshTechnologyService.644173E064ED2_eps1123pz0kt0\\LocalCache\\Local\\MyWhoosh\\Content\\Data

6. Copy YOUR path and paste it in the MyWhoosh Folder field

Note: MyWhoosh typically only keeps the most recent activity file (usually MyNewActivity-5.5.1.fit or similar) in this folder. The app will process ALL .fit files it finds there.

You can select and copy text from this window!"""
        
        text_area.insert(1.0, help_text)
        text_area.config(state='normal')  # Keep it editable so users can select/copy
        
        # Close button
        close_btn = ttk.Button(help_window, text="Close", command=help_window.destroy)
        close_btn.pack(pady=10)
    
    def browse_folder(self, entry_widget):
        folder = filedialog.askdirectory()
        if folder:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, folder)

    def show_experimental_spoof_info(self):
        info_text = (
            "Best-effort Garmin-compatible upload mode. "
            "Activities are saved as Edge 530 recordings and count toward challenges. "
            "Garmin training load and advanced metrics can take time to calculate and are not "
            "guaranteed to be calculated at all for your workout."
        )
        messagebox.showinfo("Experimental Garmin Mode", info_text)

    def _modify_tcx_for_garmin_device(self, input_path, output_path):
        """Best-effort TCX metadata rewrite so Garmin sees Garmin-like device fields."""
        try:
            tree = ET.parse(input_path)
            root = tree.getroot()
            if not root.tag.startswith("{"):
                return False

            tcx_ns = root.tag[1:].split("}")[0]
            xsi_ns = "http://www.w3.org/2001/XMLSchema-instance"
            ET.register_namespace('', tcx_ns)
            ET.register_namespace('xsi', xsi_ns)

            for activity in root.findall('.//{*}Activity'):
                creator = activity.find('{*}Creator')
                if creator is None:
                    creator = ET.SubElement(activity, f'{{{tcx_ns}}}Creator')

                creator.attrib[f'{{{xsi_ns}}}type'] = 'Device_t'
                creator.clear()
                creator.attrib[f'{{{xsi_ns}}}type'] = 'Device_t'

                ET.SubElement(creator, f'{{{tcx_ns}}}Name').text = 'Garmin Edge 530'
                ET.SubElement(creator, f'{{{tcx_ns}}}UnitId').text = '1234567890'
                ET.SubElement(creator, f'{{{tcx_ns}}}ProductID').text = '3121'
                version = ET.SubElement(creator, f'{{{tcx_ns}}}Version')
                ET.SubElement(version, f'{{{tcx_ns}}}VersionMajor').text = '17'
                ET.SubElement(version, f'{{{tcx_ns}}}VersionMinor').text = '0'
                ET.SubElement(version, f'{{{tcx_ns}}}BuildMajor').text = '0'
                ET.SubElement(version, f'{{{tcx_ns}}}BuildMinor').text = '0'

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            tree.write(output_path, encoding='utf-8', xml_declaration=True)
            return True
        except Exception as e:
            log_warning(f"Experimental TCX device rewrite failed for {os.path.basename(input_path)}: {e}")
            return False

    def _format_tcx_timestamp(self, value):
        if isinstance(value, datetime.datetime):
            if value.tzinfo is None:
                return value.strftime("%Y-%m-%dT%H:%M:%SZ")
            return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return str(value)

    def _semicircles_to_degrees(self, value):
        return float(value) * (180.0 / 2147483648.0)

    def _convert_fit_to_device_tcx(self, input_path, output_path):
        """Convert FIT to Garmin-like TCX and inject device metadata."""
        if fitdecode is None:
            log_warning("Experimental FIT spoof requires 'fitdecode' package, but it is not available.")
            return False

        try:
            records = []
            sport_name = "Biking"
            total_time = None
            total_distance = None
            total_calories = None

            with fitdecode.FitReader(input_path) as fit:
                for frame in fit:
                    if not isinstance(frame, fitdecode.FitDataMessage):
                        continue

                    values = {f.name: f.value for f in frame.fields if getattr(f, 'name', None)}

                    if frame.name == "session":
                        fit_sport = values.get("sport")
                        if fit_sport:
                            fit_sport_text = str(fit_sport).lower()
                            sport_name = "Biking" if "cycl" in fit_sport_text or "bike" in fit_sport_text else "Other"
                        total_time = values.get("total_elapsed_time") or total_time
                        total_distance = values.get("total_distance") or total_distance
                        total_calories = values.get("total_calories") or total_calories

                    elif frame.name == "record":
                        timestamp = values.get("timestamp")
                        if timestamp is None:
                            continue

                        record = {"time": timestamp}
                        if values.get("position_lat") is not None and values.get("position_long") is not None:
                            record["lat"] = self._semicircles_to_degrees(values.get("position_lat"))
                            record["lon"] = self._semicircles_to_degrees(values.get("position_long"))
                        if values.get("altitude") is not None:
                            record["altitude"] = float(values.get("altitude"))
                        if values.get("distance") is not None:
                            record["distance"] = float(values.get("distance"))
                        if values.get("heart_rate") is not None:
                            record["heart_rate"] = int(values.get("heart_rate"))
                        if values.get("cadence") is not None:
                            record["cadence"] = int(values.get("cadence"))
                        if values.get("speed") is not None:
                            record["speed"] = float(values.get("speed"))
                        if values.get("power") is not None:
                            record["power"] = int(values.get("power"))
                        records.append(record)

            if not records:
                return False

            tcx_ns = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
            xsi_ns = "http://www.w3.org/2001/XMLSchema-instance"
            ns3 = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
            ET.register_namespace('', tcx_ns)
            ET.register_namespace('xsi', xsi_ns)
            ET.register_namespace('ae', ns3)

            root = ET.Element(f"{{{tcx_ns}}}TrainingCenterDatabase")
            activities = ET.SubElement(root, f"{{{tcx_ns}}}Activities")
            activity = ET.SubElement(activities, f"{{{tcx_ns}}}Activity", Sport=sport_name)

            start_time = records[0]["time"]
            end_time = records[-1]["time"]
            ET.SubElement(activity, f"{{{tcx_ns}}}Id").text = self._format_tcx_timestamp(start_time)

            lap = ET.SubElement(activity, f"{{{tcx_ns}}}Lap", StartTime=self._format_tcx_timestamp(start_time))

            if total_time is None and isinstance(start_time, datetime.datetime) and isinstance(end_time, datetime.datetime):
                total_time = max(0.0, (end_time - start_time).total_seconds())
            if total_distance is None:
                total_distance = records[-1].get("distance", 0.0)
            if total_calories is None:
                total_calories = 0

            ET.SubElement(lap, f"{{{tcx_ns}}}TotalTimeSeconds").text = f"{float(total_time or 0.0):.1f}"
            ET.SubElement(lap, f"{{{tcx_ns}}}DistanceMeters").text = f"{float(total_distance or 0.0):.2f}"
            ET.SubElement(lap, f"{{{tcx_ns}}}MaximumSpeed").text = f"{max((r.get('speed', 0.0) for r in records), default=0.0):.3f}"
            ET.SubElement(lap, f"{{{tcx_ns}}}Calories").text = str(int(total_calories or 0))
            ET.SubElement(lap, f"{{{tcx_ns}}}Intensity").text = "Active"
            ET.SubElement(lap, f"{{{tcx_ns}}}TriggerMethod").text = "Manual"

            track = ET.SubElement(lap, f"{{{tcx_ns}}}Track")
            for rec in records:
                tp = ET.SubElement(track, f"{{{tcx_ns}}}Trackpoint")
                ET.SubElement(tp, f"{{{tcx_ns}}}Time").text = self._format_tcx_timestamp(rec["time"])

                if "lat" in rec and "lon" in rec:
                    pos = ET.SubElement(tp, f"{{{tcx_ns}}}Position")
                    ET.SubElement(pos, f"{{{tcx_ns}}}LatitudeDegrees").text = f"{rec['lat']:.8f}"
                    ET.SubElement(pos, f"{{{tcx_ns}}}LongitudeDegrees").text = f"{rec['lon']:.8f}"

                if "altitude" in rec:
                    ET.SubElement(tp, f"{{{tcx_ns}}}AltitudeMeters").text = f"{rec['altitude']:.2f}"
                if "distance" in rec:
                    ET.SubElement(tp, f"{{{tcx_ns}}}DistanceMeters").text = f"{rec['distance']:.2f}"
                if "heart_rate" in rec:
                    hr = ET.SubElement(tp, f"{{{tcx_ns}}}HeartRateBpm")
                    ET.SubElement(hr, f"{{{tcx_ns}}}Value").text = str(rec['heart_rate'])
                if "cadence" in rec:
                    ET.SubElement(tp, f"{{{tcx_ns}}}Cadence").text = str(rec['cadence'])

                if "speed" in rec or "power" in rec:
                    ext = ET.SubElement(tp, f"{{{tcx_ns}}}Extensions")
                    tpx = ET.SubElement(ext, f"{{{ns3}}}TPX")
                    if "speed" in rec:
                        ET.SubElement(tpx, f"{{{ns3}}}Speed").text = f"{rec['speed']:.3f}"
                    if "power" in rec:
                        ET.SubElement(tpx, f"{{{ns3}}}Watts").text = str(rec['power'])

            creator = ET.SubElement(activity, f"{{{tcx_ns}}}Creator")
            creator.attrib[f"{{{xsi_ns}}}type"] = "Device_t"
            ET.SubElement(creator, f"{{{tcx_ns}}}Name").text = "Garmin Edge 530"
            ET.SubElement(creator, f"{{{tcx_ns}}}UnitId").text = "1234567890"
            ET.SubElement(creator, f"{{{tcx_ns}}}ProductID").text = "3121"
            version = ET.SubElement(creator, f"{{{tcx_ns}}}Version")
            ET.SubElement(version, f"{{{tcx_ns}}}VersionMajor").text = "17"
            ET.SubElement(version, f"{{{tcx_ns}}}VersionMinor").text = "0"
            ET.SubElement(version, f"{{{tcx_ns}}}BuildMajor").text = "0"
            ET.SubElement(version, f"{{{tcx_ns}}}BuildMinor").text = "0"

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            ET.ElementTree(root).write(output_path, encoding='utf-8', xml_declaration=True)
            return True
        except Exception as e:
            log_warning(f"Experimental FIT->TCX conversion failed for {os.path.basename(input_path)}: {e}")
            return False

    def _build_modified_workout_copy(self, file_path, source_name, modified_folder):
        """Create modified copy for experimental device spoof mode.

        Returns: (path_to_upload, spoof_applied, spoof_mode)
        spoof_mode: fit_to_tcx | tcx_modified | passthrough_original
        """
        filename = os.path.basename(file_path)
        stem, ext = os.path.splitext(filename)
        ext = ext.lower()
        modified_path = os.path.join(modified_folder, f"{stem}_spoofed{ext}")

        os.makedirs(modified_folder, exist_ok=True)

        if ext == '.fit':
            converted_path = os.path.join(modified_folder, f"{stem}_spoofed.tcx")
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                spoof_applied = self._convert_fit_to_device_tcx(file_path, converted_path)
                if spoof_applied:
                    if attempt > 1:
                        log_info(f"Experimental spoof succeeded on retry {attempt} for {filename}")
                    return converted_path, True, "fit_to_tcx"
                if attempt < max_attempts:
                    log_warning(f"Experimental spoof retrying FIT conversion ({attempt}/{max_attempts}) for {filename}")
                    time.sleep(1)

        if ext == '.tcx':
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                spoof_applied = self._modify_tcx_for_garmin_device(file_path, modified_path)
                if spoof_applied:
                    if attempt > 1:
                        log_info(f"Experimental spoof succeeded on retry {attempt} for {filename}")
                    return modified_path, True, "tcx_modified"
                if attempt < max_attempts:
                    log_warning(f"Experimental spoof retrying TCX modification ({attempt}/{max_attempts}) for {filename}")
                    time.sleep(1)

        log_warning(
            f"Experimental spoof could not modify/convert {filename} after retries. "
            "Uploading original file unchanged."
        )
        return file_path, False, "passthrough_original"
    
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            'garmin_email': '',
            'garmin_password': '',
            'wahoo_folder': '',
            'mywhoosh_folder': '',
            'trainerday_folder': '',
            'start_with_windows': False,
            'check_interval': 5,
            'experimental_edge_spoof': False
        }
    
    def save_config(self):
        email = self.garmin_email.get()
        password = self.garmin_password.get()
        # Store password in Windows Credential Manager (primary)
        store_password(email, password)
        config = {
            'garmin_email': email,
            'garmin_password': _encode_fallback(password),  # fallback for early-boot
            'wahoo_folder': self.wahoo_folder.get(),
            'mywhoosh_folder': self.mywhoosh_folder.get(),
            'trainerday_folder': self.trainerday_folder.get() if hasattr(self, 'trainerday_folder') else '',
            'start_with_windows': self.start_with_windows.get(),
            'check_interval': self.interval_var.get(),
            'experimental_edge_spoof': self.experimental_edge_spoof.get() if hasattr(self, 'experimental_edge_spoof') else False
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("Configuration saved (password stored in Windows Credential Manager)")
        return config
    
    def load_last_sync_from_log(self):
        """Load last sync and upload info from log file on startup"""
        if not os.path.exists(LOG_FILE):
            return
        
        try:
            # Read last 200 lines of log file to ensure we catch everything
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                last_lines = lines[-200:] if len(lines) > 200 else lines
            
            # Search for last sync completion
            last_sync_time = None
            last_upload_info = None
            
            for line in reversed(last_lines):
                # Look for "Sync completed" messages (with or without checkmark icon)
                if ("Sync completed:" in line or "✅ Sync completed:" in line) and not last_sync_time:
                    # Extract timestamp and info
                    if " - INFO - " in line:
                        timestamp_str = line.split(" - INFO - ")[0]
                        try:
                            # Parse timestamp: 2025-12-29 01:26:34,358
                            dt = datetime.datetime.strptime(timestamp_str.strip(), "%Y-%m-%d %H:%M:%S,%f")
                            last_sync_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                        
                        # Extract upload count
                        if "uploaded" in line.lower():
                            import re
                            match = re.search(r'(\d+) activit', line)
                            if match:
                                count = match.group(1)
                                upload_time = dt.strftime("%Y-%m-%d %H:%M")
                                if int(count) > 0:
                                    last_upload_info = f"Last upload: {upload_time} - {count} file(s) uploaded"
                                else:
                                    last_upload_info = f"Last upload: {upload_time} - No new files"
                
                # Look for individual file uploads to get the filename (handle with or without checkmark)
                if ("Successfully uploaded:" in line or "✅ Successfully uploaded:" in line) and not "file(s)" in str(last_upload_info or ""):
                    if " - INFO - " in line:
                        # Extract filename (handle with or without checkmark)
                        if "✅ Successfully uploaded:" in line:
                            parts = line.split("✅ Successfully uploaded: ")
                        else:
                            parts = line.split("Successfully uploaded: ")
                        
                        if len(parts) > 1:
                            filename = parts[1].strip()
                            try:
                                timestamp_str = line.split(" - INFO - ")[0]
                                dt = datetime.datetime.strptime(timestamp_str.strip(), "%Y-%m-%d %H:%M:%S,%f")
                                upload_time = dt.strftime("%Y-%m-%d %H:%M")
                                last_upload_info = f"Last upload: {upload_time} - Latest: {filename}"
                            except:
                                last_upload_info = f"Last upload: Latest: {filename}"
                            break
            
            # Update UI
            if last_sync_time:
                self.last_sync_label.config(text=f"Last sync: {last_sync_time}")
            
            if last_upload_info:
                self.last_upload_label.config(text=last_upload_info, foreground='green')
            
            if last_sync_time or last_upload_info:
                log_info(f"Restored status from log - Sync: {last_sync_time}, Upload: {last_upload_info}")
        
        except Exception as e:
            log_info(f"Could not load last sync info from log: {str(e)}")
    
    def load_settings(self):
        email = self.config.get('garmin_email', '')
        self.garmin_email.insert(0, email)
        # Retrieve password from Windows Credential Manager (retry once
        # because Credential Manager may not be ready at early boot)
        password = retrieve_password(email)
        if not password and email:
            time.sleep(1)
            password = retrieve_password(email)
        if not password:
            # Fall back to config file (handles both new b64: and legacy XOR formats)
            fallback_pw = self.config.get('garmin_password', '')
            if fallback_pw:
                password = _decode_fallback(fallback_pw)
                if password and email:
                    store_password(email, password)
                    logger.info("Loaded password from config fallback and stored in Credential Manager")
        self.garmin_password.insert(0, password)
        self.wahoo_folder.insert(0, self.config.get('wahoo_folder', ''))
        self.mywhoosh_folder.insert(0, self.config.get('mywhoosh_folder', ''))
        # TrainerDay folder (new in 1.0.5)
        if hasattr(self, 'trainerday_folder'):
            self.trainerday_folder.insert(0, self.config.get('trainerday_folder', ''))
        self.start_with_windows.set(self.config.get('start_with_windows', False))
        self.interval_var.set(self.config.get('check_interval', 5))
        if hasattr(self, 'experimental_edge_spoof'):
            self.experimental_edge_spoof.set(self.config.get('experimental_edge_spoof', False))
        self.check_interval = self.interval_var.get() * 60  # Convert to seconds

        # Update app sections and status icons based on loaded settings
        try:
            self.update_app_sections()
        except Exception:
            pass
    
    def save_settings(self):
        # Check if Garmin credentials have changed
        old_email = self.config.get('garmin_email', '')
        old_password = self.config.get('garmin_password', '')
        new_email = self.garmin_email.get()
        new_password = self.garmin_password.get()
        
        credentials_changed = (new_email != old_email or new_password != old_password)
        
        # Only validate if credentials have changed AND we're not already logged in
        if credentials_changed and new_email and new_password and not self.is_logged_in:
            response = messagebox.askyesno(
                "Test Garmin Credentials?",
                "Your Garmin credentials have changed.\n\n"
                "Would you like to test the connection now?\n\n"
                "(If you have MFA enabled, you'll be prompted for your verification code)"
            )
            if response:
                if not self.validate_garmin_credentials():
                    return  # Don't save if validation fails
        
        self.config = self.save_config()
        self.check_interval = self.interval_var.get() * 60  # Update interval in seconds
        self.settings_changed = False  # Reset flag after saving
        log_success("Settings saved successfully")
        messagebox.showinfo("Settings Saved", "Your settings have been saved successfully!")
        self.update_status("Settings saved", "green")
    
    def test_garmin_connection(self):
        """Test Garmin connection manually (called by Test Connection button)"""
        email = self.garmin_email.get()
        password = self.garmin_password.get()
        
        if not email or not password:
            messagebox.showwarning(
                "Missing Credentials",
                "Please enter both email and password before testing the connection."
            )
            return
        
        self.validate_garmin_credentials()
    
    def validate_garmin_credentials(self):
        """Test Garmin credentials to ensure they're valid (with MFA support)"""
        email = self.garmin_email.get()
        password = self.garmin_password.get()
        
        if not email or not password:
            return True  # Skip validation if empty
        
        # Show progress
        self.update_status("Validating Garmin credentials...", "orange")
        logger.info(f"Validating Garmin credentials for: {email}")
        
        try:
            # Create session directory for this user
            user_session_dir = os.path.join(self.session_dir, email.replace('@', '_').replace('.', '_'))
            os.makedirs(user_session_dir, exist_ok=True)
            
            # Use new garminconnect 0.3.1 API with MFA support
            logger.info("Validating with Garmin (supports MFA)...")
            self.garmin_client = Garmin(email=email, password=password, prompt_mfa=self.prompt_mfa_code)
            self.garmin_client.login(user_session_dir)
            
            log_success("Garmin credentials validated successfully")
            messagebox.showinfo("Credentials Valid", "✅ Garmin credentials are valid!")
            self.update_status("Garmin credentials validated", "green")
            self.update_login_status(True)
            logger.info(f"Tokens saved to: {user_session_dir}")
            logger.info("Garmin client ready for reuse")
            
            return True
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Garmin credential validation failed: {error_msg}")
            
            # Check for rate limiting (429 error)
            if "429" in error_msg or "Too Many Requests" in error_msg:
                self.update_status("Rate limited by Garmin", "red")
                messagebox.showwarning(
                    "Garmin Rate Limit",
                    "🕒 Too Many Login Attempts\n\n"
                    "Garmin has temporarily blocked your account from logging in.\n\n"
                    "What to do:\n"
                    "• Wait 15-30 minutes\n"
                    "• Then try logging in again\n\n"
                    "This is a temporary security measure by Garmin."
                )
            else:
                # Other login errors
                self.update_status("Garmin login failed", "red")
                messagebox.showerror(
                    "Login Failed",
                    f"❌ Could not login to Garmin Connect.\n\n"
                    f"Please check your email and password.\n\n"
                    f"If the problem persists, check the log for details."
                )
            return False
    
    def on_credentials_changed(self):
        """Called when Garmin credentials are modified"""
        self.mark_settings_changed()
        # Clear login state when credentials change
        self.clear_login_status()
    
    def mark_settings_changed(self):
        """Mark that settings have been modified"""
        self.settings_changed = True
    
    def update_login_status(self, logged_in=True):
        """Update the visual login status indicator"""
        self.is_logged_in = logged_in
        if logged_in:
            self.login_status_label.config(text="✓ Logged in", foreground="green")
            logger.info("Garmin login status: Logged in")
        else:
            self.login_status_label.config(text="", foreground="gray")
    
    def clear_login_status(self):
        """Clear login status when credentials change"""
        self.is_logged_in = False
        self.login_status_label.config(text="", foreground="gray")
        logger.debug("Login status cleared due to credential change")
    
    def _maybe_log_upload_day_marker(self):
        """Write a day separator to the uploads log when the day changes"""
        now_day = datetime.datetime.now().strftime("%Y-%m-%d")
        if self._upload_log_day != now_day:
            self._upload_log_day = now_day
            upload_logger.info(f"==== {now_day} ====")
    
    def _get_current_executable(self):
        """
        Return the best path to the currently running executable/binary.
        Nuitka sets __compiled__ and uses sys.executable which can be python.exe
        when launched via a renamed stub, so prefer argv[0] when available.
        """
        if getattr(sys, "frozen", False) or "__compiled__" in globals():
            # Nuitka/PyInstaller
            argv0 = os.path.abspath(sys.argv[0]) if sys.argv else None
            if argv0 and os.path.splitext(argv0)[1].lower() == ".exe":
                return argv0
            return os.path.abspath(sys.executable)
        return os.path.abspath(__file__)

    _SHORTCUT_NAME = "GarminUploader.lnk"

    @staticmethod
    def _get_startup_folder():
        return os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')

    def _get_shortcut_path(self):
        return os.path.join(self._get_startup_folder(), self._SHORTCUT_NAME)

    @staticmethod
    def _create_lnk(lnk_path, target_path, arguments="", working_dir="", description=""):
        """Create a .lnk shortcut via a temporary VBScript executed by cscript.
        No COM from Python, no PowerShell, no win32com."""
        import subprocess
        target_path = os.path.abspath(target_path)
        if not working_dir:
            working_dir = os.path.dirname(target_path)
        vbs = (
            'Set ws = CreateObject("WScript.Shell")\n'
            f'Set sc = ws.CreateShortcut("{lnk_path}")\n'
            f'sc.TargetPath = "{target_path}"\n'
            f'sc.Arguments = "{arguments}"\n'
            f'sc.WorkingDirectory = "{working_dir}"\n'
            f'sc.Description = "{description}"\n'
            'sc.WindowStyle = 7\n'
            'sc.Save\n'
        )
        vbs_path = os.path.join(tempfile.gettempdir(), "_garmin_mklink.vbs")
        try:
            with open(vbs_path, 'w') as f:
                f.write(vbs)
            result = subprocess.run(
                ['cscript', '//Nologo', '//B', vbs_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(f"cscript failed: {result.stderr.strip()}")
        finally:
            try:
                os.remove(vbs_path)
            except OSError:
                pass

    @staticmethod
    def _read_lnk_target(lnk_path):
        """Read the target path from a .lnk file via a temporary VBScript.
        Returns the target path string or None on failure."""
        import subprocess
        vbs = (
            'Set ws = CreateObject("WScript.Shell")\n'
            f'Set sc = ws.CreateShortcut("{lnk_path}")\n'
            'WScript.Echo sc.TargetPath\n'
        )
        vbs_path = os.path.join(tempfile.gettempdir(), "_garmin_rdlink.vbs")
        try:
            with open(vbs_path, 'w') as f:
                f.write(vbs)
            result = subprocess.run(
                ['cscript', '//Nologo', vbs_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            return None
        except Exception:
            return None
        finally:
            try:
                os.remove(vbs_path)
            except OSError:
                pass

    @staticmethod
    def _remove_registry_autostart_legacy():
        """Remove any registry Run entry left by v1.0.3/v1.0.4 (one-time migration)"""
        try:
            import winreg
            reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "GarminUploader")
            logger.info("Removed legacy registry auto-start entry from v1.0.3/v1.0.4")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Could not remove legacy registry entry: {e}")

    def _create_autostart_shortcut(self):
        """Create a .lnk shortcut in the Startup folder using pure Python"""
        exe_path = self._get_current_executable()
        working_dir = os.path.dirname(exe_path)
        shortcut_path = self._get_shortcut_path()
        os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
        self._create_lnk(
            shortcut_path, exe_path,
            arguments="--minimized",
            working_dir=working_dir,
            description="Garmin Connect Uploader"
        )
        logger.info(f"Auto-start shortcut created: {shortcut_path}")

    def _remove_autostart_shortcut(self):
        """Remove the .lnk shortcut from the Startup folder"""
        shortcut_path = self._get_shortcut_path()
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
            logger.info(f"Auto-start shortcut removed: {shortcut_path}")

    def toggle_autostart(self):
        """Toggle Windows startup using a Startup-folder shortcut"""
        if self.start_with_windows.get():
            try:
                self._create_autostart_shortcut()
                messagebox.showinfo("Auto-Start Enabled", "Garmin Uploader will now start automatically when Windows starts!\n\nIt will start minimized to system tray.")
                self.update_status("Auto-start enabled", "green")
            except Exception as e:
                logger.error(f"Failed to enable auto-start: {str(e)}")
                messagebox.showerror("Error", f"Could not enable auto-start: {e}")
                self.start_with_windows.set(False)
        else:
            try:
                self._remove_autostart_shortcut()
                messagebox.showinfo("Auto-Start Disabled", "Garmin Uploader will no longer start automatically.")
                self.update_status("Auto-start disabled", "blue")
            except Exception as e:
                logger.error(f"Failed to disable auto-start: {str(e)}")
                messagebox.showerror("Error", f"Could not disable auto-start: {e}")

    def check_old_version_shortcut(self):
        """Check startup shortcut version and clean up legacy registry entries"""
        try:
            # --- Phase 0: remove any registry entry left by v1.0.3/v1.0.4 ---
            self._remove_registry_autostart_legacy()

            # --- Phase 1: check if shortcut exists ---
            shortcut_path = self._get_shortcut_path()
            logger.info(f"Checking for auto-start shortcut at: {shortcut_path}")

            if not os.path.exists(shortcut_path):
                if hasattr(self, 'start_with_windows') and self.start_with_windows.get():
                    logger.info("Auto-start enabled but shortcut missing - recreating")
                    self._create_autostart_shortcut()
                else:
                    logger.info("No autostart shortcut found and not enabled - skipping")
                return

            # --- Phase 2: verify shortcut points to current exe ---
            if not (getattr(sys, 'frozen', False) or '__compiled__' in globals()):
                logger.info("Running as script - skipping version check")
                return

            current_exe = self._get_current_executable()
            target_path = self._read_lnk_target(shortcut_path)

            if not target_path:
                logger.warning("Could not read shortcut target path")
                return

            logger.info(f"Shortcut target: {target_path}")

            if os.path.normcase(os.path.normpath(target_path)) != os.path.normcase(os.path.normpath(current_exe)):
                old_version = os.path.basename(target_path)
                current_version = os.path.basename(current_exe)
                logger.info(f"Version mismatch: {old_version} -> {current_version}")
                replace = messagebox.askyesno(
                    "Update Startup Entry",
                    f"The auto-start shortcut points to a different version.\n\n"
                    f"Current: {old_version}\n"
                    f"New: {current_version}\n\n"
                    f"Update to the new version?"
                )
                if replace:
                    os.remove(shortcut_path)
                    self._create_autostart_shortcut()
                    logger.info("User approved shortcut update")
                else:
                    logger.info("User declined shortcut update")
            else:
                logger.info("Shortcut already points to current version")

        except Exception as e:
            logger.warning(f"Error checking auto-start: {str(e)}")
    
    def validate_settings(self):
        if not self.garmin_email.get() or not self.garmin_password.get():
            messagebox.showerror("Error", "Please enter your Garmin email and password")
            log_warning("Sync attempted without Garmin credentials")
            return False
        
        wahoo = self.wahoo_folder.get().strip()
        mywhoosh = self.mywhoosh_folder.get().strip()
        trainerday = self.trainerday_folder.get().strip() if hasattr(self, 'trainerday_folder') else ""

        # Consider an app "selected" if it has any folder text entered
        wahoo_selected = bool(wahoo)
        mywhoosh_selected = bool(mywhoosh)
        trainerday_selected = bool(trainerday)

        # At least one app must have a folder configured
        if not (wahoo_selected or mywhoosh_selected or trainerday_selected):
            messagebox.showerror(
                "No Folders Configured",
                "Please configure at least one folder in Folder Settings (Wahoo, MyWhoosh, or TrainerDay)."
            )
            log_warning("Sync attempted without any folders configured")
            return False

        # Warn about non-existent folders but allow sync
        if wahoo_selected and not os.path.isdir(wahoo):
            response = messagebox.askyesno(
                "Wahoo Folder Not Found",
                f"Wahoo folder not found:\n{wahoo}\n\nContinue anyway?"
            )
            if not response:
                return False
            log_warning(f"Wahoo folder not found but user chose to continue: {wahoo}")
        
        if mywhoosh_selected and not os.path.isdir(mywhoosh):
            response = messagebox.askyesno(
                "MyWhoosh Folder Not Found",
                f"MyWhoosh folder not found:\n{mywhoosh}\n\nContinue anyway?"
            )
            if not response:
                return False
            log_warning(f"MyWhoosh folder not found but user chose to continue: {mywhoosh}")

        if trainerday_selected and trainerday and not os.path.isdir(trainerday):
            response = messagebox.askyesno(
                "TrainerDay Folder Not Found",
                f"TrainerDay folder not found:\n{trainerday}\n\nContinue anyway?"
            )
            if not response:
                return False
            log_warning(f"TrainerDay folder not found but user chose to continue: {trainerday}")

        self._update_app_status_icons()
        return True
    
    def login_garmin_with_retry(self, max_retries=1, delay=2):
        """Login to Garmin with MFA support (single attempt to avoid rate limiting)"""
        for attempt in range(max_retries):
            try:
                self.update_status(f"Logging into Garmin...", "orange")
                logger.info(f"Attempting Garmin login")
                
                # Get credentials
                email = self.garmin_email.get()
                password = self.garmin_password.get()
                if not email:
                    email = self.config.get('garmin_email', '')
                if not password:
                    password = self.config.get('garmin_password', '')
                
                # Create session directory specific to this user
                user_session_dir = os.path.join(self.session_dir, email.replace('@', '_').replace('.', '_'))
                os.makedirs(user_session_dir, exist_ok=True)
                
                # Use new garminconnect 0.3.1 API with MFA support
                logger.info("Authenticating with Garmin (supports MFA)...")
                self.garmin_client = Garmin(email=email, password=password, prompt_mfa=self.prompt_mfa_code)
                self.garmin_client.login(user_session_dir)
                logger.info("Garmin login successful, tokens saved")
                
                log_success("Garmin login successful")
                self.update_status("Logged into Garmin successfully", "green")
                self.update_login_status(True)
                return True
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Garmin login attempt {attempt + 1} failed: {error_msg}")
                
                # Check for rate limiting (429 error)
                if "429" in error_msg or "Too Many Requests" in error_msg:
                    logger.error("Rate limited by Garmin - too many login attempts")
                    self.update_status("Rate limited by Garmin", "red")
                    messagebox.showwarning(
                        "Garmin Rate Limit",
                        "🕒 Too Many Login Attempts\n\n"
                        "Garmin has temporarily blocked your account from logging in.\n\n"
                        "What to do:\n"
                        "• Wait 15-30 minutes\n"
                        "• Then try logging in again\n\n"
                        "This is a temporary security measure by Garmin."
                    )
                    return False
                
                if attempt < max_retries - 1:
                    logger.info(f"Waiting {delay} seconds before retry...")
                    time.sleep(delay)
                    # Increase delay for next attempt
                    delay *= 2  # Exponential backoff
                else:
                    logger.error("All login attempts failed")
                    self.update_status(f"Garmin login failed: {error_msg}", "red")
                    messagebox.showerror("Login Failed", f"Could not login to Garmin after {max_retries} attempts:\n{error_msg}")
        return False
    
    def is_garmin_logged_in(self):
        """Check if we have a valid Garmin session without triggering login/MFA"""
        if not self.garmin_client:
            return False
        
        try:
            # Quick check - try to get user profile
            self.garmin_client.get_user_profile()
            return True
        except Exception as e:
            logger.debug(f"Garmin session check failed: {str(e)}")
            return False
    
    def login_garmin(self):
        """Wrapper method that calls the retry version"""
        return self.login_garmin_with_retry()
    
    def sync_now(self):
        if not self.validate_settings():
            return
        
        # Run sync in background thread
        thread = threading.Thread(target=self._sync_files, daemon=True)
        thread.start()
    
    def _sync_files(self):
        self.sync_button.config(state='disabled')
        
        # Check if we're running in background (window hidden/withdrawn)
        is_background = self.root.state() == 'withdrawn'
        
        # Check if we're already logged in and session is valid
        if self.is_logged_in and self.garmin_client and self.is_garmin_logged_in():
            logger.debug("Already logged in, reusing existing session")
        else:
            # Need to login - try session first, then credentials if needed
            if not self.garmin_client:
                # First try to use saved session (doesn't trigger MFA)
                if not self.try_session_login():
                    # If session login failed and we're in background, skip login attempt
                    if is_background:
                        logger.warning("Garmin login required but app is in background - skipping sync")
                        self.update_status("Login required - please open app", "orange")
                        self.sync_button.config(state='normal')
                        return
                    # If we're in foreground, try credentials (may trigger MFA)
                    if not self.login_garmin():
                        self.sync_button.config(state='normal')
                        return
            else:
                # Client exists but session may have expired; verify it
                if not self.is_garmin_logged_in():
                    logger.warning("Existing Garmin session expired")
                    self.garmin_client = None
                    self.update_login_status(False)
                    # If in background, skip re-authentication
                    if is_background:
                        logger.warning("Re-authentication required but app is in background - skipping sync")
                        self.update_status("Login required - please open app", "orange")
                        self.sync_button.config(state='normal')
                        return
                    # If in foreground, try to re-authenticate
                    if not self.login_garmin():
                        self.sync_button.config(state='normal')
                        return
        
        uploaded_count = 0
        last_uploaded_file = None

        # Determine which apps have folders configured
        wahoo_folder = self.wahoo_folder.get().strip()
        mywhoosh_folder = self.mywhoosh_folder.get().strip()
        trainerday_folder = self.trainerday_folder.get().strip() if hasattr(self, 'trainerday_folder') else ""

        # Take a snapshot of activities BEFORE processing any files
        # This is used for TrainerDay title mapping to identify which activity was just uploaded
        pre_sync_activity_ids = None
        if trainerday_folder and os.path.isdir(trainerday_folder):
            try:
                pre_activities = self.garmin_client.get_activities(0, 20)
                pre_sync_activity_ids = {
                    a["activityId"]
                    for a in pre_activities
                    if isinstance(a, dict) and "activityId" in a
                }
                logger.info(f"Captured pre-sync activity snapshot: {len(pre_sync_activity_ids)} activities")
            except Exception as pre_err:
                log_warning(f"Could not capture pre-sync activities for TrainerDay title mapping: {pre_err}")

        # Sync Wahoo files (only if folder exists)
        if wahoo_folder and os.path.isdir(wahoo_folder):
            count, last_file = self._process_folder(wahoo_folder, "Wahoo", pre_sync_activity_ids)
            uploaded_count += count
            if last_file:
                last_uploaded_file = last_file

        # Sync MyWhoosh files (only if folder exists)
        if mywhoosh_folder and os.path.isdir(mywhoosh_folder):
            count, last_file = self._process_folder(mywhoosh_folder, "MyWhoosh", pre_sync_activity_ids)
            uploaded_count += count
            if last_file:
                last_uploaded_file = last_file

        # Sync TrainerDay files (only if folder exists)
        if trainerday_folder and os.path.isdir(trainerday_folder):
            count, last_file = self._process_folder(trainerday_folder, "TrainerDay", pre_sync_activity_ids)
            uploaded_count += count
            if last_file:
                last_uploaded_file = last_file
        
        # Update UI
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.last_sync_label.config(text=f"Last sync: {current_time}")
        
        if uploaded_count > 0:
            self.update_status(f"Sync complete! Uploaded {uploaded_count} activities", "green")
            # Update last upload info
            upload_time = time.strftime("%Y-%m-%d %H:%M")
            self.last_upload_label.config(
                text=f"Last upload: {upload_time} - {uploaded_count} file(s) - Latest: {last_uploaded_file}",
                foreground='green'
            )
            log_success(f"Sync completed: {uploaded_count} activities uploaded")
        else:
            self.update_status("Sync complete - no new activities found", "blue")
            log_success("Sync completed: No new activities found")
        
        self.sync_button.config(state='normal')
    
    def _process_folder(self, folder, source_name, pre_sync_activity_ids=None):
        uploaded = 0
        last_uploaded_file = None
        uploaded_folder = os.path.join(folder, "uploaded")
        modified_folder = os.path.join(uploaded_folder, "modified")
        os.makedirs(uploaded_folder, exist_ok=True)

        # Decide which file extensions to process for this source
        # Wahoo / MyWhoosh use .fit; TrainerDay exports .tcx via Dropbox
        if source_name == "TrainerDay":
            allowed_exts = (".fit", ".tcx")
        else:
            allowed_exts = (".fit",)

        # Add blank line before new job for better log grouping
        log_separator()
        logger.info(f"Processing {source_name} folder: {folder} (extensions: {', '.join(allowed_exts)})")

        try:
            for filename in os.listdir(folder):
                # Skip the 'uploaded' subfolder
                if filename == 'uploaded':
                    continue

                # Only process files with the allowed extensions
                if not filename.lower().endswith(allowed_exts):
                    continue

                file_path = os.path.join(folder, filename)

                if os.path.isfile(file_path):
                    self.update_status(f"Uploading {filename}...", "orange")
                    log_info(f"Uploading file: {filename} from {source_name}")

                    try:
                        self._maybe_log_upload_day_marker()

                        upload_file_path = file_path
                        spoof_mode = None
                        if source_name in ("Wahoo", "TrainerDay", "MyWhoosh") and hasattr(self, 'experimental_edge_spoof') and self.experimental_edge_spoof.get():
                            upload_file_path, _, spoof_mode = self._build_modified_workout_copy(
                                file_path, source_name, modified_folder
                            )

                        self.garmin_client.upload_activity(upload_file_path)
                        if spoof_mode:
                            if spoof_mode == "fit_to_tcx":
                                detail = f"device-spoof: FIT->TCX conversion ({os.path.basename(upload_file_path)})"
                            elif spoof_mode == "tcx_modified":
                                detail = f"device-spoof: TCX metadata modified ({os.path.basename(upload_file_path)})"
                            else:
                                detail = f"device-spoof fallback: original file upload ({os.path.basename(upload_file_path)})"
                            log_info(f"Uploaded via experimental path: {detail}")
                            upload_logger.info(f"Upload path for {filename}: {detail}")

                        # For TrainerDay uploads, try to set a friendly activity title
                        if source_name == "TrainerDay":
                            try:
                                base_name, _ = os.path.splitext(filename)
                                if " - " in base_name:
                                    activity_title = base_name.split(" - ", 1)[1].strip()
                                    if activity_title:
                                        activity_id = None

                                        # First try to find a new activity that appeared
                                        # between the pre-sync and post-upload activity lists.
                                        if pre_sync_activity_ids is not None:
                                            try:
                                                max_attempts = 6
                                                delay_seconds = 2
                                                for attempt in range(max_attempts):
                                                    post_activities = self.garmin_client.get_activities(0, 20)
                                                    new_activities = [
                                                        a
                                                        for a in post_activities
                                                        if isinstance(a, dict)
                                                        and "activityId" in a
                                                        and a["activityId"] not in pre_sync_activity_ids
                                                    ]
                                                    
                                                    # Find the activity that matches this specific file
                                                    # by checking if it was uploaded in the last few seconds
                                                    matching_activity = None
                                                    for activity in new_activities:
                                                        # The activity we just uploaded should be the most recent one
                                                        # that's not in the pre-sync snapshot
                                                        if matching_activity is None:
                                                            matching_activity = activity
                                                        elif activity.get("startTimeGMT", 0) > matching_activity.get("startTimeGMT", 0):
                                                            matching_activity = activity
                                                    
                                                    if matching_activity:
                                                        activity_id = matching_activity["activityId"]
                                                        logger.info(f"Found TrainerDay activity via diff: {activity_id} (attempt {attempt + 1})")
                                                        break
                                                    
                                                    # If we didn't find a new activity yet,
                                                    # wait a bit and let Garmin finish processing.
                                                    if attempt < max_attempts - 1:
                                                        logger.info(f"Waiting for Garmin to process TrainerDay activity (attempt {attempt + 1}/{max_attempts})...")
                                                        time.sleep(delay_seconds)
                                            except Exception as diff_err:
                                                log_warning(
                                                    f"Could not diff activities for TrainerDay title mapping: {diff_err}"
                                                )

                                        # If diffing failed or wasn't conclusive, fall back
                                        # to Garmin's notion of the last activity.
                                        if activity_id is None:
                                            last_activity = (
                                                self.garmin_client.get_last_activity()
                                            )
                                            if last_activity and "activityId" in last_activity:
                                                activity_id = last_activity["activityId"]

                                        if activity_id is not None:
                                            self.garmin_client.set_activity_name(
                                                activity_id, activity_title
                                            )
                                            log_info(
                                                f"Set TrainerDay activity title to '{activity_title}' for {filename} (activityId={activity_id})"
                                            )
                            except Exception as title_err:
                                log_warning(
                                    f"Could not set TrainerDay activity title for {filename}: {title_err}"
                                )

                        uploaded += 1
                        last_uploaded_file = filename
                        log_success(f"Successfully uploaded: {filename}")
                        upload_logger.info(f"Uploaded: {filename}")

                        # Move to uploaded folder
                        dest_path = os.path.join(uploaded_folder, filename)
                        try:
                            shutil.move(file_path, dest_path)
                            log_info(f"Moved {filename} to uploaded folder")
                        except PermissionError:
                            shutil.copy2(file_path, dest_path)
                            log_warning(f"File locked, copied instead of moved: {filename}")

                        self.update_status(f"Uploaded {filename}", "green")

                    except Exception as e:
                        error_msg = str(e)
                        if "409" in error_msg or "Conflict" in error_msg:
                            log_info(f"File already uploaded (409 conflict): {filename}")
                            # Already uploaded, move it
                            dest_path = os.path.join(uploaded_folder, filename)
                            try:
                                shutil.move(file_path, dest_path)
                            except PermissionError:
                                shutil.copy2(file_path, dest_path)
                        else:
                            log_error(f"Failed to upload {filename}: {error_msg}")
                            self.update_status(f"Failed to upload {filename}: {error_msg}", "red")
        
        except Exception as e:
            log_error(f"Error processing {source_name} folder: {str(e)}")
            self.update_status(f"Error processing {source_name} folder: {str(e)}", "red")
        
        # Log completion with success icon
        if uploaded > 0:
            log_success(f"Completed {source_name} processing. Uploaded: {uploaded} files")
        else:
            log_success(f"Completed {source_name} processing. No new files to upload")
        
        # Add blank line after job completion for better grouping
        log_separator()
        return uploaded, last_uploaded_file
    
    def toggle_monitoring(self):
        if self.is_monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()
    
    def start_monitoring(self):
        if not self.validate_settings():
            return
        
        # Check if we're already logged in and session is valid
        if self.is_logged_in and self.garmin_client and self.is_garmin_logged_in():
            logger.debug("Already logged in, starting monitoring with existing session")
        elif not self.garmin_client:
            # First try to use saved session
            if not self.try_session_login():
                # If session login failed, try credentials
                if not self.login_garmin():
                    return
        else:
            # Client exists but may be invalid
            if not self.is_garmin_logged_in():
                logger.warning("Existing session expired, re-authenticating")
                self.garmin_client = None
                self.update_login_status(False)
                if not self.login_garmin():
                    return
        
        logger.info(f"Starting auto-sync monitoring (interval: {self.check_interval//60} minutes)")
        self.is_monitoring = True
        self.monitor_button.config(text="Stop Auto-Sync")
        self.sync_button.config(state='disabled')
        self.update_status("Auto-sync started (checking every 5 minutes)", "green")
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        logger.info("Stopping auto-sync monitoring")
        self.is_monitoring = False
        self.monitor_button.config(text="Start Auto-Sync")
        self.sync_button.config(state='normal')
        self.update_status("Auto-sync stopped", "blue")
    
    def _monitor_loop(self):
        while self.is_monitoring:
            self._sync_files()
            
            # Wait using check_interval
            for _ in range(self.check_interval):
                if not self.is_monitoring:
                    break
                time.sleep(1)
    
    def update_status(self, message, color="blue"):
        # Add colored icons based on status type
        icon = ""
        if color == "green":
            icon = "✅ "  # Success
        elif color == "red":
            icon = "❌ "  # Error
        elif color == "orange":
            icon = "🔄 "  # In progress
        elif color == "blue":
            icon = "ℹ️ "  # Info
        
        self.status_label.config(text=f"Status: {icon}{message}", foreground=color)
        self.root.update_idletasks()
    
    def minimize_to_tray(self):
        """Explicitly minimize to system tray"""
        if not self.is_monitoring:
            response = messagebox.askyesno(
                "Start Auto-Sync?",
                "To minimize to tray, Auto-Sync should be running.\n\nWould you like to start Auto-Sync now?"
            )
            if response:
                # Start monitoring (which handles login if needed)
                self.start_monitoring()
            else:
                messagebox.showinfo(
                    "Minimize to Tray",
                    "Auto-Sync must be running to minimize to tray.\n\nTip: Start Auto-Sync first, then use this button."
                )
                return
        
        # Hide window and create tray icon
        self.root.withdraw()
        self.create_tray_icon()
        logger.info("Window minimized to system tray by user")
    
    def on_closing(self):
        """Handle window close - ask user if they want to run in background or close"""
        # Check for unsaved settings first
        if self.settings_changed:
            response = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved settings changes.\n\nDo you want to save them before closing?"
            )
            if response is None:  # Cancel
                return
            elif response:  # Yes - save
                self.save_settings()
        
        # Always ask user what they want to do
        if self.is_monitoring:
            # Already running - ask if they want to keep running or close
            response = messagebox.askyesno(
                "Keep Running in Background?",
                "Auto-Sync is currently running.\n\n"
                "• YES - Minimize to tray and keep syncing\n"
                "• NO - Stop syncing and close app"
            )
            if response:
                self.root.withdraw()
                self.create_tray_icon()
                self.update_status("Running in system tray", "green")
            else:
                self.quit_app()
        else:
            # Not running - ask if they want to start background sync or close
            response = messagebox.askyesno(
                "Run in Background?",
                "Would you like to start Auto-Sync and run in the background?\n\n"
                "• YES - Start syncing and minimize to tray\n"
                "• NO - Close the app"
            )
            if response:
                # Try to start auto-sync
                if self.validate_settings():
                    if not self.garmin_client:
                        if not self.login_garmin():
                            return
                    self.start_monitoring()
                    self.root.withdraw()
                    self.create_tray_icon()
                    self.update_status("Running in system tray", "green")
            else:
                self.quit_app()
    
    def create_tray_icon(self):
        """Create system tray icon"""
        if self.tray_icon:
            return  # Already created
        
        try:
            # Load icon image
            if os.path.exists(LOGO_PATH):
                icon_image = Image.open(LOGO_PATH)
            else:
                # Create a simple default icon if logo not found
                icon_image = Image.new('RGB', (64, 64), color='blue')
            
            # Create menu
            menu = Menu(
                MenuItem('Show Window', self.show_window),
                MenuItem('Sync Now', self.tray_sync_now),
                MenuItem('Exit', self.quit_app)
            )
            
            # Create tray icon
            self.tray_icon = Icon("GarminUploader", icon_image, "Garmin Uploader", menu)
            
            # Run in separate thread
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"Could not create tray icon: {e}")
    
    def show_window(self, icon=None, item=None):
        """Show the main window from tray"""
        self.root.deiconify()  # Show window
        self.root.lift()  # Bring to front
    
    def tray_sync_now(self, icon=None, item=None):
        """Trigger sync from tray menu"""
        threading.Thread(target=self._sync_files, daemon=True).start()
    
    def quit_app(self, icon=None, item=None):
        """Quit the application completely"""
        if self.is_monitoring:
            self.stop_monitoring()
        
        if self.tray_icon:
            self.tray_icon.stop()
        
        self.root.quit()
        self.root.destroy()
    
    def show_about(self):
        """Show About dialog with developer info"""
        about_window = tk.Toplevel(self.root)
        about_window.title("About Garmin Connect Uploader")
        # Apply DPI scaling
        base_width, base_height = 500, 420
        width = int(base_width * (self.scaling / 1.33))
        height = int(base_height * (self.scaling / 1.33))
        about_window.geometry(f"{width}x{height}")
        about_window.resizable(False, False)
        
        # Icon/logo at top
        try:
            if os.path.exists(LOGO_PATH):
                logo_img = Image.open(LOGO_PATH)
                logo_img.thumbnail((64, 64))
                self.about_logo = ImageTk.PhotoImage(logo_img)
        except Exception:
            self.about_logo = None
        
        # Container
        content = ttk.Frame(about_window, padding=15)
        content.pack(fill=tk.BOTH, expand=True)
        
        # Logo row (optional)
        if self.about_logo:
            logo_row = ttk.Frame(content)
            logo_row.pack(pady=(0, 10))
            ttk.Label(logo_row, image=self.about_logo).pack()
        
        # Title
        ttk.Label(content, text="Garmin Connect Uploader", font=('Arial', 14, 'bold')).pack()
        ttk.Label(content, text=f"Version {VERSION}", font=('Arial', 10)).pack(pady=(0, 15))
        
        # Description
        desc_text = "Automatically upload workout activities from Wahoo, MyWhoosh, and TrainerDay to Garmin Connect."
        ttk.Label(content, text=desc_text, wraplength=420, justify='center').pack(pady=(0, 15))
        
        # Developer info with logo
        ttk.Label(content, text="Developer", font=('Arial', 11, 'bold')).pack(pady=(10, 5))
        
        # Try to load developer logo
        dev_logo_path = DEV_LOGO_PATH
        if dev_logo_path and os.path.exists(dev_logo_path):
            try:
                dev_logo_img = Image.open(dev_logo_path)
                dev_logo_img.thumbnail((75, 75))  # Increased by 25% (60 -> 75)
                dev_logo_photo = ImageTk.PhotoImage(dev_logo_img)
                logo_label = ttk.Label(content, image=dev_logo_photo)
                logo_label.image = dev_logo_photo  # Keep reference
                logo_label.pack(pady=5)
            except:
                pass  # If fails, just skip the logo
        
        dev_frame = ttk.Frame(content)
        dev_frame.pack(pady=5)
        
        # GitHub link with logo
        github_frame = ttk.Frame(dev_frame)
        github_frame.pack(pady=5)
        
        # Try to load GitHub logo
        github_logo_path = GITHUB_LOGO_PATH
        if github_logo_path and os.path.exists(github_logo_path):
            try:
                github_img = Image.open(github_logo_path)
                github_img.thumbnail((96, 96))  # Much larger - 3x bigger
                github_photo = ImageTk.PhotoImage(github_img)
                github_logo_label = ttk.Label(github_frame, image=github_photo, cursor='hand2')
                github_logo_label.image = github_photo  # Keep reference
                github_logo_label.pack()
                github_logo_label.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/Inc21"))
            except:
                # Fallback to text if logo fails
                github_link = ttk.Label(
                    github_frame,
                    text="github.com/Inc21",
                    foreground='blue',
                    cursor='hand2',
                    font=('Arial', 9, 'underline')
                )
                github_link.pack()
                github_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/Inc21"))
        
        # Buttons frame
        btn_frame = ttk.Frame(content)
        btn_frame.pack(pady=10)
        
        # Buy Me a Coffee button with yellow background
        coffee_btn = tk.Button(
            btn_frame,
            text="☕ Buy me a coffee",
            command=lambda: webbrowser.open("https://buymeacoffee.com/inc21"),
            bg="#FFDD00",
            fg="black",
            font=('Arial', 9, 'bold'),
            cursor='hand2',
            relief=tk.RAISED,
            bd=2,
            padx=10,
            pady=5
        )
        coffee_btn.pack(side=tk.LEFT, padx=5)
        
        # View Log File button
        log_btn = ttk.Button(btn_frame, text="📄 View Log", command=self.open_log_file)
        log_btn.pack(side=tk.LEFT, padx=5)

        # View Uploads Log button
        uploads_btn = ttk.Button(btn_frame, text="📄 View Uploads Log", command=self.open_upload_log)
        uploads_btn.pack(side=tk.LEFT, padx=5)

        # Check for updates button
        updates_btn = ttk.Button(btn_frame, text="Check for updates", command=self.check_for_updates)
        updates_btn.pack(side=tk.LEFT, padx=5)
        
        # Close button - full width for better visibility
        close_btn = ttk.Button(content, text="Close", command=about_window.destroy, width=15)
        close_btn.pack(pady=(5, 0))

        # Prevent the dialog (and Close button) from being squashed
        about_window.update_idletasks()
        req_w = about_window.winfo_reqwidth()
        req_h = about_window.winfo_reqheight()
        about_window.minsize(req_w, req_h)

    def _version_to_tuple(self, value):
        """Convert version strings like v1.2.3 to comparable tuples."""
        cleaned = str(value or "").strip()
        if cleaned.lower().startswith('v'):
            cleaned = cleaned[1:]

        parts = []
        for chunk in cleaned.split('.'):
            digits = ''.join(ch for ch in chunk if ch.isdigit())
            parts.append(int(digits) if digits else 0)

        return tuple(parts) if parts else (0,)

    def _show_update_available_dialog(self, latest_label, release_url):
        """Show update dialog with clickable release URL."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Update available")

        base_width, base_height = 480, 180
        width = int(base_width * (self.scaling / 1.33))
        height = int(base_height * (self.scaling / 1.33))
        dialog.geometry(f"{width}x{height}")
        dialog.resizable(False, False)

        content = ttk.Frame(dialog, padding=14)
        content.pack(fill=tk.BOTH, expand=True)

        ttk.Label(content, text=f"New version {latest_label} is available.", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 8))
        ttk.Label(content, text="Get it here:").pack(anchor='w')

        link_label = ttk.Label(
            content,
            text="GitHub Releases",
            foreground='blue',
            cursor='hand2',
            font=('Arial', 9, 'underline')
        )
        link_label.pack(anchor='w', pady=(2, 12))
        link_label.bind("<Button-1>", lambda e: webbrowser.open(release_url))

        btn_frame = ttk.Frame(content)
        btn_frame.pack(anchor='e')
        ttk.Button(btn_frame, text="Open", command=lambda: webbrowser.open(release_url)).pack(side='left', padx=(0, 6))
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side='left')

    def check_for_updates(self):
        """Check GitHub version.json and notify user about available updates."""
        try:
            body = None
            last_error = None
            for url in (VERSION_JSON_URL, LEGACY_VERSION_JSON_URL):
                try:
                    with urllib.request.urlopen(url, timeout=10) as response:
                        body = response.read().decode('utf-8')
                    break
                except Exception as e:
                    last_error = e

            if body is None:
                raise last_error if last_error else urllib.error.URLError("Unable to fetch version.json")

            payload = json.loads(body)
            latest_version = str(payload.get('version', '')).strip()
            release_url = str(payload.get('url', GITHUB_REPO_URL)).strip() or GITHUB_REPO_URL

            if not latest_version:
                messagebox.showwarning(
                    "Check for updates",
                    "Could not find a valid version in version.json."
                )
                return

            current_tuple = self._version_to_tuple(VERSION)
            latest_tuple = self._version_to_tuple(latest_version)
            latest_label = latest_version if latest_version.lower().startswith('v') else f"v{latest_version}"

            if latest_tuple > current_tuple:
                self._show_update_available_dialog(latest_label, release_url)
            else:
                messagebox.showinfo(
                    "Up to date",
                    f"You are on the latest version ({VERSION})."
                )

        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            log_warning(f"Update check failed: {e}")
            messagebox.showwarning(
                "Check for updates",
                "Unable to check for updates right now. Please try again later."
            )
        except Exception as e:
            log_warning(f"Unexpected update check error: {e}")
            messagebox.showwarning(
                "Check for updates",
                "Unable to check for updates right now. Please try again later."
            )
    
    def open_log_file(self):
        """Open the log file in a viewer window (opens at the end)"""
        try:
            if not os.path.exists(LOG_FILE):
                messagebox.showinfo("Log File", f"Log file not found yet.\n\nIt will be created at:\n{LOG_FILE}\n\nonce you start using the app.")
                return
            
            # Create a viewer window
            log_window = tk.Toplevel(self.root)
            log_window.title("Garmin Uploader - Log File")
            
            # Apply DPI scaling
            base_width, base_height = 900, 600
            width = int(base_width * (self.scaling / 1.33))
            height = int(base_height * (self.scaling / 1.33))
            log_window.geometry(f"{width}x{height}")
            
            # Create scrolled text widget
            text_widget = scrolledtext.ScrolledText(
                log_window,
                wrap=tk.WORD,
                font=('Courier New', 9)
            )
            text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            
            # Read and display log file
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                log_content = f.read()
                text_widget.insert(1.0, log_content)
            
            # Scroll to the end
            text_widget.see(tk.END)
            
            # Make text selectable but prevent editing
            # Bind keys to prevent modification while allowing Ctrl+F search
            def block_edit(event):
                # Allow Ctrl+C (copy), Ctrl+A (select all), Ctrl+F (find), arrow keys, etc.
                if event.state & 0x4:  # Ctrl is pressed
                    return  # Allow Ctrl+key combinations
                if event.keysym in ('Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Prior', 'Next'):
                    return  # Allow navigation
                return "break"  # Block other keys
            
            text_widget.bind("<Key>", block_edit)
            
            # Add search functionality with Ctrl+F
            search_start_index = '1.0'
            
            search_window = None  # Track search window to prevent multiple instances
            
            def find_text(event=None):
                nonlocal search_start_index, search_window
                
                # If search window already exists, focus it instead of creating new one
                if search_window and search_window.winfo_exists():
                    search_window.focus()
                    return
                
                # Create search dialog
                search_window = tk.Toplevel(log_window)
                search_window.title("Find in Log")
                
                # Apply DPI scaling
                base_width, base_height = 500, 140
                width = int(base_width * (self.scaling / 1.33))
                height = int(base_height * (self.scaling / 1.33))
                search_window.geometry(f"{width}x{height}")
                search_window.resizable(False, False)
                search_window.transient(log_window)
                
                ttk.Label(search_window, text="Find:").pack(pady=(15, 5), padx=15, anchor='w')
                search_entry = ttk.Entry(search_window, width=50)
                search_entry.pack(pady=5, padx=15, fill='x')
                search_entry.focus()
                
                def do_search():
                    nonlocal search_start_index
                    search_term = search_entry.get()
                    if not search_term:
                        return
                    
                    # Remove previous highlights
                    text_widget.tag_remove('found', '1.0', tk.END)
                    
                    # Search from current position
                    pos = text_widget.search(search_term, search_start_index, tk.END, nocase=True)
                    if pos:
                        # Highlight found text
                        end_pos = f"{pos}+{len(search_term)}c"
                        text_widget.tag_add('found', pos, end_pos)
                        text_widget.tag_config('found', background='yellow', foreground='black')
                        text_widget.see(pos)
                        search_start_index = end_pos
                    else:
                        # Not found or reached end, wrap to beginning
                        search_start_index = '1.0'
                        pos = text_widget.search(search_term, search_start_index, tk.END, nocase=True)
                        if pos:
                            end_pos = f"{pos}+{len(search_term)}c"
                            text_widget.tag_add('found', pos, end_pos)
                            text_widget.tag_config('found', background='yellow', foreground='black')
                            text_widget.see(pos)
                            search_start_index = end_pos
                        else:
                            messagebox.showinfo("Not Found", f"'{search_term}' not found in log.", parent=search_window)
                
                btn_frame = ttk.Frame(search_window)
                btn_frame.pack(pady=20)
                ttk.Button(btn_frame, text="Find Next", command=do_search, width=15).pack(side='left', padx=10)
                ttk.Button(btn_frame, text="Close", command=search_window.destroy, width=15).pack(side='left', padx=10)
                
                # Bind Enter key to search
                search_entry.bind('<Return>', lambda e: do_search())
            
            # Bind Ctrl+F to open search dialog
            text_widget.bind('<Control-f>', find_text)
            log_window.bind('<Control-f>', find_text)
            
            # Add close button
            close_btn = ttk.Button(log_window, text="Close", command=log_window.destroy)
            close_btn.pack(pady=5)
            
            logger.info("Log file opened by user")
            
        except Exception as e:
            log_error(f"Failed to open log file: {str(e)}")
            messagebox.showerror("Error", f"Could not open log file:\n{str(e)}")

    def open_upload_log(self):
        """Open the upload-only log file (monthly)"""
        try:
            if not os.path.exists(UPLOAD_LOG_FILE):
                messagebox.showinfo(
                    "Uploads Log",
                    f"Uploads log not found yet.\n\nIt will be created at:\n{UPLOAD_LOG_FILE}\n\nonce uploads occur."
                )
                return
            
            log_window = tk.Toplevel(self.root)
            log_window.title("Garmin Uploader - Uploads Log")
            
            base_width, base_height = 800, 500
            width = int(base_width * (self.scaling / 1.33))
            height = int(base_height * (self.scaling / 1.33))
            log_window.geometry(f"{width}x{height}")
            
            text_widget = scrolledtext.ScrolledText(
                log_window,
                wrap=tk.WORD,
                font=('Courier New', 9)
            )
            text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            
            with open(UPLOAD_LOG_FILE, 'r', encoding='utf-8') as f:
                log_content = f.read()
                text_widget.insert(1.0, log_content)
            text_widget.see(tk.END)
            
            def block_edit(event):
                if event.state & 0x4:
                    return
                if event.keysym in ('Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Prior', 'Next'):
                    return
                return "break"
            text_widget.bind("<Key>", block_edit)
            
            close_btn = ttk.Button(log_window, text="Close", command=log_window.destroy)
            close_btn.pack(pady=5)
            
            logger.info("Uploads log opened by user")
        except Exception as e:
            log_error(f"Failed to open uploads log file: {str(e)}")
            messagebox.showerror("Error", f"Could not open uploads log file:\n{str(e)}")

def main():
    logger.info(f"=" * 60)
    logger.info(f"Garmin Connect Uploader v{VERSION} - Starting")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"=" * 60)
    
    # Check if started from Windows Startup (minimized)
    import sys
    start_minimized = '--minimized' in sys.argv or '--startup' in sys.argv
    
    root = tk.Tk()
    app = ConnectUploaderGUI(root)
    
    # Auto-start monitoring if both settings are enabled and starting from startup
    if start_minimized:
        logger.info("Started from Windows Startup - checking auto-start settings")
        try:
            # Load config to check if auto-sync should start
            if app.config.get('start_with_windows') and os.path.exists(CONFIG_FILE):
                # Check if we have a valid session (logged in)
                if app.is_logged_in and app.garmin_client:
                    logger.info("Auto-start with valid session - starting monitoring and minimizing to tray")
                    root.after(500, lambda: app.start_monitoring() if not app.is_monitoring else None)
                    root.after(800, lambda: root.withdraw())
                    root.after(1000, lambda: app.create_tray_icon())
                else:
                    # No valid session - keep window open and prompt user to login
                    logger.info("Auto-start without valid session - keeping window open for user login")
                    app.update_status("Please click 'Test & Login' to authenticate with Garmin", "orange")
                    messagebox.showinfo(
                        "Garmin Login Required",
                        "Welcome back!\n\n"
                        "Please click the 'Test & Login' button to authenticate with Garmin Connect.\n\n"
                        "After logging in, the app will auto-start silently on future reboots."
                    )
        except Exception as e:
            logger.error(f"Error during startup auto-start: {str(e)}")
    
    try:
        root.mainloop()
    except Exception as e:
        logger.error(f"Application error: {str(e)}", exc_info=True)
    finally:
        logger.info("Garmin Connect Uploader - Shutting down")
        logger.info(f"=" * 60)

if __name__ == "__main__":
    main()
