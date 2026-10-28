# fire_launcher.py
# FireLauncher v2.5.0 — фикс "танцующих" версий
import customtkinter as ctk
import threading
import os
import subprocess
import requests
import minecraft_launcher_lib
import shutil
import urllib.request
import json
import re
import psutil
import time
import zipfile
import tempfile
import sys
import ctypes
import webbrowser
import math
import hashlib
from io import BytesIO
from PIL import Image
from tkinter import filedialog

# --- Тема ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG_DARK    = "#121212"
SIDEBAR    = "#1e1e1e"
ACCENT     = "#ff5722"
ACCENT_H   = "#e64a19"
TEXT       = "#ffffff"
MUTED      = "#aaaaaa"
SELECT_BG  = "#2c2c2c"
CARD_BG    = "#252525"

DEFAULT_MINECRAFT_DIR = minecraft_launcher_lib.utils.get_minecraft_directory()

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    AUTHLIB_PATH = os.path.join(sys._MEIPASS, "authlib-injector.jar")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    AUTHLIB_PATH = os.path.join(BASE_DIR, "authlib-injector.jar")

ELY_AUTH_URL = "https://authserver.ely.by/auth/authenticate"
ELY_SKIN_URL = "https://authserver.ely.by/api/skins"
ELY_API_ROOT = "ely.by"

CONFIG_FILE = os.path.join(BASE_DIR, "firelauncher_config.json")
TOKEN_FILE = os.path.join(BASE_DIR, "auth_token.dat")
INSTANCES_DIR = os.path.join(BASE_DIR, "instances")

MODRINTH_API = "https://mod.mcimirror.top/modrinth/v2"
MODRINTH_FALLBACK = "https://api.modrinth.com/v2"
GITHUB_REPO = "TangeyPonchik/FireLauncher"

LAUNCHER_CHANGELOG = """
🔥 FireLauncher v2.5.0
- Фикс "танцующих" выпадающих списков версий.
- Инстансы: отдельные папки под каждую сборку.
- Токен Ely.by шифруется через DPAPI (Windows) / base64 (иначе).
- Fallback Modrinth: официальный API, если зеркало недоступно.
- Проверка ZIP-сигнатуры .jar перед сохранением.
- Защита от zip-slip при импорте модпаков.
- Умная починка без удаления папки версии.
- Таймер игры без двойного учёта.
"""

# ---------- Токен: DPAPI / fallback ----------
def _dpapi_encrypt(data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI только на Windows")
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf_in = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf_in, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)

def _dpapi_decrypt(data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI только на Windows")
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf_in = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf_in, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)

_TOKEN_MAGIC = b"FLT1"

def save_token(token: str):
    if not token:
        return
    raw = token.encode("utf-8")
    try:
        if os.name == "nt":
            blob = _TOKEN_MAGIC + b"W" + _dpapi_encrypt(raw)
        else:
            import base64
            blob = _TOKEN_MAGIC + b"P" + base64.b64encode(raw)
    except Exception:
        import base64
        blob = _TOKEN_MAGIC + b"P" + base64.b64encode(raw)
    with open(TOKEN_FILE, "wb") as f:
        f.write(blob)

def load_token() -> str:
    if not os.path.exists(TOKEN_FILE):
        return "0"
    try:
        with open(TOKEN_FILE, "rb") as f:
            blob = f.read()
        if not blob.startswith(_TOKEN_MAGIC):
            return blob.decode("utf-8", errors="ignore").strip() or "0"
        mode = blob[4:5]
        payload = blob[5:]
        if mode == b"W":
            return _dpapi_decrypt(payload).decode("utf-8")
        import base64
        return base64.b64decode(payload).decode("utf-8")
    except Exception:
        return "0"

# ---------- Утилиты ----------
def safe_extract_zip(zf: zipfile.ZipFile, dest: str):
    dest_real = os.path.realpath(dest)
    for member in zf.infolist():
        target = os.path.realpath(os.path.join(dest_real, member.filename))
        if not (target == dest_real or target.startswith(dest_real + os.sep)):
            continue
        zf.extract(member, dest_real)

def looks_like_jar(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"PK\x03\x04"
    except Exception:
        return False

def download_file(url: str, dest: str, timeout: int = 30, expected_sha512: str = None):
    h = hashlib.sha512() if expected_sha512 else None
    r = requests.get(url, stream=True, timeout=timeout,
                     headers={"User-Agent": "FireLauncher/2.5.0"})
    r.raise_for_status()
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            if not chunk:
                continue
            f.write(chunk)
            if h:
                h.update(chunk)
            total += len(chunk)
    if h and expected_sha512 and h.hexdigest().lower() != expected_sha512.lower():
        try:
            os.remove(dest)
        except Exception:
            pass
        raise ValueError("sha512 не совпал")
    return total

class FireLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()

        self.current_version = "2.5.1"
        self.title(f"FireLauncher v{self.current_version}")
        self.geometry("1150x800")
        self.minsize(1050, 700)
        self.configure(fg_color=BG_DARK)

        self.grid_columnconfigure(0, weight=0, minsize=200)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.selected_version = ctk.StringVar(value="")
        self.version_dict = {}
        self.filtered_versions_list = []
        
        # Флаг для фикса "танцующих" версий
        self._dropdown_locked = False

        self.is_installing = False
        self.current_account = None
        self.minecraft_dir = DEFAULT_MINECRAFT_DIR
        self.ram_value = ctk.IntVar(value=4)

        self.game_process = None
        self.is_game_running = False
        self.game_start_time = 0.0
        self.total_play_time = 0.0

        self._progress_target = 0.0
        self._pulse_step = 0

        self.show_releases_var = ctk.BooleanVar(value=True)
        self.show_snapshots_var = ctk.BooleanVar(value=False)
        self.show_modified_var = ctk.BooleanVar(value=True)

        self.frames = {}
        self.avatar_image = None
        self._saved_version = ""
        self._save_timer = None
        self._mod_icons = []
        self._current_frame_name = None
        self._instances = {}

        os.makedirs(INSTANCES_DIR, exist_ok=True)

        self._build_sidebar()
        self._build_frames()
        self._show_frame("play")
        self._update_notes(LAUNCHER_CHANGELOG)

        self._load_instances()
        self._load_config()
        threading.Thread(target=self._load_versions, daemon=True).start()

        self.after(100, self.fade_in)
        self.after(1500, self._check_github_updates)
        self.after(1000, self._pulse_play_button)
        self.after(500, self._tick_ui)

    # ---------- Инстансы ----------
    def _load_instances(self):
        self._instances = {"Default": DEFAULT_MINECRAFT_DIR}
        if os.path.isdir(INSTANCES_DIR):
            for name in os.listdir(INSTANCES_DIR):
                p = os.path.join(INSTANCES_DIR, name)
                if os.path.isdir(p):
                    self._instances[name] = p

    def _current_instance_name(self):
        for n, p in self._instances.items():
            if os.path.realpath(p) == os.path.realpath(self.minecraft_dir):
                return n
        return "Custom"

    def _switch_instance(self, name):
        path = self._instances.get(name)
        if not path:
            return
        self.minecraft_dir = path
        os.makedirs(self.minecraft_dir, exist_ok=True)
        if hasattr(self, "folder_label"):
            self.folder_label.configure(text=self.minecraft_dir)
        if hasattr(self, "instance_menu"):
            self.instance_var.set(name)
        self._save_config()
        self._load_versions()

    def _create_instance(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Новый инстанс")
        dlg.geometry("400x160")
        dlg.configure(fg_color=BG_DARK)
        dlg.grab_set()
        entry = ctk.CTkEntry(dlg, placeholder_text="Имя инстанса", width=340)
        entry.pack(pady=20, padx=20)

        def ok():
            name = entry.get().strip()
            dlg.destroy()
            if not name:
                return
            safe_name = re.sub(r"[^a-zA-Z0-9_\- ]", "", name).strip()
            if not safe_name:
                return
            path = os.path.join(INSTANCES_DIR, safe_name)
            if os.path.exists(path):
                return
            os.makedirs(path, exist_ok=True)
            self._load_instances()
            self._switch_instance(safe_name)

        ctk.CTkButton(dlg, text="Создать", command=ok, fg_color=ACCENT).pack()

    def _delete_instance(self):
        name = self._current_instance_name()
        if name in ("Default", "Custom"):
            return
        path = self._instances.get(name)
        if not path or not os.path.isdir(path):
            return
        if self.is_game_running:
            return
        shutil.rmtree(path, ignore_errors=True)
        self._load_instances()
        self._switch_instance("Default")

    # ---------- Анимации ----------
    def fade_in(self, duration=400):
        try:
            self.update()
            self.deiconify()
            if os.name != "nt":
                self.attributes("-alpha", 1.0)
                return
            self.attributes("-alpha", 0.0)
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            steps = 20
            delay = max(1, duration // steps)

            def step(i=0):
                if i <= steps:
                    p = i / steps
                    alpha = 1 - (1 - p) ** 3
                    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, int(alpha * 255), 2)
                    self.after(delay, lambda: step(i + 1))
                else:
                    self.attributes("-alpha", 1.0)
            step()
        except Exception:
            try:
                self.attributes("-alpha", 1.0)
                self.deiconify()
            except Exception:
                pass

    def _pulse_play_button(self):
        if self.is_game_running or self.is_installing:
            return
        self._pulse_step += 1
        val = (math.sin(self._pulse_step / 10.0) + 1) / 2
        r = int(255 * val + 138 * (1 - val))
        g = int(87 * val + 42 * (1 - val))
        b = int(34 * val + 10 * (1 - val))
        try:
            self.play_btn.configure(fg_color=f"#{r:02x}{g:02x}{b:02x}")
        except Exception:
            pass
        self.after(50, self._pulse_play_button)

    def _animate_progress(self):
        try:
            if not self.progress_bar.winfo_ismapped():
                return
            current = self.progress_bar.get()
            target = self._progress_target
            if abs(current - target) > 0.005:
                self.progress_bar.set(current + (target - current) * 0.15)
                self.after(16, self._animate_progress)
            else:
                self.progress_bar.set(target)
        except Exception:
            pass

    # ---------- UI: sidebar ----------
    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(sidebar, text="🔥 Fire", font=("Segoe UI", 28, "bold"), text_color=ACCENT)\
            .pack(pady=(40, 30), padx=20, anchor="w")

        self._nav_btn(sidebar, "🏠 Играть", lambda: self._show_frame("play"))
        self._nav_btn(sidebar, "📦 Сборки", lambda: self._show_frame("builds"))
        self._nav_btn(sidebar, "🔍 Моды", lambda: self._show_frame("mods"))
        self._nav_btn(sidebar, "👤 Аккаунт", lambda: self._show_frame("account"))
        self._nav_btn(sidebar, "📊 Статистика", lambda: self._show_frame("stats"))
        self._nav_btn(sidebar, "⚙️ Настройки", lambda: self._show_frame("settings"))

        profile_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        profile_frame.pack(side="bottom", fill="x", padx=15, pady=20)

        self.avatar_label = ctk.CTkLabel(profile_frame, text="👤", font=("Segoe UI", 30), width=48, height=48)
        self.avatar_label.pack(side="left", padx=(0, 10))

        text_frame = ctk.CTkFrame(profile_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="both")

        self.user_label = ctk.CTkLabel(text_frame, text="Гость", font=("Segoe UI", 14, "bold"), text_color=TEXT)
        self.user_label.pack(anchor="w")
        ctk.CTkLabel(text_frame, text="Offline / Ely.by", font=("Segoe UI", 11), text_color=MUTED).pack(anchor="w")

    def _nav_btn(self, parent, text, command):
        ctk.CTkButton(parent, text=text, command=command, fg_color="transparent",
                      hover_color=SELECT_BG, text_color=TEXT, anchor="w",
                      font=("Segoe UI", 15), height=40, corner_radius=8)\
            .pack(fill="x", padx=10, pady=4)

    # ---------- UI: frames ----------
    def _build_frames(self):
        self._build_play_frame()
        self._build_builds_frame()
        self._build_mods_frame()
        self._build_account_frame()
        self._build_stats_frame()
        self._build_settings_frame()

    def _build_play_frame(self):
        play_frame = ctk.CTkFrame(self, fg_color="transparent")

        ctk.CTkLabel(play_frame, text="Добро пожаловать в FireLauncher!",
                     font=("Segoe UI", 28, "bold"), text_color=TEXT)\
            .pack(anchor="w", pady=(0, 5))
        self.desc_label = ctk.CTkLabel(play_frame, text="Выберите версию и нажмите Играть.",
                                       font=("Segoe UI", 14), text_color=MUTED)
        self.desc_label.pack(anchor="w", pady=(0, 10))

        notes_frame = ctk.CTkFrame(play_frame, fg_color="#1e1e1e", corner_radius=15)
        notes_frame.pack(fill="both", expand=True, pady=(10, 20))
        notes_top = ctk.CTkFrame(notes_frame, fg_color="transparent")
        notes_top.pack(fill="x", padx=20, pady=(10, 5))
        ctk.CTkLabel(notes_top, text="📜 Что нового", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).pack(side="left")

        self.notes_textbox = ctk.CTkTextbox(notes_frame, fg_color="#121212", text_color=MUTED,
                                            font=("Segoe UI", 13), wrap="word", border_width=0)
        self.notes_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.notes_textbox.configure(state="disabled")

        bottom_frame = ctk.CTkFrame(play_frame, fg_color="#1e1e1e", corner_radius=15, height=100)
        bottom_frame.pack(fill="x", side="bottom", pady=10)
        bottom_frame.pack_propagate(False)

        left_bottom = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        left_bottom.pack(side="left", padx=15, pady=10, fill="y")
        ctk.CTkLabel(left_bottom, text="Версия:", font=("Segoe UI", 12), text_color=MUTED).pack(anchor="w")

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(left_bottom, textvariable=self.search_var,
                                         placeholder_text="Поиск версии", width=150, height=30,
                                         fg_color="#121212", border_width=0)
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_var.trace_add("write", self._filter_search)

        self.version_menu = ctk.CTkOptionMenu(left_bottom, variable=self.selected_version,
                                              values=["Загрузка..."], width=180, height=30,
                                              fg_color="#2c2c2c", button_color=ACCENT,
                                              command=self._on_version_change)
        self.version_menu.pack(side="left")
        
        # === ЛОКИРОВКА МЕНЮ ОТ "ТАНЦЕВ" ===
        def lock_dropdown(event=None):
            self._dropdown_locked = True
            
        def unlock_dropdown(event=None):
            self._dropdown_locked = False
            
        self.version_menu._canvas.bind("<Button-1>", lock_dropdown, add="+")
        self.version_menu._button_canvas.bind("<Button-1>", lock_dropdown, add="+")
        self.version_menu.bind("<Unmap>", unlock_dropdown, add="+")
        self.version_menu.bind("<<ComboboxSelected>>", unlock_dropdown, add="+")

        center_bottom = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        center_bottom.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        self.progress_label = ctk.CTkLabel(center_bottom, text="", font=("Segoe UI", 11), text_color=MUTED)
        self.progress_label.pack(anchor="center", pady=(5, 2))
        self.progress_bar = ctk.CTkProgressBar(center_bottom, width=200, height=10, progress_color=ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.pack(anchor="center")
        self.progress_bar.pack_forget()

        right_bottom = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        right_bottom.pack(side="right", padx=15, pady=15, fill="y")
        self.fix_btn = ctk.CTkButton(right_bottom, text="🔧 Починить", font=("Segoe UI", 14),
                                     fg_color="#333333", hover_color="#444444", width=100, height=40,
                                     corner_radius=10, command=self.repair_game)
        self.fix_btn.pack(side="left", padx=(0, 10))

        self.play_btn = ctk.CTkButton(right_bottom, text="▶ ИГРАТЬ", font=("Segoe UI", 18, "bold"),
                                      fg_color=ACCENT, hover_color=ACCENT_H, width=150, height=50,
                                      corner_radius=10, command=self.start_game)
        self.play_btn.pack(side="left")
        self.frames["play"] = play_frame

    def _build_builds_frame(self):
        build_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(build_frame, text="Сборки и Модлоадеры", font=("Segoe UI", 28, "bold"),
                     text_color=TEXT).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(build_frame, text="Импорт готовой сборки (.mrpack / CurseForge .zip):",
                     font=("Segoe UI", 14), text_color=TEXT).pack(anchor="w", pady=(20, 5))
        ctk.CTkButton(build_frame, text="📂 Выбрать файл сборки", fg_color="#4f8cff",
                      hover_color="#3a75e6", width=200, height=40,
                      command=self._import_modpack).pack(anchor="w", pady=10)

        ctk.CTkLabel(build_frame, text="Установка модлоадеров:", font=("Segoe UI", 14),
                     text_color=TEXT).pack(anchor="w", pady=(20, 5))
        self.build_version_var = ctk.StringVar(value="")
        self.build_version_menu = ctk.CTkOptionMenu(build_frame, variable=self.build_version_var,
                                                    values=["Загрузка..."], width=250, height=35,
                                                    fg_color="#1e1e1e", button_color=ACCENT)
        self.build_version_menu.pack(anchor="w", pady=(5, 20))

        btn_frame = ctk.CTkFrame(build_frame, fg_color="transparent")
        btn_frame.pack(anchor="w", pady=10)
        ctk.CTkButton(btn_frame, text="Установить Fabric", fg_color="#4f8cff", hover_color="#3a75e6",
                      width=160, height=40,
                      command=lambda: self._install_mod_loader("fabric")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Установить Forge", fg_color="#ff5c5c", hover_color="#e64a19",
                      width=160, height=40,
                      command=lambda: self._install_mod_loader("forge")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Удалить", fg_color="#333333", hover_color="#444444",
                      width=100, height=40,
                      command=self._delete_selected_version).pack(side="left")

        self.build_status = ctk.CTkLabel(build_frame, text="", font=("Segoe UI", 12), text_color=MUTED)
        self.build_status.pack(anchor="w", pady=20)
        self.frames["builds"] = build_frame

    def _build_mods_frame(self):
        mods_frame = ctk.CTkFrame(self, fg_color="transparent")

        header_mods = ctk.CTkFrame(mods_frame, fg_color="transparent")
        header_mods.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(header_mods, text="Топ контента", font=("Segoe UI", 28, "bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(header_mods, text="📁 Открыть папку", fg_color="#333333",
                      hover_color="#444444", width=140, height=35,
                      command=self._open_mods_dir).pack(side="right")

        type_frame = ctk.CTkFrame(mods_frame, fg_color="transparent")
        type_frame.pack(fill="x", pady=(0, 10))
        self.content_type_var = ctk.StringVar(value="mods")
        ctk.CTkRadioButton(type_frame, text="Моды", variable=self.content_type_var,
                           value="mods", command=self._search_mods, fg_color=ACCENT).pack(side="left", padx=(0, 15))
        ctk.CTkRadioButton(type_frame, text="Шейдеры", variable=self.content_type_var,
                           value="shaders", command=self._search_mods, fg_color=ACCENT).pack(side="left", padx=(0, 15))
        ctk.CTkRadioButton(type_frame, text="Ресурспаки", variable=self.content_type_var,
                           value="resourcepacks", command=self._search_mods, fg_color=ACCENT).pack(side="left")

        search_frame = ctk.CTkFrame(mods_frame, fg_color="transparent")
        search_frame.pack(fill="x", pady=(0, 15))
        self.mod_search_entry = ctk.CTkEntry(search_frame, placeholder_text="Поиск (пусто = Топ)",
                                             width=400, height=40, fg_color="#1e1e1e")
        self.mod_search_entry.pack(side="left", padx=(0, 10))
        self.mod_search_entry.bind("<Return>", lambda e: self._search_mods())
        ctk.CTkButton(search_frame, text="Найти", fg_color=ACCENT, hover_color=ACCENT_H,
                      width=100, height=40, command=self._search_mods).pack(side="left")

        self.mods_scroll = ctk.CTkScrollableFrame(mods_frame, fg_color="transparent")
        self.mods_scroll.pack(fill="both", expand=True)
        self.frames["mods"] = mods_frame

    def _build_account_frame(self):
        acc_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(acc_frame, text="Аккаунт Ely.by", font=("Segoe UI", 28, "bold"),
                     text_color=TEXT).pack(anchor="w", pady=(0, 5))

        self.ely_user = ctk.CTkEntry(acc_frame, placeholder_text="Email или ник",
                                     width=300, height=40, fg_color="#1e1e1e")
        self.ely_user.pack(anchor="w", pady=5)
        self.ely_pass = ctk.CTkEntry(acc_frame, placeholder_text="Пароль", width=300, height=40,
                                     fg_color="#1e1e1e", show="*")
        self.ely_pass.pack(anchor="w", pady=5)

        btn_acc = ctk.CTkFrame(acc_frame, fg_color="transparent")
        btn_acc.pack(anchor="w", pady=15)
        ctk.CTkButton(btn_acc, text="Войти", fg_color=ACCENT, hover_color=ACCENT_H, height=40,
                      command=self.ely_login).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_acc, text="🎨 Сменить скин", fg_color="#4f8cff", hover_color="#3a75e6",
                      height=40, command=self._change_skin).pack(side="left")

        self.acc_status = ctk.CTkLabel(acc_frame, text="", font=("Segoe UI", 12), text_color=MUTED)
        self.acc_status.pack(anchor="w")
        self.frames["account"] = acc_frame

    def _build_stats_frame(self):
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(stats_frame, text="Статистика", font=("Segoe UI", 28, "bold"),
                     text_color=TEXT).pack(anchor="w", pady=(0, 20))

        self.play_time_lbl = ctk.CTkLabel(stats_frame, text="⏱️ Время в игре: 0 ч 0 мин",
                                          font=("Segoe UI", 18), text_color=TEXT)
        self.play_time_lbl.pack(anchor="w", pady=(0, 20))

        self.cpu_label = ctk.CTkLabel(stats_frame, text="CPU: 0%", font=("Segoe UI", 18), text_color=TEXT)
        self.cpu_label.pack(anchor="w", pady=5)
        self.cpu_bar = ctk.CTkProgressBar(stats_frame, width=400, height=15, progress_color=ACCENT)
        self.cpu_bar.set(0)
        self.cpu_bar.pack(anchor="w", pady=(0, 20))

        self.ram_usage_label = ctk.CTkLabel(stats_frame, text="RAM: 0%", font=("Segoe UI", 18), text_color=TEXT)
        self.ram_usage_label.pack(anchor="w", pady=5)
        self.ram_usage_bar = ctk.CTkProgressBar(stats_frame, width=400, height=15, progress_color="#4f8cff")
        self.ram_usage_bar.set(0)
        self.ram_usage_bar.pack(anchor="w", pady=(0, 20))
        self.frames["stats"] = stats_frame

    def _build_settings_frame(self):
        settings_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(settings_frame, text="Настройки", font=("Segoe UI", 28, "bold"),
                     text_color=TEXT).pack(anchor="w", pady=(0, 30))

        ctk.CTkLabel(settings_frame, text="Инстанс:", font=("Segoe UI", 14),
                     text_color=TEXT).pack(anchor="w", pady=(0, 5))
        inst_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        inst_frame.pack(anchor="w", pady=5)
        self.instance_var = ctk.StringVar(value="Default")
        self.instance_menu = ctk.CTkOptionMenu(inst_frame, variable=self.instance_var,
                                               values=list(self._instances.keys()) or ["Default"],
                                               width=250, height=35, fg_color="#1e1e1e",
                                               button_color=ACCENT, command=self._switch_instance)
        self.instance_menu.pack(side="left", padx=(0, 10))
        ctk.CTkButton(inst_frame, text="+ Новый", fg_color="#4f8cff", hover_color="#3a75e6",
                      width=100, height=35, command=self._create_instance).pack(side="left", padx=(0, 10))
        ctk.CTkButton(inst_frame, text="Удалить", fg_color="#333333", hover_color="#444444",
                      width=100, height=35, command=self._delete_instance).pack(side="left")

        ctk.CTkLabel(settings_frame, text="Какие версии показывать:", font=("Segoe UI", 14),
                     text_color=TEXT).pack(anchor="w", pady=(20, 5))
        filter_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        filter_frame.pack(anchor="w", pady=5)
        ctk.CTkCheckBox(filter_frame, text="Релизы", variable=self.show_releases_var,
                        command=self._apply_filters, fg_color=ACCENT).pack(side="left", padx=(0, 20))
        ctk.CTkCheckBox(filter_frame, text="Снапшоты", variable=self.show_snapshots_var,
                        command=self._apply_filters, fg_color=ACCENT).pack(side="left", padx=(0, 20))
        ctk.CTkCheckBox(filter_frame, text="Модифицированные", variable=self.show_modified_var,
                        command=self._apply_filters, fg_color=ACCENT).pack(side="left")

        ctk.CTkLabel(settings_frame, text="Выделяемая память (ОЗУ):", font=("Segoe UI", 14),
                     text_color=TEXT).pack(anchor="w", pady=(20, 5))
        self.ram_slider = ctk.CTkSlider(settings_frame, from_=2, to=16, number_of_steps=14,
                                        command=self._update_ram_label)
        self.ram_slider.pack(anchor="w", pady=5)
        self.ram_slider.set(4)
        self.ram_label = ctk.CTkLabel(settings_frame, text="4 ГБ", font=("Segoe UI", 12), text_color=MUTED)
        self.ram_label.pack(anchor="w")

        ctk.CTkLabel(settings_frame, text="Дополнительные JVM-аргументы:", font=("Segoe UI", 14),
                     text_color=TEXT).pack(anchor="w", pady=(20, 5))
        self.jvm_args_entry = ctk.CTkEntry(settings_frame, placeholder_text="-XX:+UseG1GC",
                                           width=500, height=35, fg_color="#1e1e1e")
        self.jvm_args_entry.pack(anchor="w", pady=5)

        ctk.CTkLabel(settings_frame, text="Папка с игрой:", font=("Segoe UI", 14),
                     text_color=TEXT).pack(anchor="w", pady=(20, 5))
        self.folder_label = ctk.CTkLabel(settings_frame, text=self.minecraft_dir,
                                         font=("Segoe UI", 11), text_color=MUTED, wraplength=500)
        self.folder_label.pack(anchor="w", pady=5)
        folder_btn_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        folder_btn_frame.pack(anchor="w", pady=10)
        ctk.CTkButton(folder_btn_frame, text="Выбрать", fg_color="#4f8cff", hover_color="#3a75e6",
                      command=self._choose_minecraft_dir).pack(side="left", padx=(0, 10))
        ctk.CTkButton(folder_btn_frame, text="Открыть", fg_color="#333333", hover_color="#444444",
                      command=self._open_minecraft_dir).pack(side="left")
        self.frames["settings"] = settings_frame

    # ---------- Навигация ----------
    def _show_frame(self, name):
        for frame in self.frames.values():
            frame.grid_forget()
        self.frames[name].grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        self._current_frame_name = name
        if name == "mods" and not getattr(self, "_mods_loaded", False):
            self._mods_loaded = True
            self.after(200, self._search_mods)

    # ---------- Единый tick ----------
    def _tick_ui(self):
        try:
            shown = self.total_play_time
            if self.is_game_running and self.game_start_time > 0:
                shown += time.time() - self.game_start_time
            h = int(shown // 3600)
            m = int((shown % 3600) // 60)
            if hasattr(self, "play_time_lbl"):
                self.play_time_lbl.configure(text=f"⏱️ Время в игре: {h} ч {m} мин")

            if self._current_frame_name == "stats":
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                self.cpu_label.configure(text=f"CPU: {cpu}%")
                self.cpu_bar.set(cpu / 100)
                self.ram_usage_label.configure(text=f"RAM: {ram}%")
                self.ram_usage_bar.set(ram / 100)
        except Exception:
            pass
        self.after(1000, self._tick_ui)

    # ---------- Версии ----------
    def _filter_search(self, *args):
        query = self.search_var.get().lower()
        if not query:
            self.version_menu.configure(values=self.filtered_versions_list or ["Загрузка..."])
            return
        filtered = [v for v in self.filtered_versions_list if query in v.lower()]
        self.version_menu.configure(values=filtered or ["Ничего не найдено"])

    def _on_version_change(self, choice):
        if not choice or choice not in self.version_dict:
            self.play_btn.configure(state="disabled")
        else:
            self.play_btn.configure(state="normal")
        self._save_config()

    def _load_versions(self):
        try:
            versions = minecraft_launcher_lib.utils.get_version_list()
            self.version_dict = {}
            for v in versions:
                if v["type"] == "release":
                    self.version_dict[v["id"]] = v["id"]
                elif v["type"] == "snapshot":
                    self.version_dict[f"{v['id']} (Snapshot)"] = v["id"]

            local_dir = os.path.join(self.minecraft_dir, "versions")
            if os.path.exists(local_dir):
                for folder in os.listdir(local_dir):
                    if any(x in folder.lower() for x in ("fabric", "forge", "quilt")):
                        json_path = os.path.join(local_dir, folder, f"{folder}.json")
                        if os.path.exists(json_path) and folder not in self.version_dict.values():
                            self.version_dict[folder] = folder

            if not self.version_dict:
                self.after(0, lambda: self.desc_label.configure(
                    text="Не удалось загрузить список версий (сеть?)", text_color="#ff5c5c"))
                return

            self._apply_filters()
            if self._saved_version and self._saved_version in self.filtered_versions_list:
                self.after(0, lambda: self.selected_version.set(self._saved_version))
        except Exception as e:
            err = str(e) or "Неизвестная ошибка"
            self.after(0, lambda: self.desc_label.configure(
                text=f"Ошибка версий: {err}", text_color="#ff5c5c"))

    def _apply_filters(self):
        show_rel = self.show_releases_var.get()
        show_snap = self.show_snapshots_var.get()
        show_mod = self.show_modified_var.get()

        if not (show_rel or show_snap or show_mod):
            self.show_releases_var.set(True)
            show_rel = True

        new_list = []
        for display, real_id in self.version_dict.items():
            is_snap = "Snapshot" in display
            is_mod = any(x in real_id.lower() for x in ("fabric", "forge", "quilt"))
            is_rel = not is_snap and not is_mod
            if (is_rel and show_rel) or (is_snap and show_snap) or (is_mod and show_mod):
                new_list.append(display)

        if not new_list:
            return

        if new_list == self.filtered_versions_list:
            return
            
        self.filtered_versions_list = new_list

        if not self._dropdown_locked:
            self.version_menu.configure(values=self.filtered_versions_list)
            if hasattr(self, "build_version_menu"):
                self.build_version_menu.configure(values=self.filtered_versions_list)

        cur = self.selected_version.get()
        if cur not in self.filtered_versions_list:
            self.selected_version.set(self.filtered_versions_list[0])

        if hasattr(self, "build_version_var"):
            cur_b = self.build_version_var.get()
            if cur_b not in self.filtered_versions_list:
                self.build_version_var.set(self.filtered_versions_list[0])

    # ---------- Настройки / конфиг ----------
    def _update_ram_label(self, value):
        self.ram_value.set(int(value))
        self.ram_label.configure(text=f"{int(value)} ГБ")
        if self._save_timer:
            try:
                self.after_cancel(self._save_timer)
            except Exception:
                pass
        self._save_timer = self.after(1000, self._save_config)

    def _choose_minecraft_dir(self):
        path = filedialog.askdirectory(initialdir=self.minecraft_dir)
        if path:
            self.minecraft_dir = path
            self.folder_label.configure(text=self.minecraft_dir)
            if hasattr(self, "instance_var"):
                self.instance_var.set(self._current_instance_name())
            self._save_config()
            self._load_versions()

    def _open_minecraft_dir(self):
        try:
            if os.name == "nt":
                os.startfile(self.minecraft_dir)
            else:
                subprocess.Popen(["xdg-open", self.minecraft_dir])
        except Exception:
            pass

    def _save_config(self):
        config = {
            "version": self.selected_version.get(),
            "minecraft_dir": self.minecraft_dir,
            "ram": self.ram_value.get(),
            "jvm_args": self.jvm_args_entry.get().strip() if hasattr(self, "jvm_args_entry") else "",
            "username": self.current_account["username"] if self.current_account else None,
            "uuid": self.current_account["uuid"] if self.current_account else None,
            "show_releases": self.show_releases_var.get(),
            "show_snapshots": self.show_snapshots_var.get(),
            "show_modified": self.show_modified_var.get(),
            "total_play_time": self.total_play_time,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            if self.current_account and self.current_account.get("token"):
                save_token(self.current_account["token"])
        except Exception:
            pass

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)

            if config.get("username"):
                self.current_account = {
                    "username": config["username"],
                    "uuid": config.get("uuid", ""),
                    "token": load_token(),
                }
                self.after(0, lambda: self.user_label.configure(text=self.current_account["username"]))
                self._download_avatar(self.current_account["username"])

            if config.get("minecraft_dir"):
                self.minecraft_dir = config["minecraft_dir"]
                self.folder_label.configure(text=self.minecraft_dir)
                if hasattr(self, "instance_var"):
                    self.instance_var.set(self._current_instance_name())

            if config.get("ram"):
                self.ram_value.set(config["ram"])
                self.ram_slider.set(config["ram"])
                self.ram_label.configure(text=f"{config['ram']} ГБ")

            if config.get("jvm_args") and hasattr(self, "jvm_args_entry"):
                self.jvm_args_entry.delete(0, "end")
                self.jvm_args_entry.insert(0, config["jvm_args"])

            self.show_releases_var.set(config.get("show_releases", True))
            self.show_snapshots_var.set(config.get("show_snapshots", False))
            self.show_modified_var.set(config.get("show_modified", True))

            self.total_play_time = float(config.get("total_play_time", 0) or 0)
            self._saved_version = config.get("version", "")
        except Exception:
            pass

    # ---------- Аккаунт Ely.by ----------
    def ely_login(self):
        username = self.ely_user.get().strip()
        password = self.ely_pass.get().strip()
        if not username or not password:
            self.acc_status.configure(text="Заполни логин и пароль", text_color="#ff5c5c")
            return
        self.acc_status.configure(text="Вход...", text_color=MUTED)
        threading.Thread(target=self._ely_login_thread, args=(username, password), daemon=True).start()

    def _ely_login_thread(self, username, password):
        try:
            r = requests.post(ELY_AUTH_URL, json={
                "username": username, "password": password,
                "clientToken": "firelauncher", "requestUser": True,
            }, timeout=15)
            if r.status_code == 200:
                data = r.json()
                profile = data.get("selectedProfile", {}) or {}
                self.current_account = {
                    "username": profile.get("name", username),
                    "uuid": profile.get("id", ""),
                    "token": data.get("accessToken", "0"),
                }
                self.after(0, lambda: self.user_label.configure(text=self.current_account["username"]))
                self.after(0, lambda: self.acc_status.configure(text="Успешный вход!", text_color="#3ddc84"))
                self._download_avatar(self.current_account["username"])
                self._save_config()
                self.after(0, lambda: self._show_frame("play"))
            else:
                try:
                    err = r.json().get("errorMessage", "Неверный логин")
                except Exception:
                    err = f"HTTP {r.status_code}"
                self.after(0, lambda: self.acc_status.configure(text=err, text_color="#ff5c5c"))
        except Exception as e:
            self.after(0, lambda: self.acc_status.configure(text=f"Ошибка: {e}", text_color="#ff5c5c"))

    def _download_avatar(self, nickname):
        def fetch():
            try:
                req = urllib.request.Request(
                    f"http://skinsystem.ely.by/skins/{nickname}.png",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = resp.read(2 * 1024 * 1024)
                img = Image.open(BytesIO(data))
                head = img.crop((8, 8, 16, 16)).resize((64, 64), Image.Resampling.NEAREST)
                ctk_img = ctk.CTkImage(light_image=head, dark_image=head, size=(48, 48))
                self.avatar_image = ctk_img
                self.after(0, lambda: self.avatar_label.configure(image=ctk_img, text=""))
            except Exception:
                pass
        threading.Thread(target=fetch, daemon=True).start()

    def _change_skin(self):
        if not self.current_account:
            self.acc_status.configure(text="Сначала войдите в аккаунт!", text_color="#ff5c5c")
            return
        path = filedialog.askopenfilename(title="Выберите скин (PNG 64x64)",
                                          filetypes=[("PNG", "*.png")])
        if not path:
            return
        self.acc_status.configure(text="Загрузка скина...", text_color=MUTED)

        def upload():
            try:
                with open(path, "rb") as f:
                    files = {"skin": f}
                    headers = {"Authorization": f"Bearer {self.current_account['token']}"}
                    r = requests.post(f"{ELY_SKIN_URL}/{self.current_account['uuid']}",
                                      headers=headers, files=files, timeout=30)
                if r.status_code == 200:
                    self.after(0, lambda: self.acc_status.configure(text="Скин обновлён!", text_color="#3ddc84"))
                    self._download_avatar(self.current_account["username"])
                else:
                    self.after(0, lambda: self.acc_status.configure(text=f"Ошибка: {r.status_code}", text_color="#ff5c5c"))
            except Exception as e:
                self.after(0, lambda: self.acc_status.configure(text=f"Ошибка: {e}", text_color="#ff5c5c"))
        threading.Thread(target=upload, daemon=True).start()

    # ---------- Модпаки / лоадеры ----------
    def _import_modpack(self):
        path = filedialog.askopenfilename(title="Выберите сборку",
                                          filetypes=[("Modpacks", "*.mrpack *.zip")])
        if not path:
            return
        self.build_status.configure(text=f"Импорт {os.path.basename(path)}...", text_color=MUTED)

        def import_thread():
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    with zipfile.ZipFile(path, "r") as z:
                        safe_extract_zip(z, temp_dir)

                    if path.endswith(".mrpack"):
                        manifest_path = os.path.join(temp_dir, "modrinth.index.json")
                        if not os.path.exists(manifest_path):
                            raise Exception("Не найден modrinth.index.json")
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = json.load(f)

                        deps = manifest.get("dependencies", {})
                        game_ver = deps.get("minecraft")
                        if not game_ver:
                            raise Exception("В манифесте нет версии Minecraft")
                        loader = "fabric" if "fabric-loader" in deps else ("forge" if "forge" in deps else None)

                        self.after(0, lambda: self.build_status.configure(text="Скачивание игры и модлоадера..."))
                        minecraft_launcher_lib.install.install_minecraft_version(game_ver, self.minecraft_dir)
                        if loader == "fabric":
                            minecraft_launcher_lib.mod_loader.get_mod_loader("fabric").install(game_ver, self.minecraft_dir)
                        elif loader == "forge":
                            minecraft_launcher_lib.mod_loader.get_mod_loader("forge").install(game_ver, self.minecraft_dir)

                        self.after(0, lambda: self.build_status.configure(text="Скачивание контента..."))
                        mods_dir = os.path.join(self.minecraft_dir, "mods")
                        os.makedirs(mods_dir, exist_ok=True)
                        for file_info in manifest.get("files", []):
                            downloads = file_info.get("downloads") or []
                            if not downloads:
                                continue
                            url = downloads[0]
                            filename = os.path.basename(file_info.get("path", "")) or "mod.jar"
                            dest = os.path.join(mods_dir, filename)
                            try:
                                download_file(url, dest, expected_sha512=file_info.get("hashes", {}).get("sha512"))
                            except Exception as e:
                                print(f"[modpack] {filename}: {e}")

                    elif path.endswith(".zip"):
                        manifest_path = os.path.join(temp_dir, "manifest.json")
                        if os.path.exists(manifest_path):
                            overrides = os.path.join(temp_dir, "overrides")
                            if os.path.exists(overrides):
                                shutil.copytree(overrides, self.minecraft_dir, dirs_exist_ok=True)
                            self.after(0, lambda: self.build_status.configure(
                                text="CurseForge сборка импортирована", text_color="#3ddc84"))
                        else:
                            mods_dir = os.path.join(self.minecraft_dir, "mods")
                            os.makedirs(mods_dir, exist_ok=True)
                            for root, _, files in os.walk(temp_dir):
                                for file in files:
                                    if file.endswith(".jar"):
                                        shutil.copy(os.path.join(root, file),
                                                    os.path.join(mods_dir, file))
                            self.after(0, lambda: self.build_status.configure(
                                text="Моды из ZIP скопированы!", text_color="#3ddc84"))

                self.after(0, lambda: self.build_status.configure(text="Импорт завершён!", text_color="#3ddc84"))
                self.after(0, self._load_versions)
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self.build_status.configure(text=f"Ошибка: {msg}", text_color="#ff5c5c"))

        threading.Thread(target=import_thread, daemon=True).start()

    def _install_mod_loader(self, loader_type):
        ver = self.version_dict.get(self.build_version_var.get(), "")
        if not ver:
            self.build_status.configure(text="Выберите версию!", text_color="#ff5c5c")
            return
        self.build_status.configure(text=f"Установка {loader_type}...", text_color=MUTED)

        def install():
            try:
                if loader_type == "fabric":
                    minecraft_launcher_lib.mod_loader.get_mod_loader("fabric").install(ver, self.minecraft_dir)
                elif loader_type == "forge":
                    minecraft_launcher_lib.mod_loader.get_mod_loader("forge").install(ver, self.minecraft_dir)
                self.after(0, lambda: self.build_status.configure(text="Установлено!", text_color="#3ddc84"))
                self.after(0, self._load_versions)
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self.build_status.configure(text=f"Ошибка: {msg}", text_color="#ff5c5c"))
        threading.Thread(target=install, daemon=True).start()

    def _delete_selected_version(self):
        ver = self.version_dict.get(self.build_version_var.get(), "")
        if not ver or not any(x in ver.lower() for x in ("fabric", "forge", "quilt")):
            self.build_status.configure(text="Выберите модлоадер!", text_color="#ff5c5c")
            return
        path = os.path.join(self.minecraft_dir, "versions", ver)
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            self.build_status.configure(text="Удалено!", text_color="#3ddc84")
            self._load_versions()

    # ---------- Моды (Modrinth) ----------
    def _open_mods_dir(self):
        ct = self.content_type_var.get()
        folder = "mods" if ct == "mods" else ("shaderpacks" if ct == "shaders" else "resourcepacks")
        dest = os.path.join(self.minecraft_dir, folder)
        os.makedirs(dest, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(dest)
            else:
                subprocess.Popen(["xdg-open", dest])
        except Exception:
            pass

    def _search_mods(self):
        query = self.mod_search_entry.get().strip()
        content_type = self.content_type_var.get()

        for w in self.mods_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.mods_scroll, text="Загрузка...", text_color=MUTED).pack(pady=20)

        def fetch():
            data = None
            for base in (MODRINTH_API, MODRINTH_FALLBACK):
                try:
                    facet = f'[["project_type:{content_type}"]]'
                    url = f"{base}/search?query={query}&limit=15&facets={facet}&index=downloads"
                    r = requests.get(url, headers={"User-Agent": "FireLauncher/2.5.0"}, timeout=15)
                    r.raise_for_status()
                    data = r.json()
                    break
                except Exception as e:
                    print(f"[modrinth] {base}: {e}")
                    continue

            for w in self.mods_scroll.winfo_children():
                w.destroy()

            if data is None:
                self.after(0, lambda: ctk.CTkLabel(self.mods_scroll,
                                                  text="Не удалось получить список (сеть/зеркало)",
                                                  text_color="#ff5c5c").pack(pady=20))
                return
            self.after(0, lambda: self._display_mods(data.get("hits", [])))

        threading.Thread(target=fetch, daemon=True).start()

    def _display_mods(self, mods):
        if not mods:
            ctk.CTkLabel(self.mods_scroll, text="Ничего не найдено", text_color=MUTED).pack(pady=20)
            return
        for mod in mods:
            card = ctk.CTkFrame(self.mods_scroll, fg_color=CARD_BG, corner_radius=10, height=80)
            card.pack(fill="x", pady=5, padx=5)
            card.pack_propagate(False)

            icon_label = ctk.CTkLabel(card, text="", width=60, height=60)
            icon_label.pack(side="left", padx=10, pady=10)
            if mod.get("icon_url"):
                self._load_mod_icon(mod["icon_url"], card, icon_label)

            text_frame = ctk.CTkFrame(card, fg_color="transparent")
            text_frame.pack(side="left", fill="both", expand=True, pady=10)
            ctk.CTkLabel(text_frame, text=mod.get("title", ""), font=("Segoe UI", 14, "bold"),
                         text_color=TEXT, anchor="w").pack(anchor="w")

            downloads = mod.get("downloads", 0) or 0
            dl_text = f"{downloads/1_000_000:.1f}M" if downloads > 1_000_000 else f"{downloads/1000:.0f}K"
            desc = (mod.get("description", "") or "")[:60]
            ctk.CTkLabel(text_frame, text=f"📥 {dl_text} | {desc}...",
                         font=("Segoe UI", 11), text_color=MUTED, anchor="w").pack(anchor="w")

            slug = mod.get("slug", "")
            ctk.CTkButton(card, text="Скачать", width=100, height=32, fg_color=ACCENT,
                          command=lambda s=slug, t=self.content_type_var.get(): self._download_mod(s, t))\
                .pack(side="right", padx=15)

    def _load_mod_icon(self, url, card, label):
        def fetch():
            try:
                r = requests.get(url, timeout=8, headers={"User-Agent": "FireLauncher/2.5.0"})
                r.raise_for_status()
                if len(r.content) > 2 * 1024 * 1024:
                    return
                img = Image.open(BytesIO(r.content))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(48, 48))
                self._mod_icons.append(ctk_img)
                self.after(0, lambda: label.configure(image=ctk_img))
            except Exception:
                pass
        threading.Thread(target=fetch, daemon=True).start()

    def _download_mod(self, slug, content_type):
        def fetch():
            try:
                ver = self.version_dict.get(self.selected_version.get(), "")

                loader = None
                if content_type == "mods":
                    lv = ver.lower()
                    loader = "fabric" if "fabric" in lv else ("forge" if "forge" in lv else None)

                match = re.search(r"(\d+\.\d+(?:\.\d+)?)", ver)
                game_ver = match.group(1) if match else None

                params = {}
                if game_ver and content_type == "mods":
                    params["game_versions"] = json.dumps([game_ver])
                if loader:
                    params["loaders"] = json.dumps([loader])

                versions = None
                for base in (MODRINTH_API, MODRINTH_FALLBACK):
                    try:
                        r = requests.get(f"{base}/project/{slug}/version", params=params,
                                         headers={"User-Agent": "FireLauncher/2.5.0"}, timeout=15)
                        r.raise_for_status()
                        versions = r.json()
                        break
                    except Exception as e:
                        print(f"[modrinth dl] {base}: {e}")
                        continue

                if not versions:
                    self.after(0, lambda: self._show_toast("Нет версий под эту сборку!"))
                    return

                files = versions[0].get("files", [])
                if not files:
                    self.after(0, lambda: self._show_toast("У версии нет файлов"))
                    return
                f0 = files[0]
                download_url = f0.get("url")
                filename = f0.get("filename") or f"{slug}.jar"
                expected = (f0.get("hashes") or {}).get("sha512")

                folder = "mods" if content_type == "mods" else ("shaderpacks" if content_type == "shaders" else "resourcepacks")
                dest_dir = os.path.join(self.minecraft_dir, folder)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, filename)

                download_file(download_url, dest, expected_sha512=expected)

                if filename.endswith(".jar") and not looks_like_jar(dest):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                    self.after(0, lambda: self._show_toast("Скачанный .jar битый"))
                    return

                self.after(0, lambda: self._show_toast(f"{filename} скачан!"))
            except Exception as e:
                print(f"[mod download] {e}")
                self.after(0, lambda: self._show_toast("Ошибка скачивания"))
        threading.Thread(target=fetch, daemon=True).start()

    def _show_toast(self, text):
        base_title = f"FireLauncher v{self.current_version}"
        self.title(f"{base_title} — {text}")
        self.after(3000, lambda: self.title(base_title))

    # ---------- Починка ----------
    def repair_game(self):
        ver = self.version_dict.get(self.selected_version.get(), "")
        if not ver:
            return
        self.desc_label.configure(text=f"Починка {ver}...", text_color=MUTED)

        def work():
            removed_mods = 0
            mods_dir = os.path.join(self.minecraft_dir, "mods")
            if os.path.exists(mods_dir):
                for f in os.listdir(mods_dir):
                    if not f.endswith(".jar"):
                        continue
                    p = os.path.join(mods_dir, f)
                    try:
                        if os.path.getsize(p) < 1024 or not looks_like_jar(p):
                            os.remove(p)
                            removed_mods += 1
                    except Exception:
                        pass

            try:
                minecraft_launcher_lib.install.install_minecraft_version(ver, self.minecraft_dir)
                ok = True
            except Exception as e:
                print(f"[repair] {e}")
                ok = False

            def done():
                if ok:
                    self.desc_label.configure(
                        text=f"Готово. Битых модов удалено: {removed_mods}. Нажми Играть.",
                        text_color=MUTED)
                else:
                    self.desc_label.configure(
                        text=f"Не удалось переустановить версию. Удалено модов: {removed_mods}",
                        text_color="#ff5c5c")
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    # ---------- Запуск игры ----------
    def _update_progress(self, current, total=None):
        if total and total > 0:
            self._progress_target = current / total
            if not getattr(self, "_progress_animating", False):
                self._progress_animating = True
                self._animate_progress()

    def _run_game_logic(self):
        try:
            ver = self.version_dict.get(self.selected_version.get(), "")
            if not ver:
                raise ValueError("Версия не выбрана")

            self.after(0, lambda: self.progress_label.pack(anchor="center"))
            self.after(0, lambda: self.progress_bar.pack(anchor="center"))
            self.after(0, lambda: self.play_btn.configure(text="Установка...", state="disabled"))
            self.is_installing = True

            def safe_status(t):
                self.after(0, lambda: self.progress_label.configure(text=t))

            callback = {
                "setStatus": safe_status,
                "setProgress": self._update_progress,
                "setMax": lambda m: None,
            }
            minecraft_launcher_lib.install.install_minecraft_version(ver, self.minecraft_dir, callback=callback)

            jvm_args = [f"-Xmx{self.ram_value.get()}G", "-Xms2G"]
            extra = self.jvm_args_entry.get().strip() if hasattr(self, "jvm_args_entry") else ""
            if extra:
                jvm_args.extend(extra.split())

            if self.current_account:
                options = {
                    "username": self.current_account["username"],
                    "uuid": self.current_account["uuid"],
                    "token": self.current_account["token"],
                    "jvmArguments": jvm_args,
                }
            else:
                options = minecraft_launcher_lib.utils.generate_test_options()
                options["jvmArguments"] = jvm_args

            command = minecraft_launcher_lib.command.get_minecraft_command(ver, self.minecraft_dir, options)

            if self.current_account and os.path.exists(AUTHLIB_PATH):
                command.insert(1, f"-javaagent:{AUTHLIB_PATH}={ELY_API_ROOT}")

            self.after(0, lambda: self.desc_label.configure(text="Запуск..."))
            log_dir = os.path.join(self.minecraft_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "launcher_last.log")
            log_file = open(log_path, "w", encoding="utf-8", errors="replace")
            self.game_process = subprocess.Popen(command, cwd=self.minecraft_dir,
                                                 stdout=log_file, stderr=log_file)

            started = False
            deadline = time.time() + 10
            while time.time() < deadline:
                if self.game_process.poll() is not None:
                    break
                started = True
                break
            if self.game_process.poll() is None:
                started = True

            if started and self.game_process.poll() is None:
                self.is_game_running = True
                self.game_start_time = time.time()
                self.after(0, lambda: self.play_btn.configure(
                    text="⏹ ЗАКРЫТЬ", fg_color="#ff5c5c", hover_color="#e64a19", state="normal"))
                self.after(0, lambda: self.desc_label.configure(text="Игра запущена!", text_color="#3ddc84"))
                self._watch_game_process()
            else:
                self.after(0, lambda: self.desc_label.configure(
                    text="Игра вылетела при запуске (смотри logs/launcher_last.log)",
                    text_color="#ff5c5c"))
                self.after(0, lambda: self.play_btn.configure(
                    text="▶ ИГРАТЬ", fg_color=ACCENT, hover_color=ACCENT_H, state="normal"))
                self.is_installing = False
                self._pulse_play_button()
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self.desc_label.configure(text=f"Ошибка: {msg}", text_color="#ff5c5c"))
            self.after(0, lambda: self.play_btn.configure(
                text="▶ ИГРАТЬ", fg_color=ACCENT, hover_color=ACCENT_H, state="normal"))
            self.is_installing = False
            self._pulse_play_button()
        finally:
            self.after(0, lambda: self.progress_bar.pack_forget())
            self.after(0, lambda: self.progress_label.pack_forget())

    def _watch_game_process(self):
        def watch():
            try:
                if self.game_process:
                    self.game_process.wait()
            except Exception:
                pass
            if self.game_start_time > 0:
                self.total_play_time += time.time() - self.game_start_time
                self.game_start_time = 0.0
            self.is_game_running = False
            self.is_installing = False
            self.after(0, lambda: self.play_btn.configure(
                text="▶ ИГРАТЬ", fg_color=ACCENT, hover_color=ACCENT_H, state="normal"))
            self.after(0, lambda: self.desc_label.configure(text="Игра закрыта.", text_color=MUTED))
            self.after(0, self._save_config)
            self._pulse_play_button()
        threading.Thread(target=watch, daemon=True).start()

    def start_game(self):
        if self.is_installing:
            return
        if self.is_game_running:
            if self.game_process:
                try:
                    self.game_process.terminate()

                    def kill_if_alive():
                        try:
                            if self.game_process and self.game_process.poll() is None:
                                self.game_process.kill()
                        except Exception:
                            pass
                    self.after(5000, kill_if_alive)
                except Exception:
                    pass
                self.desc_label.configure(text="Завершение игры...")
            return
        self.is_installing = True
        threading.Thread(target=self._run_game_logic, daemon=True).start()

    # ---------- Обновления ----------
    def _check_github_updates(self):
        def fetch():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                r = requests.get(url, headers={"User-Agent": "FireLauncher/2.5.0"}, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    latest = data.get("tag_name", "").replace("v", "")
                    if latest and latest != self.current_version:
                        body = data.get("body", "Нет описания.") or "Нет описания."
                        if len(body) > 500:
                            body = body[:500] + "..."
                        self.after(0, lambda: self._show_update_dialog(latest, body))
            except Exception as e:
                print(f"[update] {e}")
        threading.Thread(target=fetch, daemon=True).start()

    def _show_update_dialog(self, version, changelog):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Доступно обновление!")
        dlg.geometry("600x450")
        dlg.configure(fg_color=BG_DARK)
        dlg.transient(self)
        dlg.grab_set()
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() // 2) - 300
        y = (dlg.winfo_screenheight() // 2) - 225
        dlg.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dlg, text=f"🔥 Вышла новая версия: v{version}",
                     font=("Segoe UI", 24, "bold"), text_color=ACCENT).pack(pady=(30, 10))
        ctk.CTkLabel(dlg, text="Что нового:", font=("Segoe UI", 16, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=30)

        notes_box = ctk.CTkTextbox(dlg, fg_color="#1e1e1e", text_color=MUTED,
                                   font=("Segoe UI", 13), wrap="word", height=200)
        notes_box.pack(fill="both", expand=True, padx=30, pady=10)
        notes_box.insert("1.0", changelog)
        notes_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=20)
        ctk.CTkButton(btn_frame, text="Позже", fg_color="#333333", hover_color="#444444",
                      width=120, height=40, command=dlg.destroy).pack(side="left")

        def download():
            webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
            dlg.destroy()
        ctk.CTkButton(btn_frame, text="📥 Скачать обновление", fg_color=ACCENT, hover_color=ACCENT_H,
                      width=200, height=40, command=download).pack(side="right")

    def _update_notes(self, text):
        self.notes_textbox.configure(state="normal")
        self.notes_textbox.delete("1.0", "end")
        self.notes_textbox.insert("1.0", text)
        self.notes_textbox.configure(state="disabled")

    # ---------- Закрытие ----------
    def on_close(self):
        try:
            self._save_config()
        except Exception:
            pass
        try:
            if self.game_process and self.game_process.poll() is None:
                self.game_process.terminate()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    app = FireLauncher()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()