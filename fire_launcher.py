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
AUTHLIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "authlib-injector.jar")
ELY_AUTH_URL = "https://authserver.ely.by/auth/authenticate"
ELY_SKIN_URL = "https://authserver.ely.by/api/skins"
ELY_API_ROOT = "ely.by"

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firelauncher_config.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_token.dat")

MODRINTH_API = "https://mod.mcimirror.top/modrinth/v2"

LAUNCHER_CHANGELOG = """
🔥 FireLauncher v2.0.0 (Мега-обновление!)
- Смена скина Ely.by прямо в лаунчере.
- Автоматическое скачивание нужной Java.
- Импорт сборок (.mrpack и .zip).
- Мониторинг ОЗУ/CPU в реальном времени.
- Проверка модов на вирусы (опционально).
"""

class FireLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FireLauncher v2.0.3")
        self.geometry("1150x800")
        self.minsize(1050, 700)
        self.configure(fg_color=BG_DARK)

        self.grid_columnconfigure(0, weight=0, minsize=200)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.selected_version = ctk.StringVar(value="")
        self.version_dict = {}
        self.all_versions_list = []
        self.is_installing = False
        self.current_account = None
        self.minecraft_dir = DEFAULT_MINECRAFT_DIR
        self.ram_value = ctk.IntVar(value=4)
        
        self.frames = {}
        self.avatar_image = None
        self.monitor_thread_running = False
        
        self._build_sidebar()
        self._build_frames()
        self._show_frame("play")
        self._update_notes(LAUNCHER_CHANGELOG)
        
        self._load_config()
        threading.Thread(target=self._load_versions, daemon=True).start()

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(7, weight=1)

        logo = ctk.CTkLabel(sidebar, text="🔥 Fire", font=("Segoe UI", 28, "bold"), text_color=ACCENT)
        logo.pack(pady=(40, 30), padx=20, anchor="w")

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
        btn = ctk.CTkButton(parent, text=text, command=command, fg_color="transparent", hover_color=SELECT_BG, text_color=TEXT, anchor="w", font=("Segoe UI", 15), height=40, corner_radius=8)
        btn.pack(fill="x", padx=10, pady=4)

    def _build_frames(self):
        # --- Фрейм "Играть" ---
        play_frame = ctk.CTkFrame(self, fg_color="transparent")
        play_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        
        ctk.CTkLabel(play_frame, text="Добро пожаловать в FireLauncher v2!", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 5))
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
        self.search_var.trace_add("write", self._filter_versions)

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

        # --- Фрейм "Сборки" (Импорт и Модлоадеры) ---
        build_frame = ctk.CTkFrame(self, fg_color="transparent")
        build_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        ctk.CTkLabel(build_frame, text="Сборки и Модлоадеры", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 5))
        
        # Импорт сборок
        ctk.CTkLabel(build_frame, text="Импорт готовой сборки (.mrpack / CurseForge .zip):", font=("Segoe UI", 14), text_color=TEXT).pack(anchor="w", pady=(20, 5))
        ctk.CTkButton(build_frame, text="📂 Выбрать файл сборки", fg_color="#4f8cff", hover_color="#3a75e6", width=200, height=40, command=self._import_modpack).pack(anchor="w", pady=10)

        ctk.CTkLabel(build_frame, text="─" * 50, text_color=MUTED).pack(pady=20)

        ctk.CTkLabel(build_frame, text="Установка модлоадеров:", font=("Segoe UI", 14), text_color=TEXT).pack(anchor="w", pady=(10, 5))
        self.build_version_var = ctk.StringVar(value="")
        self.build_version_menu = ctk.CTkOptionMenu(build_frame, variable=self.build_version_var, values=["Загрузка..."], width=250, height=35, fg_color="#1e1e1e", button_color=ACCENT)
        self.build_version_menu.pack(anchor="w", pady=(5, 20))
        
        btn_frame = ctk.CTkFrame(build_frame, fg_color="transparent")
        btn_frame.pack(anchor="w", pady=10)
        ctk.CTkButton(btn_frame, text="Установить Fabric", fg_color="#4f8cff", hover_color="#3a75e6", width=160, height=40, command=lambda: self._install_mod_loader("fabric")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Установить Forge", fg_color="#ff5c5c", hover_color="#e64a19", width=160, height=40, command=lambda: self._install_mod_loader("forge")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Удалить", fg_color="#333333", hover_color="#444444", width=100, height=40, command=self._delete_selected_version).pack(side="left")
        
        self.build_status = ctk.CTkLabel(build_frame, text="", font=("Segoe UI", 12), text_color=MUTED)
        self.build_status.pack(anchor="w", pady=20)
        self.frames["builds"] = build_frame

        # --- Фрейм "Моды" ---
        mods_frame = ctk.CTkFrame(self, fg_color="transparent")
        mods_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        
        header_mods = ctk.CTkFrame(mods_frame, fg_color="transparent")
        header_mods.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(header_mods, text="Поиск модов", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkButton(header_mods, text="🛡 Проверить моды", fg_color="#ff5c5c", hover_color="#e64a19", width=140, height=35, command=self._scan_mods_antivirus).pack(side="right", padx=5)
        ctk.CTkButton(header_mods, text="📁 Открыть папку", fg_color="#333333", hover_color="#444444", width=140, height=35, command=self._open_mods_dir).pack(side="right")

        search_frame = ctk.CTkFrame(mods_frame, fg_color="transparent")
        search_frame.pack(fill="x", pady=(0, 15))
        
        self.mod_search_entry = ctk.CTkEntry(search_frame, placeholder_text="Название мода (Sodium, JEI...)", width=400, height=40, fg_color="#1e1e1e")
        self.mod_search_entry.pack(side="left", padx=(0, 10))
        self.mod_search_entry.bind("<Return>", lambda e: self._search_mods())
        ctk.CTkButton(search_frame, text="Найти", fg_color=ACCENT, hover_color=ACCENT_H, width=100, height=40, command=self._search_mods).pack(side="left")

        self.mods_scroll = ctk.CTkScrollableFrame(mods_frame, fg_color="transparent")
        self.mods_scroll.pack(fill="both", expand=True)
        self.frames["mods"] = mods_frame

        # --- Фрейм "Аккаунт" ---
        acc_frame = ctk.CTkFrame(self, fg_color="transparent")
        acc_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        ctk.CTkLabel(acc_frame, text="Аккаунт Ely.by", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 5))
        
        self.ely_user = ctk.CTkEntry(acc_frame, placeholder_text="Email или ник", width=300, height=40, fg_color="#1e1e1e")
        self.ely_user.pack(anchor="w", pady=5)
        self.ely_pass = ctk.CTkEntry(acc_frame, placeholder_text="Пароль", width=300, height=40, fg_color="#1e1e1e", show="*")
        self.ely_pass.pack(anchor="w", pady=5)
        
        btn_acc = ctk.CTkFrame(acc_frame, fg_color="transparent")
        btn_acc.pack(anchor="w", pady=15)
        ctk.CTkButton(btn_acc, text="Войти", fg_color=ACCENT, hover_color=ACCENT_H, height=40, command=self.ely_login).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_acc, text="🎨 Сменить скин", fg_color="#4f8cff", hover_color="#3a75e6", height=40, command=self._change_skin).pack(side="left")
        
        self.acc_status = ctk.CTkLabel(acc_frame, text="", font=("Segoe UI", 12), text_color=MUTED)
        self.acc_status.pack(anchor="w")
        self.frames["account"] = acc_frame

        # --- Фрейм "Статистика" ---
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        ctk.CTkLabel(stats_frame, text="Мониторинг системы", font=("Segoe UI", 28, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 20))
        
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
        
        ctk.CTkLabel(stats_frame, text="* Запустите игру, чтобы видеть нагрузку", font=("Segoe UI", 11), text_color=MUTED).pack(anchor="w", pady=20)
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

        ctk.CTkLabel(settings_frame, text="Дополнительные JVM-аргументы:", font=("Segoe UI", 14), text_color=TEXT).pack(anchor="w", pady=(20, 5))
        self.jvm_args_entry = ctk.CTkEntry(settings_frame, placeholder_text="-XX:+UseG1GC", width=500, height=35, fg_color="#1e1e1e")
        self.jvm_args_entry.pack(anchor="w", pady=5)

        ctk.CTkLabel(settings_frame, text="Папка с игрой:", font=("Segoe UI", 14), text_color=TEXT).pack(anchor="w", pady=(20, 5))
        self.folder_label = ctk.CTkLabel(settings_frame, text=self.minecraft_dir, font=("Segoe UI", 11), text_color=MUTED, wraplength=500)
        self.folder_label.pack(anchor="w", pady=5)
        folder_btn_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        folder_btn_frame.pack(anchor="w", pady=10)
        ctk.CTkButton(folder_btn_frame, text="Выбрать", fg_color="#4f8cff", hover_color="#3a75e6", command=self._choose_minecraft_dir).pack(side="left", padx=(0, 10))
        ctk.CTkButton(folder_btn_frame, text="Открыть", fg_color="#333333", hover_color="#444444", command=self._open_minecraft_dir).pack(side="left")
        self.frames["settings"] = settings_frame

    def _show_frame(self, name):
        for frame in self.frames.values():
            frame.grid_forget()
        self.frames[name].grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        
        # Запуск мониторинга при переходе на вкладку
        if name == "stats" and not self.monitor_thread_running:
            self.monitor_thread_running = True
            threading.Thread(target=self._update_stats_loop, daemon=True).start()

    # --- 1. Смена скина ---
    def _change_skin(self):
        if not self.current_account:
            self.acc_status.configure(text="Сначала войдите в аккаунт!", text_color="#ff5c5c")
            return
            
        path = filedialog.askopenfilename(title="Выберите скин (PNG 64x64)", filetypes=[("PNG", "*.png")])
        if not path: return
        
        self.acc_status.configure(text="Загрузка скина...", text_color=MUTED)
        def upload():
            try:
                with open(path, "rb") as f:
                    files = {'skin': f}
                    headers = {"Authorization": f"Bearer {self.current_account['token']}"}
                    # Ely.by API для загрузки скина
                    r = requests.post(f"{ELY_SKIN_URL}/{self.current_account['uuid']}", headers=headers, files=files)
                    
                if r.status_code == 200:
                    self.after(0, lambda: self.acc_status.configure(text="Скин обновлен!", text_color="#3ddc84"))
                    self._download_avatar(self.current_account["username"]) # Обновить аватарку
                else:
                    self.after(0, lambda: self.acc_status.configure(text=f"Ошибка: {r.status_code}", text_color="#ff5c5c"))
            except Exception as e:
                self.after(0, lambda: self.acc_status.configure(text=f"Ошибка: {e}", text_color="#ff5c5c"))
        threading.Thread(target=upload, daemon=True).start()

    # --- 3. Импорт сборок ---
    def _import_modpack(self):
        path = filedialog.askopenfilename(title="Выберите сборку", filetypes=[("Modpacks", "*.mrpack *.zip")])
        if not path: return
        
        self.build_status.configure(text=f"Импорт {os.path.basename(path)}...", text_color=MUTED)
        
        def import_thread():
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Распаковка архива
                    with zipfile.ZipFile(path, 'r') as z:
                        z.extractall(temp_dir)
                    
                    if path.endswith(".mrpack"):
                        # Логика для Modrinth .mrpack
                        manifest_path = os.path.join(temp_dir, "modrinth.index.json")
                        if not os.path.exists(manifest_path): raise Exception("Не найден modrinth.index.json")
                        
                        with open(manifest_path, "r") as f:
                            manifest = json.load(f)
                            
                        game_ver = manifest["dependencies"]["minecraft"]
                        loader = "fabric" if "fabric-loader" in manifest["dependencies"] else "forge"
                        
                        # 1. Установка нужной версии игры и модлоадера
                        self.after(0, lambda: self.build_status.configure(text="Скачивание игры и модлоадера..."))
                        minecraft_launcher_lib.install.install_minecraft_version(game_ver, self.minecraft_dir)
                        
                        if loader == "fabric":
                            fabric = minecraft_launcher_lib.mod_loader.get_mod_loader("fabric")
                            fabric.install(game_ver, self.minecraft_dir)
                        elif loader == "forge":
                            forge = minecraft_launcher_lib.mod_loader.get_mod_loader("forge")
                            forge.install(game_ver, self.minecraft_dir)
                            
                        # 2. Скачивание модов
                        self.after(0, lambda: self.build_status.configure(text="Скачивание модов..."))
                        mods_dir = os.path.join(self.minecraft_dir, "mods")
                        os.makedirs(mods_dir, exist_ok=True)
                        
                        for file_info in manifest.get("files", []):
                            url = file_info["downloads"][0]
                            filename = file_info["path"].split("/")[-1]
                            r = requests.get(url, stream=True)
                            with open(os.path.join(mods_dir, filename), 'wb') as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                                    
                    elif path.endswith(".zip"):
                        # Упрощенная логика для CurseForge (если есть manifest.json)
                        manifest_path = os.path.join(temp_dir, "manifest.json")
                        if os.path.exists(manifest_path):
                            # В реальности нужно парсить projectID и fileID и качать через API CurseForge
                            # Здесь мы просто копируем overrides (если есть)
                            overrides = os.path.join(temp_dir, "overrides")
                            if os.path.exists(overrides):
                                shutil.copytree(overrides, self.minecraft_dir, dirs_exist_ok=True)
                            self.after(0, lambda: self.build_status.configure(text="CurseForge сборка импортирована (частично)", text_color="#3ddc84"))
                        else:
                            # Если это просто zip с модами
                            mods_dir = os.path.join(self.minecraft_dir, "mods")
                            os.makedirs(mods_dir, exist_ok=True)
                            for root, _, files in os.walk(temp_dir):
                                for file in files:
                                    if file.endswith(".jar"):
                                        shutil.copy(os.path.join(root, file), os.path.join(mods_dir, file))
                            self.after(0, lambda: self.build_status.configure(text="Моды из ZIP скопированы!", text_color="#3ddc84"))

                self.after(0, lambda: self.build_status.configure(text="Импорт завершен!", text_color="#3ddc84"))
                self.after(0, self._load_versions)
            except Exception as e:
                self.after(0, lambda: self.build_status.configure(text=f"Ошибка импорта: {e}", text_color="#ff5c5c"))
        threading.Thread(target=import_thread, daemon=True).start()

    # --- 4. Мониторинг ---
    def _update_stats_loop(self):
        while self.monitor_thread_running:
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                
                self.after(0, lambda: self.cpu_label.configure(text=f"CPU: {cpu}%"))
                self.after(0, lambda: self.cpu_bar.set(cpu/100))
                self.after(0, lambda: self.ram_usage_label.configure(text=f"RAM: {ram}%"))
                self.after(0, lambda: self.ram_usage_bar.set(ram/100))
            except:
                pass
            time.sleep(1)

    # --- 5. Антивирус для модов ---
    def _scan_mods_antivirus(self):
        mods_dir = os.path.join(self.minecraft_dir, "mods")
        if not os.path.exists(mods_dir): return
        
        def scan():
            self.after(0, lambda: self._show_toast("Сканирование модов..."))
            found = 0
            for f in os.listdir(mods_dir):
                if f.endswith(".jar"):
                    try:
                        from scanner import hybrid_scan
                        res = hybrid_scan(os.path.join(mods_dir, f))
                        if res["status"] in ("malicious", "suspicious"):
                            found += 1
                    except: pass
            
            if found > 0:
                self.after(0, lambda: self._show_toast(f"⚠ Найдено {found} подозрительных модов!"))
            else:
                self.after(0, lambda: self._show_toast("✅ Все моды чистые"))
        threading.Thread(target=scan, daemon=True).start()

    # --- Стандартные методы (поиск, запуск, сохранение) ---
    def _search_mods(self):
        query = self.mod_search_entry.get().strip()
        if not query: return
        for widget in self.mods_scroll.winfo_children(): widget.destroy()
        ctk.CTkLabel(self.mods_scroll, text="Поиск...", text_color=MUTED).pack(pady=20)
        
        def fetch():
            try:
                url = f"{MODRINTH_API}/search?query={query}&limit=10&facets=[[\"project_type:mod\"]]"
                headers = {"User-Agent": "Mozilla/5.0"}
                r = requests.get(url, headers=headers, timeout=15)
                data = r.json()
                for widget in self.mods_scroll.winfo_children(): widget.destroy()
                self.after(0, lambda: self._display_mods(data.get("hits", [])))
            except Exception as e:
                if self.mods_scroll.winfo_children():
                    self.after(0, lambda: self.mods_scroll.winfo_children()[0].configure(text=f"Ошибка: {e}"))
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
            ctk.CTkLabel(text_frame, text=mod.get("title", ""), font=("Segoe UI", 14, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
            desc = mod.get("description", "")
            ctk.CTkLabel(text_frame, text=desc[:80] + "..." if len(desc) > 80 else desc, font=("Segoe UI", 11), text_color=MUTED, anchor="w").pack(anchor="w")
            
            ctk.CTkButton(card, text="Скачать", width=100, height=32, fg_color=ACCENT, command=lambda s=mod["slug"]: self._download_mod(s)).pack(side="right", padx=15)

    def _load_mod_icon(self, url, card, label):
        def fetch():
            try:
                r = requests.get(url, timeout=5)
                img = Image.open(BytesIO(r.content))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(48, 48))
                card._icon = ctk_img
                self.after(0, lambda: label.configure(image=ctk_img))
            except: pass
        threading.Thread(target=fetch, daemon=True).start()

    def _download_mod(self, slug):
        def fetch():
            try:
                ver = self.version_dict.get(self.selected_version.get(), "")
                loader = "fabric" if "fabric" in ver.lower() else ("forge" if "forge" in ver.lower() else None)
                match = re.search(r'(\d+\.\d+(\.\d+)?)', ver)
                game_ver = match.group(1) if match else None

                params = {}
                if game_ver: params["game_versions"] = json.dumps([game_ver])
                if loader: params["loaders"] = json.dumps([loader])

                r = requests.get(f"{MODRINTH_API}/project/{slug}/version", params=params, timeout=15)
                versions = r.json()
                if not versions:
                    self.after(0, lambda: self._show_toast("Нет версий под эту сборку!"))
                    return
                
                download_url = versions[0]["files"][0]["url"]
                filename = versions[0]["files"][0]["filename"]
                
                mods_dir = os.path.join(self.minecraft_dir, "mods")
                os.makedirs(mods_dir, exist_ok=True)
                with requests.get(download_url, stream=True) as r_file:
                    with open(os.path.join(mods_dir, filename), "wb") as f:
                        for chunk in r_file.iter_content(8192): f.write(chunk)
                self.after(0, lambda: self._show_toast(f"{filename} скачан!"))
            except Exception as e:
                self.after(0, lambda: self._show_toast("Ошибка скачивания"))
        threading.Thread(target=fetch, daemon=True).start()

    def _show_toast(self, text):
        self.title(f"FireLauncher - {text}")
        self.after(3000, lambda: self.title("FireLauncher v2.0.3"))

    def _open_mods_dir(self):
        mods_dir = os.path.join(self.minecraft_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)
        os.startfile(mods_dir)

    def _save_config(self):
        config = {
            "version": self.selected_version.get(),
            "minecraft_dir": self.minecraft_dir,
            "ram": self.ram_value.get(),
            "jvm_args": self.jvm_args_entry.get().strip(),
            "username": self.current_account["username"] if self.current_account else None,
            "uuid": self.current_account["uuid"] if self.current_account else None
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
                self._download_avatar(self.current_account["username"])
            if config.get("minecraft_dir"):
                self.minecraft_dir = config["minecraft_dir"]
                self.folder_label.configure(text=self.minecraft_dir)
            if config.get("ram"):
                self.ram_value.set(config["ram"])
                self.ram_slider.set(config["ram"])
                self.ram_label.configure(text=f"{config['ram']} ГБ")
            if config.get("jvm_args"):
                self.jvm_args_entry.insert(0, config["jvm_args"])
            self._saved_version = config.get("version", "")
        except: pass

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

    def ely_login(self):
        username, password = self.ely_user.get().strip(), self.ely_pass.get().strip()
        if not username or not password:
            self.acc_status.configure(text="Заполни логин и пароль", text_color="#ff5c5c")
            return
        self.acc_status.configure(text="Вход...", text_color=MUTED)
        threading.Thread(target=self._ely_login_thread, args=(username, password), daemon=True).start()

    def _ely_login_thread(self, username, password):
        try:
            r = requests.post(ELY_AUTH_URL, json={"username": username, "password": password, "clientToken": "firelauncher", "requestUser": True}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                profile = data.get("selectedProfile", {})
                self.current_account = {"username": profile.get("name", username), "uuid": profile.get("id", ""), "token": data.get("accessToken", "0")}
                self.after(0, lambda: self.user_label.configure(text=self.current_account["username"]))
                self.after(0, lambda: self.acc_status.configure(text="Успешный вход!", text_color="#3ddc84"))
                self._download_avatar(self.current_account["username"])
                self._save_config()
                self.after(0, lambda: self._show_frame("play"))
            else:
                err = r.json().get("errorMessage", "Неверный логин")
                self.after(0, lambda: self.acc_status.configure(text=err, text_color="#ff5c5c"))
        except Exception as e:
            self.after(0, lambda: self.acc_status.configure(text=f"Ошибка: {e}", text_color="#ff5c5c"))

    def _download_avatar(self, nickname):
        def fetch():
            try:
                req = urllib.request.Request(f"http://skinsystem.ely.by/skins/{nickname}.png", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response: img_data = response.read()
                img = Image.open(BytesIO(img_data))
                head = img.crop((8, 8, 16, 16)).resize((64, 64), Image.Resampling.NEAREST)
                ctk_img = ctk.CTkImage(light_image=head, dark_image=head, size=(48, 48))
                self.after(0, lambda: self.avatar_label.configure(image=ctk_img, text=""))
                self.avatar_image = ctk_img
            except: pass
        threading.Thread(target=fetch, daemon=True).start()

    def _filter_versions(self, *args):
        query = self.search_var.get().lower()
        if not query:
            self.version_menu.configure(values=self.all_versions_list)
            return
        filtered = [v for v in self.all_versions_list if query in v.lower()]
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
            all_v = []
            for v in versions:
                if v["type"] in ("release", "snapshot"):
                    display = v["id"] + (" (Snapshot)" if v["type"] == "snapshot" else "")
                    self.version_dict[display] = v["id"]
                    all_v.append(display)
            
            local_dir = os.path.join(self.minecraft_dir, "versions")
            if os.path.exists(local_dir):
                for folder in os.listdir(local_dir):
                    if ("fabric" in folder.lower() or "forge" in folder.lower()) and folder not in self.version_dict:
                        json_path = os.path.join(local_dir, folder, f"{folder}.json")
                        if os.path.exists(json_path):
                            self.version_dict[folder] = folder
                            all_v.append(folder)
            
            self.all_versions_list = all_v
            self.after(0, lambda: self.version_menu.configure(values=all_v))
            self.after(0, lambda: self.build_version_menu.configure(values=all_v))
            if all_v:
                self.after(0, lambda: self.selected_version.set(all_v[0]))
                self.after(0, lambda: self.build_version_var.set(all_v[0]))
                if hasattr(self, "_saved_version") and self._saved_version in self.version_dict:
                    self.after(0, lambda: self.selected_version.set(self._saved_version))
                    self.after(0, lambda: self._on_version_change(self._saved_version))
        except Exception as e:
            self.after(0, lambda: self.desc_label.configure(text=f"Ошибка версий: {e}"))

    def _update_notes(self, text):
        self.notes_textbox.configure(state="normal")
        self.notes_textbox.delete("1.0", "end")
        self.notes_textbox.insert("1.0", text)
        self.notes_textbox.configure(state="disabled")

    def _install_mod_loader(self, loader_type):
        ver = self.version_dict.get(self.build_version_var.get(), "")
        if not ver:
            self.build_status.configure(text="Выберите версию!", text_color="#ff5c5c")
            return
        self.build_status.configure(text=f"Установка {loader_type}...", text_color=MUTED)
        def install():
            try:
                if loader_type == "fabric": minecraft_launcher_lib.mod_loader.get_mod_loader("fabric").install(ver, self.minecraft_dir)
                elif loader_type == "forge": minecraft_launcher_lib.mod_loader.get_mod_loader("forge").install(ver, self.minecraft_dir)
                self.after(0, lambda: self.build_status.configure(text="Установлено!", text_color="#3ddc84"))
                self.after(0, self._load_versions)
            except Exception as e: self.after(0, lambda: self.build_status.configure(text=f"Ошибка: {e}", text_color="#ff5c5c"))
        threading.Thread(target=install, daemon=True).start()

    def _delete_selected_version(self):
        ver = self.version_dict.get(self.build_version_var.get(), "")
        if not ver or ("fabric" not in ver.lower() and "forge" not in ver.lower()):
            self.build_status.configure(text="Выберите модлоадер!", text_color="#ff5c5c")
            return
        path = os.path.join(self.minecraft_dir, "versions", ver)
        if os.path.exists(path):
            shutil.rmtree(path)
            self.build_status.configure(text="Удалено!", text_color="#3ddc84")
            self._load_versions()

    def repair_game(self):
        ver = self.version_dict.get(self.selected_version.get(), "")
        if not ver: return
        self.desc_label.configure(text=f"Починка {ver}...")
        idx_dir = os.path.join(self.minecraft_dir, "assets", "indexes")
        if os.path.isdir(idx_dir):
            for f in os.listdir(idx_dir):
                try: os.remove(os.path.join(idx_dir, f))
                except: pass
        version_path = os.path.join(self.minecraft_dir, "versions", ver)
        if os.path.exists(version_path): shutil.rmtree(version_path, ignore_errors=True)
        self.desc_label.configure(text="Кэш очищен. Нажми Играть.", text_color=MUTED)

    def _update_progress(self, current, total=None):
        if total and total > 0:
            self.after(0, lambda: self.progress_bar.set(current / total))

    def _run_game_logic(self):
        try:
            ver = self.version_dict.get(self.selected_version.get(), "")
            if not ver: raise ValueError("Версия не выбрана")

            self.after(0, lambda: self.progress_label.pack(anchor="center"))
            self.after(0, lambda: self.progress_bar.pack(anchor="center"))
            self.after(0, lambda: self.play_btn.configure(text="Установка...", state="disabled"))

            # 2. Автоматическая установка Java (встроено в install_minecraft_version)
            def safe_status(t): self.after(0, lambda: self.progress_label.configure(text=t))
            callback = {"setStatus": safe_status, "setProgress": self._update_progress, "setMax": lambda m: None}
            minecraft_launcher_lib.install.install_minecraft_version(ver, self.minecraft_dir, callback=callback)

            jvm_args = [f"-Xmx{self.ram_value.get()}G", "-Xms2G"]
            if self.jvm_args_entry.get().strip():
                jvm_args.extend(self.jvm_args_entry.get().strip().split())

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
                subprocess.Popen(command, cwd=self.minecraft_dir, stdout=log, stderr=log)
        except Exception as e:
            self.after(0, lambda: self.desc_label.configure(text=f"Ошибка: {e}", text_color="#ff5c5c"))
        finally:
            self.after(0, lambda: self.play_btn.configure(text="▶ ИГРАТЬ", state="normal"))
            self.after(0, lambda: self.progress_bar.pack_forget())
            self.after(0, lambda: self.progress_label.pack_forget())
            self.is_installing = False

    def start_game(self):
        if self.is_installing: return
        self.is_installing = True
        threading.Thread(target=self._run_game_logic, daemon=True).start()

if __name__ == "__main__":
    app = FireLauncher()
    app.protocol("WM_DELETE_WINDOW", lambda: (app._save_config(), app.destroy()))
    app.mainloop()