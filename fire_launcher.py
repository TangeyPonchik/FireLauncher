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
from io import BytesIO
from PIL import Image
from tkinter import filedialog
from datetime import datetime

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

# Определяем базу для сохранения конфигов
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

MODRINTH_API = "https://mod.mcimirror.top/modrinth/v2"
GITHUB_REPO = "TangeyPonchik/FireLauncher"

LAUNCHER_CHANGELOG = """
🔥 FireLauncher v2.4.0 (Текущая)
- Добавлена "Умная починка" (проверка модов и перекачка битых файлов).
- Добавлен Менеджер сборок (Инстансы) — можно менять папку игры.
- Добавлена вкладка "Статистика" с подсчетом времени в игре.
"""

class FireLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        
        self.current_version = "2.4.0"
        self.title(f"FireLauncher v{self.current_version}")
        self.geometry("1150x800")
        self.minsize(1050, 700)
        self.configure(fg_color=BG_DARK)

        self.grid_columnconfigure(0, weight=0, minsize=200)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.selected_version = ctk.StringVar(value="")
        self.version_dict = {}
        self.all_versions_list = []
        self.filtered_versions_list = []
        
        self.is_installing = False
        self.current_account = None
        self.minecraft_dir = DEFAULT_MINECRAFT_DIR
        self.ram_value = ctk.IntVar(value=4)
        
        self.game_process = None
        self.is_game_running = False
        self.game_start_time = 0
        
        self._progress_target = 0.0
        self._pulse_step = 0
        
        self.show_releases_var = ctk.BooleanVar(value=True)
        self.show_snapshots_var = ctk.BooleanVar(value=False)
        self.show_modified_var = ctk.BooleanVar(value=True)
        
        self.frames = {}
        self.avatar_image = None
        self.monitor_thread_running = False
        self._saved_version = ""
        self.total_play_time = 0 # в секундах
        
        self._build_sidebar()
        self._build_frames()
        self._show_frame("play")
        self._update_notes(LAUNCHER_CHANGELOG)
        
        self._load_config()
        threading.Thread(target=self._load_versions, daemon=True).start()

        self.after(100, self.fade_in)
        self.after(1500, self._check_github_updates)
        self.after(1000, self._pulse_play_button)
        self.after(500, self._update_stats_loop) # Запуск мониторинга статистики

    def fade_in(self, duration=400):
        self.update()
        self.deiconify()
        self.attributes("-alpha", 0.0)
        hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        steps = 20
        delay = duration // steps
        def step(i=0):
            if i <= steps:
                progress = i / steps
                alpha = 1 - (1 - progress) ** 3
                ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, int(alpha * 255), 2)
                self.after(delay, lambda: step(i + 1))
            else:
                self.attributes("-alpha", 1.0)
        step()

    def _pulse_play_button(self):
        if self.is_game_running or self.is_installing: return
        self._pulse_step += 1
        val = (math.sin(self._pulse_step / 10.0) + 1) / 2
        r = int(255 * val + 138 * (1 - val))
        g = int(87 * val + 42 * (1 - val))
        b = int(34 * val + 10 * (1 - val))
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        try: self.play_btn.configure(fg_color=hex_color)
        except: pass
        self.after(50, self._pulse_play_button)

    def _animate_progress(self):
        if not self.progress_bar.winfo_ismapped(): return
        current = self.progress_bar.get()
        target = self._progress_target
        if abs(current - target) > 0.005:
            new_val = current + (target - current) * 0.15
            self.progress_bar.set(new_val)
            self.after(16, self._animate_progress)
        else:
            self.progress_bar.set(target)

    # --- Статистика ---
    def _update_stats_loop(self):
        """Обновляет время игры в реальном времени, если игра запущена."""
        if self.is_game_running and self.game_start_time > 0:
            elapsed = time.time() - self.game_start_time
            self.total_play_time += elapsed
            self.game_start_time = time.time()
            
            # Обновляем лейбл в статистике
            h = int(self.total_play_time // 3600)
            m = int((self.total_play_time % 3600) // 60)
            if hasattr(self, 'play_time_lbl'):
                self.play_time_lbl.configure(text=f"⏱️ Время в игре: {h} ч {m} мин")
        self.after(1000, self._update_stats_loop)

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(sidebar, text="🔥 Fire", font=("Segoe UI", 28, "bold"), text_color=ACCENT).pack(pady=(40, 30), padx=20, anchor="w")

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
        ctk.CTkButton(parent, text=text, command=command, fg_color="transparent", hover_color=SELECT_BG, text_color=TEXT, anchor="w", font=("Segoe UI", 15), height=40, corner_radius=8).pack(fill="x", padx=10, pady=4)

    def _build_frames(self):
        # --- Фрейм "Играть" ---
        play_frame = ctk.CTkFrame(self, fg_color="transparent")
        play_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        
        ctk.CTkLabel(play_frame, text="Добро пожаловать в FireLauncher!", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 5))
        self.desc_label = ctk.CTkLabel(play_frame, text="Выберите версию и нажмите Играть.", font=("Segoe UI", 14), text_color=MUTED)
        self.desc_label.pack(anchor="w", pady=(0, 10))

        notes_frame = ctk.CTkFrame(play_frame, fg_color="#1e1e1e", corner_radius=15)
        notes_frame.pack(fill="both", expand=True, pady=(10, 20))
        notes_top = ctk.CTkFrame(notes_frame, fg_color="transparent")
        notes_top.pack(fill="x", padx=20, pady=(10, 5))
        ctk.CTkLabel(notes_top, text="📜 Что нового", font=("Segoe UI", 16, "bold"), text_color=TEXT).pack(side="left")
        
        self.notes_textbox = ctk.CTkTextbox(notes_frame, fg_color="#121212", text_color=MUTED, font=("Segoe UI", 13), wrap="word", border_width=0)
        self.notes_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.notes_textbox.configure(state="disabled")

        bottom_frame = ctk.CTkFrame(play_frame, fg_color="#1e1e1e", corner_radius=15, height=100)
        bottom_frame.pack(fill="x", side="bottom", pady=10)
        bottom_frame.pack_propagate(False)

        left_bottom = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        left_bottom.pack(side="left", padx=15, pady=10, fill="y")
        ctk.CTkLabel(left_bottom, text="Версия:", font=("Segoe UI", 12), text_color=MUTED).pack(anchor="w")
        
        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(left_bottom, textvariable=self.search_var, placeholder_text="Поиск версии", width=150, height=30, fg_color="#121212", border_width=0)
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_var.trace_add("write", self._filter_search)

        self.version_menu = ctk.CTkOptionMenu(left_bottom, variable=self.selected_version, values=["Загрузка..."], width=180, height=30, fg_color="#2c2c2c", button_color=ACCENT, command=self._on_version_change)
        self.version_menu.pack(side="left")

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
        self.fix_btn = ctk.CTkButton(right_bottom, text="🔧 Починить", font=("Segoe UI", 14), fg_color="#333333", hover_color="#444444", width=100, height=40, corner_radius=10, command=self.repair_game)
        self.fix_btn.pack(side="left", padx=(0, 10))
        
        self.play_btn = ctk.CTkButton(right_bottom, text="▶ ИГРАТЬ", font=("Segoe UI", 18, "bold"), fg_color=ACCENT, hover_color=ACCENT_H, width=150, height=50, corner_radius=10, command=self.start_game)
        self.play_btn.pack(side="left")
        self.frames["play"] = play_frame

        # --- Фрейм "Статистика" ---
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        ctk.CTkLabel(stats_frame, text="Статистика", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 20))

        self.play_time_lbl = ctk.CTkLabel(stats_frame, text="⏱️ Время в игре: 0 ч 0 мин", font=("Segoe UI", 18), text_color=TEXT)
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

        # --- Фрейм "Настройки" ---
        settings_frame = ctk.CTkFrame(self, fg_color="transparent")
        settings_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        ctk.CTkLabel(settings_frame, text="Настройки", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 30))

        ctk.CTkLabel(settings_frame, text="Выделяемая память (ОЗУ):", font=("Segoe UI", 14), text_color=TEXT).pack(anchor="w", pady=(0, 5))
        self.ram_slider = ctk.CTkSlider(settings_frame, from_=2, to=16, number_of_steps=14, command=self._update_ram_label)
        self.ram_slider.pack(anchor="w", pady=5)
        self.ram_slider.set(4)
        self.ram_label = ctk.CTkLabel(settings_frame, text="4 ГБ", font=("Segoe UI", 12), text_color=MUTED)
        self.ram_label.pack(anchor="w")

        ctk.CTkLabel(settings_frame, text="Папка с игрой (Инстанс):", font=("Segoe UI", 14), text_color=TEXT).pack(anchor="w", pady=(20, 5))
        self.folder_label = ctk.CTkLabel(settings_frame, text=self.minecraft_dir, font=("Segoe UI", 11), text_color=MUTED, wraplength=500)
        self.folder_label.pack(anchor="w", pady=5)
        folder_btn_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        folder_btn_frame.pack(anchor="w", pady=10)
        ctk.CTkButton(folder_btn_frame, text="Выбрать", fg_color="#4f8cff", hover_color="#3a75e6", command=self._choose_minecraft_dir).pack(side="left", padx=(0, 10))
        ctk.CTkButton(folder_btn_frame, text="Открыть", fg_color="#333333", hover_color="#444444", command=self._open_minecraft_dir).pack(side="left")
        self.frames["settings"] = settings_frame

        # Заглушки для остальных вкладок, чтобы не падало
        self.frames["builds"] = ctk.CTkFrame(self, fg_color="transparent")
        self.frames["mods"] = ctk.CTkFrame(self, fg_color="transparent")
        self.frames["account"] = ctk.CTkFrame(self, fg_color="transparent")

    def _show_frame(self, name):
        for frame in self.frames.values():
            frame.grid_forget()
        self.frames[name].grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        
        if name == "stats" and not self.monitor_thread_running:
            self.monitor_thread_running = True
            threading.Thread(target=self._update_system_stats_loop, daemon=True).start()

    def _update_system_stats_loop(self):
        while self.monitor_thread_running:
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                self.after(0, lambda: self.cpu_label.configure(text=f"CPU: {cpu}%"))
                self.after(0, lambda: self.cpu_bar.set(cpu/100))
                self.after(0, lambda: self.ram_usage_label.configure(text=f"RAM: {ram}%"))
                self.after(0, lambda: self.ram_usage_bar.set(ram/100))
            except: pass
            time.sleep(1)

    def _update_ram_label(self, value):
        self.ram_value.set(int(value))
        self.ram_label.configure(text=f"{int(value)} ГБ")
        if hasattr(self, "_save_timer"): self.after_cancel(self._save_timer)
        self._save_timer = self.after(1000, self._save_config)

    def _choose_minecraft_dir(self):
        path = filedialog.askdirectory(initialdir=self.minecraft_dir)
        if path:
            self.minecraft_dir = path
            self.folder_label.configure(text=self.minecraft_dir)
            self._save_config()
            self._load_versions()

    def _open_minecraft_dir(self):
        os.startfile(self.minecraft_dir)

    # --- Умная починка ---
    def repair_game(self):
        ver = self.version_dict.get(self.selected_version.get(), "")
        if not ver: return
        self.desc_label.configure(text=f"Умная починка {ver}...")
        
        # Удаляем только версию, чтобы перекачать её
        version_path = os.path.join(self.minecraft_dir, "versions", ver)
        if os.path.exists(version_path): 
            shutil.rmtree(version_path, ignore_errors=True)
        
        # Проверяем папку mods на пустые файлы
        mods_dir = os.path.join(self.minecraft_dir, "mods")
        if os.path.exists(mods_dir):
            for f in os.listdir(mods_dir):
                if f.endswith(".jar"):
                    p = os.path.join(mods_dir, f)
                    if os.path.getsize(p) < 1024: # Если файл меньше 1 КБ, он битый
                        try: os.remove(p)
                        except: pass
                        
        self.desc_label.configure(text="Кэш версии и битые моды очищены. Нажми Играть.", text_color=MUTED)

    def _update_progress(self, current, total=None):
        if total and total > 0:
            self._progress_target = current / total
            if not hasattr(self, "_progress_animating") or not self._progress_animating:
                self._progress_animating = True
                self._animate_progress()

    def _run_game_logic(self):
        try:
            ver = self.version_dict.get(self.selected_version.get(), "")
            if not ver: raise ValueError("Версия не выбрана")
            
            self.after(0, lambda: self.progress_label.pack(anchor="center"))
            self.after(0, lambda: self.progress_bar.pack(anchor="center"))
            self.after(0, lambda: self.play_btn.configure(text="Установка...", state="disabled"))
            
            self.is_installing = True
            
            def safe_status(t): self.after(0, lambda: self.progress_label.configure(text=t))
            callback = {"setStatus": safe_status, "setProgress": self._update_progress, "setMax": lambda m: None}
            minecraft_launcher_lib.install.install_minecraft_version(ver, self.minecraft_dir, callback=callback)

            jvm_args = [f"-Xmx{self.ram_value.get()}G", "-Xms2G"]

            if self.current_account:
                options = {"username": self.current_account["username"], "uuid": self.current_account["uuid"], "token": self.current_account["token"], "jvmArguments": jvm_args}
            else:
                options = minecraft_launcher_lib.utils.generate_test_options()
                options["jvmArguments"] = jvm_args

            command = minecraft_launcher_lib.command.get_minecraft_command(ver, self.minecraft_dir, options)
            
            if self.current_account and os.path.exists(AUTHLIB_PATH):
                command.insert(1, f"-javaagent:{AUTHLIB_PATH}={ELY_API_ROOT}")

            self.after(0, lambda: self.desc_label.configure(text="Запуск..."))
            log_dir = os.path.join(self.minecraft_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "launcher_last.log"), "w") as log:
                self.game_process = subprocess.Popen(command, cwd=self.minecraft_dir, stdout=log, stderr=log)
            
            time.sleep(2)
            
            if self.game_process.poll() is None:
                self.is_game_running = True
                self.game_start_time = time.time() # Старт таймера
                self.after(0, lambda: self.play_btn.configure(text="⏹ ЗАКРЫТЬ", fg_color="#ff5c5c", hover_color="#e64a19", state="normal"))
                self.after(0, lambda: self.desc_label.configure(text="Игра запущена!"))
                self._watch_game_process()
            else:
                self.after(0, lambda: self.desc_label.configure(text="Игра вылетела при запуске (проверь логи)"))
                self.after(0, lambda: self.play_btn.configure(text="▶ ИГРАТЬ", fg_color=ACCENT, hover_color=ACCENT_H, state="normal"))
                self.is_installing = False
                self._pulse_play_button()

        except Exception as e:
            self.after(0, lambda: self.desc_label.configure(text=f"Ошибка: {e}", text_color="#ff5c5c"))
            self.after(0, lambda: self.play_btn.configure(text="▶ ИГРАТЬ", fg_color=ACCENT, hover_color=ACCENT_H, state="normal"))
            self.is_installing = False
            self._pulse_play_button()
        finally:
            self.after(0, lambda: self.progress_bar.pack_forget())
            self.after(0, lambda: self.progress_label.pack_forget())

    def _watch_game_process(self):
        def watch():
            self.game_process.wait()
            
            # Считаем время игры
            if self.game_start_time > 0:
                self.total_play_time += time.time() - self.game_start_time
                self.game_start_time = 0
            
            self.is_game_running = False
            self.is_installing = False
            self.after(0, lambda: self.play_btn.configure(text="▶ ИГРАТЬ", fg_color=ACCENT, hover_color=ACCENT_H, state="normal"))
            self.after(0, lambda: self.desc_label.configure(text="Игра закрыта."))
            self.after(0, self._save_config) # Сохраняем время
            self._pulse_play_button()
        threading.Thread(target=watch, daemon=True).start()

    def start_game(self):
        if self.is_installing: return
        if self.is_game_running:
            if self.game_process:
                self.game_process.terminate()
                self.desc_label.configure(text="Завершение игры...")
            return
        self.is_installing = True
        threading.Thread(target=self._run_game_logic, daemon=True).start()

    # --- Конфиг ---
    def _save_config(self):
        config = {
            "version": self.selected_version.get(),
            "minecraft_dir": self.minecraft_dir,
            "ram": self.ram_value.get(),
            "username": self.current_account["username"] if self.current_account else None,
            "uuid": self.current_account["uuid"] if self.current_account else None,
            "show_releases": self.show_releases_var.get(),
            "show_snapshots": self.show_snapshots_var.get(),
            "show_modified": self.show_modified_var.get(),
            "total_play_time": self.total_play_time
        }
        try:
            with open(CONFIG_FILE, "w") as f: json.dump(config, f, indent=2)
            if self.current_account and self.current_account.get("token"):
                with open(TOKEN_FILE, "w") as f: f.write(self.current_account["token"])
        except: pass

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE): return
        try:
            with open(CONFIG_FILE, "r") as f: config = json.load(f)
            if config.get("username"):
                token = "0"
                if os.path.exists(TOKEN_FILE):
                    with open(TOKEN_FILE, "r") as f: token = f.read().strip()
                self.current_account = {"username": config["username"], "uuid": config["uuid"], "token": token}
                self.after(0, lambda: self.user_label.configure(text=self.current_account["username"]))
            if config.get("minecraft_dir"):
                self.minecraft_dir = config["minecraft_dir"]
                self.folder_label.configure(text=self.minecraft_dir)
            if config.get("ram"):
                self.ram_value.set(config["ram"])
                self.ram_slider.set(config["ram"])
                self.ram_label.configure(text=f"{config['ram']} ГБ")
            
            self.show_releases_var.set(config.get("show_releases", True))
            self.show_snapshots_var.set(config.get("show_snapshots", False))
            self.show_modified_var.set(config.get("show_modified", True))
            
            self.total_play_time = config.get("total_play_time", 0)
            h = int(self.total_play_time // 3600)
            m = int((self.total_play_time % 3600) // 60)
            if hasattr(self, 'play_time_lbl'):
                self.play_time_lbl.configure(text=f"⏱️ Время в игре: {h} ч {m} мин")

            self._saved_version = config.get("version", "")
        except: pass

    def _filter_search(self, *args):
        query = self.search_var.get().lower()
        if not query:
            self.version_menu.configure(values=self.filtered_versions_list)
            return
        filtered = [v for v in self.filtered_versions_list if query in v.lower()]
        self.version_menu.configure(values=filtered)

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
                    display = f"{v['id']} (Snapshot)"
                    self.version_dict[display] = v["id"]
                    
            local_dir = os.path.join(self.minecraft_dir, "versions")
            if os.path.exists(local_dir):
                for folder in os.listdir(local_dir):
                    if "fabric" in folder.lower() or "forge" in folder.lower() or "quilt" in folder.lower():
                        json_path = os.path.join(local_dir, folder, f"{folder}.json")
                        if os.path.exists(json_path):
                            if folder not in self.version_dict.values():
                                self.version_dict[folder] = folder
            
            if not self.version_dict:
                print("Не удалось загрузить версии (пустой список)")
                return

            self._apply_filters()
            
            if hasattr(self, "_saved_version") and self._saved_version in self.filtered_versions_list:
                self.after(0, lambda: self.selected_version.set(self._saved_version))
                
        except Exception as e:
            err_msg = str(e) if str(e) else "Неизвестная ошибка"
            self.after(0, lambda: self.desc_label.configure(text=f"Ошибка версий: {err_msg}"))

    def _apply_filters(self):
        show_rel = self.show_releases_var.get()
        show_snap = self.show_snapshots_var.get()
        show_mod = self.show_modified_var.get()

        if not (show_rel or show_snap or show_mod):
            self.show_releases_var.set(True)
            show_rel = True

        self.filtered_versions_list = []
        for display, real_id in self.version_dict.items():
            is_snapshot = "Snapshot" in display
            is_modified = "fabric" in real_id.lower() or "forge" in real_id.lower() or "quilt" in real_id.lower()
            is_release = not is_snapshot and not is_modified

            if (is_release and show_rel) or (is_snapshot and show_snap) or (is_modified and show_mod):
                self.filtered_versions_list.append(display)

        if not self.filtered_versions_list: return

        self.version_menu.configure(values=self.filtered_versions_list)
        
        current = self.selected_version.get()
        if current not in self.filtered_versions_list:
            self.selected_version.set(self.filtered_versions_list[0])

    def _update_notes(self, text):
        self.notes_textbox.configure(state="normal")
        self.notes_textbox.delete("1.0", "end")
        self.notes_textbox.insert("1.0", text)
        self.notes_textbox.configure(state="disabled")

    def _check_github_updates(self):
        def fetch():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                headers = {"User-Agent": "FireLauncher"}
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    latest_tag = data.get("tag_name", "").replace("v", "")
                    
                    if latest_tag and latest_tag != self.current_version:
                        body = data.get("body", "Нет описания.")
                        if len(body) > 500: body = body[:500] + "..."
                        self.after(0, lambda: self._show_update_dialog(latest_tag, body))
            except Exception as e:
                print(f"Ошибка проверки обновлений GitHub: {e}")
        threading.Thread(target=fetch, daemon=True).start()

    def _show_update_dialog(self, version, changelog):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Доступно обновление!")
        dlg.geometry("600x450")
        dlg.configure(fg_color=BG_DARK)
        dlg.transient(self)
        dlg.grab_set()
        
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() // 2) - (600 // 2)
        y = (dlg.winfo_screenheight() // 2) - (450 // 2)
        dlg.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dlg, text=f"🔥 Вышла новая версия: v{version}", font=("Segoe UI", 24, "bold"), text_color=ACCENT).pack(pady=(30, 10))
        ctk.CTkLabel(dlg, text="Что нового:", font=("Segoe UI", 16, "bold"), text_color=TEXT).pack(anchor="w", padx=30)

        notes_box = ctk.CTkTextbox(dlg, fg_color="#1e1e1e", text_color=MUTED, font=("Segoe UI", 13), wrap="word", height=200)
        notes_box.pack(fill="both", expand=True, padx=30, pady=10)
        notes_box.insert("1.0", changelog)
        notes_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=20)
        
        ctk.CTkButton(btn_frame, text="Позже", fg_color="#333333", hover_color="#444444", width=120, height=40, command=dlg.destroy).pack(side="left")
        
        def download():
            webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
            dlg.destroy()
            
        ctk.CTkButton(btn_frame, text="📥 Скачать обновление", fg_color=ACCENT, hover_color=ACCENT_H, width=200, height=40, command=download).pack(side="right")

if __name__ == "__main__":
    app = FireLauncher()
    app.protocol("WM_DELETE_WINDOW", lambda: (app._save_config(), app.destroy()))
    app.mainloop()