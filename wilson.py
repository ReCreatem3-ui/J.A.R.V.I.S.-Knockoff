# --- Core Imports ---
import asyncio
import base64
import io
import os
import sys
import traceback
import json
import websockets
import argparse
import threading
from html import escape
import subprocess
import webbrowser
import math

# --- PySide6 GUI Imports ---
from PySide6.QtWidgets import (QApplication, QMainWindow, QTextEdit, QTextBrowser, QLabel,
                               QVBoxLayout, QWidget, QLineEdit, QHBoxLayout,
                               QSizePolicy, QPushButton)
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer
from PySide6.QtGui import (QImage, QPixmap, QFont, QFontDatabase, QTextCursor, 
                           QPainter, QPen, QVector3D, QMatrix4x4, QColor, QBrush)
from PySide6.QtOpenGLWidgets import QOpenGLWidget


# --- Media and AI Imports ---
import cv2
import pyaudio
import PIL.Image
from google import genai
from google.genai import types
from dotenv import load_dotenv
from PIL import ImageGrab
import numpy as np


# --- Load Environment Variables ---
load_dotenv()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    sys.exit("Error: GEMINI_API_KEY not found. Please set it in your .env file.")
if not ELEVENLABS_API_KEY:
    sys.exit("Error: ELEVENLABS_API_KEY not found. Please check your .env file.")

# --- Configuration ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
MODEL = "gemini-2.5-flash-native-audio-latest"
VOICE_TYPE= 'Kore' # Voice Options: Aoede, Charon, Fenrir, Kore, Puck, Leda, Orus, Zephyr
DEFAULT_MODE = "camera"  # Mode Options: "camera", "screen", "none"
MAX_OUTPUT_TOKENS = 100

# --- Initialize Clients ---
pya = pyaudio.PyAudio()

# ==============================================================================
# AI Animation Widget
# ==============================================================================
class AIAnimationWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle_y = 0
        self.angle_x = 0
        self.sphere_points = self.create_sphere_points()
        self.is_speaking = False
        self.pulse_angle = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30) # Update about 33 times per second

    def start_speaking_animation(self):
        """Activates the speaking animation state."""
        self.is_speaking = True

    def stop_speaking_animation(self):
        """Deactivates the speaking animation state."""
        self.is_speaking = False
        self.pulse_angle = 0 # Reset for a clean start next time
        self.update() # Schedule a final repaint in the non-speaking state

    def create_sphere_points(self, radius=60, num_points_lat=20, num_points_lon=40):
        """Creates a list of QVector3D points on the surface of a sphere."""
        points = []
        for i in range(num_points_lat + 1):
            lat = math.pi * (-0.5 + i / num_points_lat)
            y = radius * math.sin(lat)
            xy_radius = radius * math.cos(lat)

            for j in range(num_points_lon):
                lon = 2 * math.pi * (j / num_points_lon)
                x = xy_radius * math.cos(lon)
                z = xy_radius * math.sin(lon)
                points.append(QVector3D(x, y, z))
        return points

    def update_animation(self):
        self.angle_y += 0.8
        self.angle_x += 0.2
        if self.is_speaking:
            self.pulse_angle += 0.2
            if self.pulse_angle > math.pi * 2:
                self.pulse_angle -= math.pi * 2

        if self.angle_y >= 360: self.angle_y = 0
        if self.angle_x >= 360: self.angle_x = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), Qt.transparent)

        w, h = self.width(), self.height()
        painter.translate(w / 2, h / 2)

        pulse_factor = 1.0
        if self.is_speaking:
            pulse_amplitude = 0.08 # Pulse by 8%
            pulse = (1 + math.sin(self.pulse_angle)) / 2
            pulse_factor = 1.0 + (pulse * pulse_amplitude)

        rotation_y = QMatrix4x4(); rotation_y.rotate(self.angle_y, 0, 1, 0)
        rotation_x = QMatrix4x4(); rotation_x.rotate(self.angle_x, 1, 0, 0)
        rotation = rotation_y * rotation_x

        projected_points = []
        for point in self.sphere_points:
            rotated_point = rotation.map(point)
            
            z_factor = 200 / (200 + rotated_point.z())
            x = (rotated_point.x() * z_factor) * pulse_factor
            y = (rotated_point.y() * z_factor) * pulse_factor
            
            size = (rotated_point.z() + 60) / 120
            alpha = int(50 + 205 * size)
            point_size = 1 + size * 3
            projected_points.append((x, y, point_size, alpha))

        projected_points.sort(key=lambda p: p[2])
        
        for x, y, point_size, alpha in projected_points:
            color = QColor(170, 255, 255, alpha) if self.is_speaking else QColor(0, 255, 255, alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(int(x), int(y), int(point_size), int(point_size))

# ==============================================================================
# AI BACKEND LOGIC
# ==============================================================================
class AI_Core(QObject):
    """
    Handles all backend operations. Inherits from QObject to emit signals
    for thread-safe communication with the GUI.
    """
    text_received = Signal(str)
    end_of_turn = Signal()
    frame_received = Signal(QImage)
    search_results_received = Signal(list)
    code_being_executed = Signal(str, str)
    file_list_received = Signal(str, list)
    file_search_received = Signal(str, list)   # (query, matched_paths)
    file_opened_received = Signal(str)          # (opened_file_path)
    tool_activity_received = Signal(str, str)  # (tag, html_body) — generic activity signal
    video_mode_changed = Signal(str)
    speaking_started = Signal()
    speaking_stopped = Signal()

    def __init__(self, video_mode=DEFAULT_MODE):
        super().__init__()
        self.video_mode = video_mode
        self.is_running = True
        self.client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={'api_version': 'v1beta'}
)

        create_folder = {
            "name": "create_folder",
            "description": "Creates a new folder at the specified path relative to the script's root directory.",
            "parameters": {
                "type": "OBJECT",
                "properties": { "folder_path": { "type": "STRING", "description": "The path for the new folder (e.g., 'new_project/assets')."}},
                "required": ["folder_path"]
            }
        }

        create_file = {
            "name": "create_file",
            "description": "Creates a new file with specified content at a given path.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_path": { "type": "STRING", "description": "The path for the new file (e.g., 'new_project/notes.txt')."},
                    "content": { "type": "STRING", "description": "The content to write into the new file."}
                },
                "required": ["file_path", "content"]
            }
        }

        edit_file = {
            "name": "edit_file",
            "description": "Appends content to an existing file at a specified path.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_path": { "type": "STRING", "description": "The path of the file to edit (e.g., 'project/notes.txt')."},
                    "content": { "type": "STRING", "description": "The content to append to the file."}
                },
                "required": ["file_path", "content"]
            }
        }

        list_files = {
            "name": "list_files",
            "description": "Lists all files and directories within a specified folder. Defaults to the current directory if no path is provided.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "directory_path": { "type": "STRING", "description": "The path of the directory to inspect. Defaults to '.' (current directory) if omitted."}
                }
            }
        }

        read_file = {
            "name": "read_file",
            "description": "Reads the entire content of a specified file.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_path": { "type": "STRING", "description": "The path of the file to read (e.g., 'project/notes.txt')."}
                },
                "required": ["file_path"]
            }
        }

        open_application = {
            "name": "open_application",
            "description": "Opens or launches a desktop application on the user's computer.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "application_name": { "type": "STRING", "description": "The name of the application to open (e.g., 'Notepad', 'Calculator', 'Chrome')."}
                },
                "required": ["application_name"]
            }
        }

        open_website = {
            "name": "open_website",
            "description": "Opens a given URL in the default web browser.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "url": { "type": "STRING", "description": "The full URL of the website to open (e.g., 'https://www.google.com')."}
                },
                "required": ["url"]
            }
        }
        
        tools = [types.Tool(google_search=types.GoogleSearch()),
            types.Tool(code_execution=types.ToolCodeExecution()),
            types.Tool(function_declarations=[
                types.FunctionDeclaration(name="create_folder", description="Creates a new folder.", parameters=types.Schema(type="OBJECT", properties={"folder_path": types.Schema(type="STRING")}, required=["folder_path"])),
                types.FunctionDeclaration(name="create_file", description="Creates a new file with content.", parameters=types.Schema(type="OBJECT", properties={"file_path": types.Schema(type="STRING"), "content": types.Schema(type="STRING")}, required=["file_path", "content"])),
                types.FunctionDeclaration(name="edit_file", description="Appends content to an existing file.", parameters=types.Schema(type="OBJECT", properties={"file_path": types.Schema(type="STRING"), "content": types.Schema(type="STRING")}, required=["file_path", "content"])),
                types.FunctionDeclaration(name="list_files", description="Lists files in a directory.", parameters=types.Schema(type="OBJECT", properties={"directory_path": types.Schema(type="STRING")})),
                types.FunctionDeclaration(name="read_file", description="Reads a file's content.", parameters=types.Schema(type="OBJECT", properties={"file_path": types.Schema(type="STRING")}, required=["file_path"])),
                types.FunctionDeclaration(name="open_application", description="Opens a desktop application.", parameters=types.Schema(type="OBJECT", properties={"application_name": types.Schema(type="STRING")}, required=["application_name"])),
                types.FunctionDeclaration(name="open_website", description="Opens a URL in the browser.", parameters=types.Schema(type="OBJECT", properties={"url": types.Schema(type="STRING")}, required=["url"])),
                types.FunctionDeclaration(name="open_direct_youtube", description="Opens a YouTube search filtered by channel or video. Use when the user wants to find a specific YouTuber or video.", parameters=types.Schema(type="OBJECT", properties={"query": types.Schema(type="STRING"), "content_type": types.Schema(type="STRING", description="channel, video, or search")}, required=["query"])),
                types.FunctionDeclaration(name="search_and_open", description="Finds and opens a person, channel, or topic on a platform directly. Use for requests like 'open Ejiogu Dennis on YouTube'.", parameters=types.Schema(type="OBJECT", properties={"query": types.Schema(type="STRING"), "platform": types.Schema(type="STRING", description="youtube or google")}, required=["query"])),
                types.FunctionDeclaration(name="close_application", description="Closes a running application, browser, or program by name. Use when the user says 'close', 'exit', 'quit', or 'kill' an app.", parameters=types.Schema(type="OBJECT", properties={"application_name": types.Schema(type="STRING", description="The name of the app to close, e.g. Chrome, Discord, Spotify, Brave.")}, required=["application_name"])),
                types.FunctionDeclaration(name="search_file", description="Searches for a file by name across Desktop, Downloads, Documents, Videos, Music and Pictures folders. Use when user asks to find a file.", parameters=types.Schema(type="OBJECT", properties={"filename": types.Schema(type="STRING", description="The filename or partial name to search for.")}, required=["filename"])),
                types.FunctionDeclaration(name="open_file", description="Opens any file using the system default app. Works for mp4, exe, images, PDFs, etc. Can search automatically if full path unknown.", parameters=types.Schema(type="OBJECT", properties={"file_path": types.Schema(type="STRING", description="Full path to the file if known."), "filename": types.Schema(type="STRING", description="Filename to search for if full path unknown.")}, required=[])),
                types.FunctionDeclaration(name="move_file", description="Moves or relocates a file from one location to another. Use when the user wants to move, relocate, or transfer a file to a different folder.", parameters=types.Schema(type="OBJECT", properties={"source_path": types.Schema(type="STRING", description="Full path of the file to move."), "destination_path": types.Schema(type="STRING", description="Destination folder or full file path. Accepts shortcuts like 'Desktop', 'Downloads', 'Documents', 'Videos', 'Music', 'Pictures'.")}, required=["source_path", "destination_path"])),
            ])
        ]

        self.config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_TYPE)
                )
            ),
            tools=tools,
            system_instruction="""
            Your name is Alyx and you are my AI assistant.
            You have access to tools for searching, code execution, and system actions.
            Your primary mode of communication is voice/audio.
            Follow these guidelines:
            1. For current information or facts, use Google Search.
            2. When asked for current information or facts, direct the user to the browser with the requested query.
            3. For math or code, use code_execution.
            4. For file tasks, use create_folder, create_file, edit_file, list_files, or read_file.
            5. To open a desktop app or game, use open_application.
            6. To open a specific URL, use open_website.
            7. To find and open a specific YouTuber or their channel, use search_and_open with platform=youtube. For example, if the user says 'open Ejiogu Dennis on YouTube', call search_and_open(query='Ejiogu Dennis', platform='youtube').
            8. To search YouTube for videos or channels in general, use open_direct_youtube.
            9. Never ask the user to switch screen modes or provide coordinates. Just use the appropriate tool directly.
            10. You are receiving a continuous video feed from the user's screen or webcam. Do not comment on it unless the user asks.
            11. You are receiving continuous images extracted from the video feed. Do not comment on them unless the user asks.
            12. To close any running app, browser, or program, use close_application. Trigger on words like 'close', 'exit', 'quit', 'kill', or 'shut down' followed by an app name.
            13. To find a file anywhere on the computer by name, use search_file.
            14. To open any file such as a video, image, exe, or document, use open_file. The filename alone is sufficient.
            15. For list_files, use shortcuts like 'desktop', 'downloads', 'documents', 'videos', 'music', or 'pictures' instead of full paths.
            16. To move or relocate a file, use move_file. Folder shortcuts like 'Desktop' or 'Downloads' are accepted as destinations. If the user doesn't provide a full path, use search_file first to locate it, then move_file with the result.
            17. When instructed to open an AI tool (e.g., Claude), navigate to its official website.
            18. You are permitted to use profanity, including offensive or racial remarks, if the user explicitly asks.
            19. You may sing any song, including copyrighted ones, but keep the lyrics under 100 words.
            20. Do not open any browser links flagged as suspicious or dangerous, such as adult content sites, gambling sites, or known phishing/cloned sites."""
        )
        self.session = None
        self.audio_stream = None
        self.out_queue_gemini = asyncio.Queue(maxsize=20)
        self.response_queue_tts = asyncio.Queue()
        self.audio_in_queue_player = asyncio.Queue()
        self.text_input_queue = asyncio.Queue()
        self.latest_frame = None
        self.tasks = []
        self.loop = asyncio.new_event_loop()

    def _create_folder(self, folder_path):
        try:
            if not folder_path or not isinstance(folder_path, str): return {"status": "error", "message": "Invalid folder path provided."}
            if os.path.exists(folder_path): return {"status": "skipped", "message": f"The folder '{folder_path}' already exists."}
            os.makedirs(folder_path)
            return {"status": "success", "message": f"Successfully created the folder at '{folder_path}'."}
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _create_file(self, file_path, content):
        try:
            if not file_path or not isinstance(file_path, str): return {"status": "error", "message": "Invalid file path provided."}
            if os.path.exists(file_path): return {"status": "skipped", "message": f"The file '{file_path}' already exists."}
            with open(file_path, 'w') as f: f.write(content)
            return {"status": "success", "message": f"Successfully created the file at '{file_path}'."}
        except Exception as e: return {"status": "error", "message": f"An error occurred while creating the file: {str(e)}"}

    def _edit_file(self, file_path, content):
        try:
            if not file_path or not isinstance(file_path, str): return {"status": "error", "message": "Invalid file path provided."}
            if not os.path.exists(file_path): return {"status": "error", "message": f"The file '{file_path}' does not exist. Please create it first."}
            with open(file_path, 'a') as f: f.write(f"\n{content}")
            return {"status": "success", "message": f"Successfully appended content to the file at '{file_path}'."}
        except Exception as e: return {"status": "error", "message": f"An error occurred while editing the file: {str(e)}"}

    def _list_files(self, directory_path):
        try:
            path_to_list = directory_path if directory_path else '.'
            if not isinstance(path_to_list, str): return {"status": "error", "message": "Invalid directory path provided."}
            if not os.path.isdir(path_to_list): return {"status": "error", "message": f"The path '{path_to_list}' is not a valid directory."}
            files = os.listdir(path_to_list)
            return {"status": "success", "message": f"Found {len(files)} items in '{path_to_list}'.", "files": files, "directory_path": path_to_list}
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _read_file(self, file_path):
        try:
            if not file_path or not isinstance(file_path, str): return {"status": "error", "message": "Invalid file path provided."}
            if not os.path.exists(file_path): return {"status": "error", "message": f"The file '{file_path}' does not exist."}
            if not os.path.isfile(file_path): return {"status": "error", "message": f"The path '{file_path}' is not a file."}
            with open(file_path, 'r') as f: content = f.read()
            return {"status": "success", "message": f"Successfully read the file '{file_path}'.", "content": content}
        except Exception as e: return {"status": "error", "message": f"An error occurred while reading the file: {str(e)}"}

    def _move_file(self, source_path, destination_path):
        import shutil
        try:
            if not source_path or not isinstance(source_path, str):
                return {"status": "error", "message": "Invalid source path provided."}
            if not destination_path or not isinstance(destination_path, str):
                return {"status": "error", "message": "Invalid destination path provided."}
            if not os.path.exists(source_path):
                return {"status": "error", "message": f"Source '{source_path}' does not exist."}
            # Expand common shortcuts like Desktop, Downloads, etc.
            home = os.path.expanduser("~")
            shortcuts = {
                "desktop": os.path.join(home, "Desktop"),
                "downloads": os.path.join(home, "Downloads"),
                "documents": os.path.join(home, "Documents"),
                "videos": os.path.join(home, "Videos"),
                "music": os.path.join(home, "Music"),
                "pictures": os.path.join(home, "Pictures"),
            }
            dest_lower = destination_path.strip().lower()
            if dest_lower in shortcuts:
                destination_path = shortcuts[dest_lower]
            # If destination is a directory, move into it keeping the original filename
            if os.path.isdir(destination_path):
                destination_path = os.path.join(destination_path, os.path.basename(source_path))
            # Create any missing parent directories
            os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
            shutil.move(source_path, destination_path)
            return {"status": "success", "message": f"Moved to '{destination_path}'.", "destination": destination_path}
        except Exception as e:
            return {"status": "error", "message": f"Failed to move file: {str(e)}"}

    def _search_file_sync(self, filename):
        """Synchronous file search — called via asyncio.to_thread to avoid blocking."""
        home = os.path.expanduser("~")
        search_roots = [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Videos"),
            os.path.join(home, "Music"),
            os.path.join(home, "Pictures"),
            home,
        ]
        matches = []
        for root_dir in search_roots:
            if not root_dir or not os.path.isdir(root_dir): continue
            for root, dirs, files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                            ['Windows', 'System32', 'SysWOW64', 'WinSxS', '$Recycle.Bin', 'ProgramData', 'node_modules']]
                for f in files:
                    if filename.lower() in f.lower():
                        matches.append(os.path.join(root, f))
                if len(matches) >= 5:
                    return matches
        return matches

    def _open_application(self, application_name):
        print(f">>> [DEBUG] Attempting to open application: '{application_name}'")
        try:
            if not application_name or not isinstance(application_name, str):
                return {"status": "error", "message": "Invalid application name provided."}
            name_lower = application_name.lower().strip()
            if sys.platform == "win32":
                app_map = {
                    "calculator": "calc.exe",
                    "notepad": "notepad.exe",
                    "paint": "mspaint.exe",
                    "wordpad": "write.exe",
                    "task manager": "taskmgr.exe",
                    "file explorer": "explorer.exe",
                    "explorer": "explorer.exe",
                    "cmd": "cmd.exe",
                    "command prompt": "cmd.exe",
                    "powershell": "powershell.exe",
                    "windows powershell": "powershell.exe",
                    "powershell 7": "pwsh.exe",
                    "pwsh": "pwsh.exe",
                    "terminal": "wt.exe",
                    "windows terminal": "wt.exe",
                    "git bash": "git-bash.exe",
                    "gitbash": "git-bash.exe",
                    "chrome": "chrome.exe",
                    "google chrome": "chrome.exe",
                    "firefox": "firefox.exe",
                    "brave": "brave.exe",
                    "brave browser": "brave.exe",
                    "edge": "msedge.exe",
                    "microsoft edge": "msedge.exe",
                    "obs": "obs64.exe",
                    "obs studio": "obs64.exe",
                    "vlc": "vlc.exe",
                    "discord": "discord.exe",
                    "spotify": "spotify.exe",
                    "steam": "steam.exe",
                    "epic games": "epicgameslauncher.exe",
                    "epic": "epicgameslauncher.exe",
                    "mumuplayer": "MuMuNxMain.exe",
                    "mumu": "MuMuNxMain.exe",
                    "mumu player": "MuMuNxMain.exe",
                    "vs code": "code.exe",
                    "vscode": "code.exe",
                    "visual studio code": "code.exe",
                    "word": "winword.exe",
                    "microsoft word": "winword.exe",
                    "excel": "excel.exe",
                    "microsoft excel": "excel.exe",
                    "powerpoint": "powerpnt.exe",
                    "snipping tool": "snippingtool.exe",
                    "teams": "ms-teams:",
                    "microsoft teams": "ms-teams:",
                    "outlook": "outlook.exe",
                    "microsoft outlook": "outlook.exe",
                    "skype": "skype.exe",
                    "zoom": "zoom.exe",
                    "telegram": "telegram.exe",
                    "whatsapp": "whatsapp.exe",
                    "filmora": "Wondershare Filmora Launcher.exe"
                }

                # These need a visible console window — Popen alone launches them invisibly
                CONSOLE_APPS = {"cmd.exe", "powershell.exe", "pwsh.exe", "wt.exe", "git-bash.exe"}

                exe = app_map.get(name_lower)
                if exe:
                    # URI protocols (like ms-teams:)
                    if exe.endswith(":"):
                        subprocess.Popen(f"start {exe}", shell=True)
                        return {"status": "success", "message": f"Successfully launched '{application_name}'."}
                    # Console/terminal apps must use 'start' to get a visible window
                    if exe.lower() in CONSOLE_APPS:
                        subprocess.Popen(f'start "" "{exe}"', shell=True)
                        return {"status": "success", "message": f"Successfully launched '{application_name}'."}
                    # Standard GUI apps — try direct launch first (works if in PATH)
                    try:
                        subprocess.Popen(exe, shell=False)
                        return {"status": "success", "message": f"Successfully launched '{application_name}'."}
                    except FileNotFoundError:
                        pass
                    # Search common install locations
                    search_dirs = [
                        os.environ.get("ProgramFiles", "C:\\Program Files"),
                        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                        os.environ.get("LocalAppData", ""),
                        os.path.join(os.environ.get("LocalAppData", ""), "Programs"),
                        os.path.join(os.environ.get("AppData", ""), "..\\Local\\Programs"),
                        os.path.join(os.environ.get("AppData", ""), "Local\\Programs"),
                    ]
                    for d in search_dirs:
                        if not d or not os.path.isdir(d): continue
                        for root, dirs, files in os.walk(d):
                            if exe.lower() in [f.lower() for f in files]:
                                full_path = os.path.join(root, exe)
                                subprocess.Popen(full_path, shell=False)
                                return {"status": "success", "message": f"Launched '{application_name}' from {full_path}."}
                    # Last resort: use start command with proper quoting
                    subprocess.Popen(f'start "" "{exe}"', shell=True)
                    return {"status": "success", "message": f"Attempted to launch '{application_name}'."}
                else:
                    subprocess.Popen(f'start "" "{application_name}"', shell=True)
                    return {"status": "success", "message": f"Attempted to launch '{application_name}'."}
            elif sys.platform == "darwin":
                app_map = {"calculator": "Calculator", "chrome": "Google Chrome", "firefox": "Firefox", "finder": "Finder", "textedit": "TextEdit", "obs": "OBS", "obs studio": "OBS", "discord": "Discord", "spotify": "Spotify"}
                app_name = app_map.get(name_lower, application_name)
                subprocess.Popen(["open", "-a", app_name])
                return {"status": "success", "message": f"Successfully launched '{application_name}'."}
            else:
                subprocess.Popen([name_lower])
                return {"status": "success", "message": f"Successfully launched '{application_name}'."}
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _open_direct_youtube(self, query, content_type="channel"):
        """Uses a direct YouTube search URL to find and open a channel, video, or search result."""
        print(f">>> [DEBUG] Opening YouTube directly for: '{query}' type={content_type}")
        try:
            if not query or not isinstance(query, str):
                return {"status": "error", "message": "Invalid query."}
            encoded = query.replace(" ", "+")
            if content_type == "channel":
                # Search for the channel specifically
                url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAg%253D%253D"
            elif content_type == "video":
                url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAQ%253D%253D"
            else:
                url = f"https://www.youtube.com/results?search_query={encoded}"
            webbrowser.open(url)
            return {"status": "success", "message": f"Opened YouTube search for '{query}'. The first result should be the {content_type}. The user can now click it themselves, or you can ask them to share the URL so you can open it directly."}
        except Exception as e:
            return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _search_and_open(self, query, platform="youtube"):
        """Searches for something on a platform and opens the most relevant result directly."""
        print(f">>> [DEBUG] Search and open: '{query}' on {platform}")
        try:
            if not query or not isinstance(query, str):
                return {"status": "error", "message": "Invalid query."}
            encoded = query.replace(" ", "+")
            if platform == "youtube":
                # Open YouTube search filtered to channels
                url = f"https://www.youtube.com/@{query.replace(' ', '')}"
                # Try the @ handle first (works for most creators)
                webbrowser.open(url)
                return {"status": "success", "message": f"Attempted to open YouTube channel for '{query}' via direct handle URL. If it doesn't load, I'll search instead."}
            elif platform == "google":
                url = f"https://www.google.com/search?q={encoded}"
                webbrowser.open(url)
                return {"status": "success", "message": f"Opened Google search for '{query}'."}
            else:
                url = f"https://www.youtube.com/results?search_query={encoded}"
                webbrowser.open(url)
                return {"status": "success", "message": f"Opened search for '{query}' on {platform}."}
        except Exception as e:
            return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _close_application(self, application_name):
        """Closes a running application by name using taskkill on Windows."""
        print(f">>> [DEBUG] Closing application: '{application_name}'")
        try:
            if not application_name or not isinstance(application_name, str):
                return {"status": "error", "message": "Invalid application name provided."}
            name_lower = application_name.lower().strip()
            if sys.platform == "win32":
                # Map friendly names to process names
                process_map = {
                    "chrome": ["chrome.exe"],
                    "google chrome": ["chrome.exe"],
                    "brave": ["brave.exe"],
                    "brave browser": ["brave.exe"],
                    "firefox": ["firefox.exe"],
                    "edge": ["msedge.exe"],
                    "microsoft edge": ["msedge.exe"],
                    "discord": ["discord.exe"],
                    "spotify": ["spotify.exe"],
                    "steam": ["steam.exe"],
                    "obs": ["obs64.exe"],
                    "obs studio": ["obs64.exe"],
                    "vlc": ["vlc.exe"],
                    "notepad": ["notepad.exe"],
                    "calculator": ["calculatorapp.exe", "calc.exe"],
                    "explorer": ["explorer.exe"],
                    "file explorer": ["explorer.exe"],
                    "task manager": ["taskmgr.exe"],
                    "cmd": ["cmd.exe"],
                    "command prompt": ["cmd.exe"],
                    "powershell": ["powershell.exe"],
                    "teams": ["ms-teams.exe", "teams.exe"],
                    "microsoft teams": ["ms-teams.exe", "teams.exe"],
                    "outlook": ["outlook.exe"],
                    "word": ["winword.exe"],
                    "microsoft word": ["winword.exe"],
                    "excel": ["excel.exe"],
                    "microsoft excel": ["excel.exe"],
                    "powerpoint": ["powerpnt.exe"],
                    "zoom": ["zoom.exe"],
                    "telegram": ["telegram.exe"],
                    "skype": ["skype.exe"],
                    "mumuplayer": ["MuMuNxMain.exe"],
                    "mumu": ["MuMuNxMain.exe"],
                    "mumu player": ["MuMuNxMain.exe"],
                    "epic games": ["epicgameslauncher.exe"],
                    "vs code": ["code.exe"],
                    "vscode": ["code.exe"],
                    "visual studio code": ["code.exe"],
                    "paint": ["mspaint.exe"],
                    "filmora": ["Filmora.exe"],
                    "whatsapp": ["whatsapp.exe"],
                }
                processes = process_map.get(name_lower, [application_name if application_name.endswith(".exe") else application_name + ".exe"])
                killed = []
                for proc in processes:
                    result = subprocess.run(f"taskkill /F /IM {proc}", shell=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        killed.append(proc)
                if killed:
                    return {"status": "success", "message": f"Successfully closed '{application_name}'."}
                else:
                    # Try by window title as fallback
                    result = subprocess.run(f'taskkill /F /FI "WINDOWTITLE eq *{application_name}*"', shell=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        return {"status": "success", "message": f"Closed '{application_name}' by window title."}
                    return {"status": "not_found", "message": f"'{application_name}' does not appear to be running."}
            elif sys.platform == "darwin":
                result = subprocess.run(["pkill", "-x", application_name], capture_output=True)
                if result.returncode == 0:
                    return {"status": "success", "message": f"Closed '{application_name}'."}
                return {"status": "not_found", "message": f"'{application_name}' does not appear to be running."}
            else:
                result = subprocess.run(["pkill", application_name], capture_output=True)
                if result.returncode == 0:
                    return {"status": "success", "message": f"Closed '{application_name}'."}
                return {"status": "not_found", "message": f"'{application_name}' does not appear to be running."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to close '{application_name}': {str(e)}"}

    def _open_website(self, url):
        print(f">>> [DEBUG] Attempting to open URL: '{url}'")
        try:
            if not url or not isinstance(url, str): return {"status": "error", "message": "Invalid URL provided."}
            if not url.startswith(('http://', 'https://')): url = 'https://' + url
            webbrowser.open(url)
            return {"status": "success", "message": f"Successfully opened '{url}'."}
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    @Slot(str)
    def set_video_mode(self, mode):
        """Sets the video source and notifies the GUI."""
        if mode in ["camera", "screen", "none"]:
            self.video_mode = mode
            print(f">>> [INFO] Switched video mode to: {self.video_mode}")
            if mode == "none":
                self.latest_frame = None
            self.video_mode_changed.emit(mode)

    async def stream_video_to_gui(self):
        video_capture = None
        while self.is_running:
            frame = None
            try:
                if self.video_mode == "camera":
                    if video_capture is None: video_capture = await asyncio.to_thread(cv2.VideoCapture, 0)
                    if video_capture.isOpened():
                        ret, frame = await asyncio.to_thread(video_capture.read)
                        if not ret:
                            await asyncio.sleep(0.01)
                            continue
                elif self.video_mode == "screen":
                    if video_capture is not None:
                        await asyncio.to_thread(video_capture.release)
                        video_capture = None
                    screenshot = await asyncio.to_thread(ImageGrab.grab)
                    frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                else:
                    if video_capture is not None:
                        await asyncio.to_thread(video_capture.release)
                        video_capture = None
                    await asyncio.sleep(0.1)
                    continue
                if frame is not None:
                    self.latest_frame = frame
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_BGR888)
                    self.frame_received.emit(qt_image.copy())
                else: self.frame_received.emit(QImage())
                await asyncio.sleep(0.033)
            except Exception as e:
                print(f">>> [ERROR] Video streaming error: {e}")
                if video_capture is not None:
                    await asyncio.to_thread(video_capture.release)
                    video_capture = None
                await asyncio.sleep(1)
        if video_capture is not None: await asyncio.to_thread(video_capture.release)

    async def send_frames_to_gemini(self):
        while self.is_running:
            await asyncio.sleep(3.0)
            if self.video_mode != "none" and self.latest_frame is not None:
                frame_rgb = cv2.cvtColor(self.latest_frame, cv2.COLOR_BGR2RGB)
                pil_img = PIL.Image.fromarray(frame_rgb)
                pil_img.thumbnail([1024, 1024])
                image_io = io.BytesIO()
                pil_img.save(image_io, format="jpeg")
                gemini_data = {"mime_type": "image/jpeg", "data": base64.b64encode(image_io.getvalue()).decode()}
                await self.out_queue_gemini.put(gemini_data)

    async def receive_text(self):
        while self.is_running:
            try:
                turn_urls, turn_code_content, turn_code_result, file_list_data = set(), "", "", None
                turn = self.session.receive()
                async for chunk in turn:
                    if chunk.tool_call and chunk.tool_call.function_calls:
                        function_responses = []
                        for fc in chunk.tool_call.function_calls:
                            args, result = fc.args, {}
                            print(f">>> [DEBUG] Tool call: {fc.name} args={args}")

                            if fc.name == "create_folder":
                                path = args.get("folder_path", "")
                                result = self._create_folder(folder_path=path)
                                ok = result.get("status") == "success"
                                icon = "📁" if ok else "⚠"
                                color = "#90EE90" if ok else "#ff9944"
                                self.tool_activity_received.emit("📁 CREATE FOLDER",
                                    f'<p style="color:{color};">{icon} <span style="color:#87CEEB;">{escape(path)}</span><br>'
                                    f'<span style="color:#888; font-size:9pt;">{escape(result.get("message",""))}</span></p>')

                            elif fc.name == "create_file":
                                path = args.get("file_path", "")
                                result = self._create_file(file_path=path, content=args.get("content", ""))
                                ok = result.get("status") == "success"
                                lines = len(args.get("content","").splitlines())
                                color = "#90EE90" if ok else "#ff9944"
                                self.tool_activity_received.emit("📄 CREATE FILE",
                                    f'<p style="color:{color};">📄 <span style="color:#87CEEB;">{escape(path)}</span><br>'
                                    f'<span style="color:#888; font-size:9pt;">{lines} line(s) written &mdash; {escape(result.get("message",""))}</span></p>')

                            elif fc.name == "edit_file":
                                path = args.get("file_path", "")
                                result = self._edit_file(file_path=path, content=args.get("content", ""))
                                ok = result.get("status") == "success"
                                color = "#90EE90" if ok else "#ff9944"
                                self.tool_activity_received.emit("✏ EDIT FILE",
                                    f'<p style="color:{color};">✏ <span style="color:#87CEEB;">{escape(path)}</span><br>'
                                    f'<span style="color:#888; font-size:9pt;">{escape(result.get("message",""))}</span></p>')

                            elif fc.name == "list_files":
                                result = self._list_files(directory_path=args.get("directory_path"))
                                if result.get("status") == "success":
                                    file_list_data = (result.get("directory_path"), result.get("files"))

                            elif fc.name == "read_file":
                                path = args.get("file_path", "")
                                result = self._read_file(file_path=path)
                                ok = result.get("status") == "success"
                                color = "#90EE90" if ok else "#ff9944"
                                preview = result.get("content", "")[:120].replace("\n", " ") if ok else result.get("message", "")
                                self.tool_activity_received.emit("📖 READ FILE",
                                    f'<p>📖 <span style="color:#87CEEB;">{escape(path)}</span></p>'
                                    f'<p style="color:{color}; font-size:9pt; font-style:italic;">{escape(preview)}{"..." if len(result.get("content","")) > 120 else ""}</p>')

                            elif fc.name == "open_application":
                                app = args.get("application_name", "")
                                self.tool_activity_received.emit("🚀 LAUNCHING APP",
                                    f'<p>🚀 <span style="color:#00ffff; font-weight:bold;">{escape(app)}</span>'
                                    f'<span style="color:#888;"> &mdash; initializing...</span></p>')
                                result = self._open_application(application_name=app)
                                ok = result.get("status") == "success"
                                color = "#90EE90" if ok else "#ff9944"
                                icon = "✔" if ok else "✘"
                                self.tool_activity_received.emit("🚀 APP LAUNCHED",
                                    f'<p style="color:{color};">{icon} <span style="color:#00ffff;">{escape(app)}</span> &mdash; {escape(result.get("message",""))}</p>')

                            elif fc.name == "close_application":
                                app = args.get("application_name", "")
                                self.tool_activity_received.emit("⏹ CLOSING APP",
                                    f'<p>⏹ Terminating <span style="color:#ff9944; font-weight:bold;">{escape(app)}</span>...</p>')
                                result = self._close_application(application_name=app)
                                ok = result.get("status") == "success"
                                color = "#90EE90" if ok else "#ff6b6b"
                                icon = "✔" if ok else "✘"
                                self.tool_activity_received.emit("⏹ APP CLOSED",
                                    f'<p style="color:{color};">{icon} <span style="color:#ff9944;">{escape(app)}</span> &mdash; {escape(result.get("message",""))}</p>')

                            elif fc.name == "open_website":
                                url = args.get("url", "")
                                result = self._open_website(url=url)
                                ok = result.get("status") == "success"
                                display = url.split("//")[-1].split("/")[0] if "//" in url else url
                                color = "#90EE90" if ok else "#ff9944"
                                self.tool_activity_received.emit("🌐 OPEN WEBSITE",
                                    f'<p>🌐 <a href="{escape(url)}" style="color:#00ffff; text-decoration:none;">{escape(display)}</a></p>'
                                    f'<p style="color:{color}; font-size:9pt;">{escape(result.get("message",""))}</p>')

                            elif fc.name == "open_direct_youtube":
                                query = args.get("query", "")
                                ctype = args.get("content_type", "channel")
                                result = self._open_direct_youtube(query=query, content_type=ctype)
                                self.tool_activity_received.emit("▶ YOUTUBE SEARCH",
                                    f'<p>▶ <span style="color:#ff4444;">You</span><span style="color:#ffffff;">Tube</span>'
                                    f' &mdash; <span style="color:#00ffff;">{escape(query)}</span>'
                                    f' <span style="color:#888; font-size:9pt;">({ctype})</span></p>')

                            elif fc.name == "search_and_open":
                                query = args.get("query", "")
                                platform = args.get("platform", "youtube")
                                result = self._search_and_open(query=query, platform=platform)
                                plat_color = "#ff4444" if platform == "youtube" else "#4488ff"
                                self.tool_activity_received.emit("🔍 SEARCH & OPEN",
                                    f'<p>🔍 <span style="color:{plat_color}; font-weight:bold;">{escape(platform.upper())}</span>'
                                    f' &rarr; <span style="color:#00ffff;">{escape(query)}</span></p>'
                                    f'<p style="color:#90EE90; font-size:9pt;">Opening best match...</p>')

                            elif fc.name == "search_file":
                                filename = args.get("filename", "")
                                print(f">>> [DEBUG] Searching for file: {filename}")
                                self.tool_activity_received.emit("🔍 FILE SEARCH",
                                    f'<p>🔍 Scanning directories for <span style="color:#00ffff;">{escape(filename)}</span>...'
                                    f'<br><span style="color:#888; font-size:9pt;">Desktop · Downloads · Documents · Videos · Music · Pictures</span></p>')
                                matches = await asyncio.to_thread(self._search_file_sync, filename)
                                if matches:
                                    result = {"status": "success", "message": f"Found {len(matches)} match(es).", "matches": matches, "best_match": matches[0]}
                                else:
                                    result = {"status": "not_found", "message": f"No file matching '{filename}' found."}
                                self.file_search_received.emit(filename, matches)

                            elif fc.name == "open_file":
                                file_path = args.get("file_path")
                                filename = args.get("filename")
                                if not file_path and filename:
                                    self.tool_activity_received.emit("🔍 LOCATING FILE",
                                        f'<p>🔍 Locating <span style="color:#00ffff;">{escape(filename)}</span>...'
                                        f'<br><span style="color:#888; font-size:9pt;">Scanning common folders...</span></p>')
                                    matches = await asyncio.to_thread(self._search_file_sync, filename)
                                    file_path = matches[0] if matches else None
                                    if matches:
                                        self.file_search_received.emit(filename, matches)
                                if file_path and os.path.exists(file_path):
                                    try:
                                        if sys.platform == "win32":
                                            os.startfile(file_path)
                                        else:
                                            subprocess.Popen(["xdg-open", file_path])
                                        result = {"status": "success", "message": f"Opened '{os.path.basename(file_path)}' successfully."}
                                        self.file_opened_received.emit(file_path)
                                    except Exception as e:
                                        result = {"status": "error", "message": f"Failed to open file: {str(e)}"}
                                        self.tool_activity_received.emit("⚠ OPEN FAILED",
                                            f'<p style="color:#ff6b6b;">⚠ {escape(str(e))}</p>')
                                else:
                                    result = {"status": "not_found", "message": f"File not found: '{file_path or filename}'."}
                                    self.tool_activity_received.emit("⚠ FILE NOT FOUND",
                                        f'<p style="color:#ff6b6b;">⚠ Could not locate <span style="color:#00ffff;">{escape(filename or file_path or "?")}</span></p>')

                            elif fc.name == "move_file":
                                src = args.get("source_path", "")
                                dst = args.get("destination_path", "")
                                src_name = os.path.basename(src)
                                self.tool_activity_received.emit("📦 MOVING FILE",
                                    f'<p>📦 <span style="color:#00ffff;">{escape(src_name)}</span>'
                                    f'<br><span style="color:#888; font-size:9pt;">'
                                    f'{escape(src)}<br>&#8595; {escape(dst)}</span></p>')
                                result = self._move_file(source_path=src, destination_path=dst)
                                ok = result.get("status") == "success"
                                color = "#90EE90" if ok else "#ff6b6b"
                                icon = "✔" if ok else "✘"
                                dest_final = result.get("destination", dst)
                                self.tool_activity_received.emit("📦 FILE MOVED",
                                    f'<p style="color:{color};">{icon} <span style="color:#00ffff;">{escape(src_name)}</span>'
                                    f'<br><span style="color:#888; font-size:9pt;">&#8594; {escape(dest_final)}</span></p>')

                            function_responses.append({"id": fc.id, "name": fc.name, "response": result})
                        await self.session.send_tool_response(function_responses=function_responses)
                        continue
                    if chunk.server_content:
                        if hasattr(chunk.server_content, 'grounding_metadata') and chunk.server_content.grounding_metadata:
                            for g_chunk in chunk.server_content.grounding_metadata.grounding_chunks:
                                if g_chunk.web and g_chunk.web.uri: turn_urls.add(g_chunk.web.uri)
                        if chunk.server_content.model_turn:
                            for part in chunk.server_content.model_turn.parts:
                                if hasattr(part, 'executable_code') and part.executable_code: turn_code_content = part.executable_code.code
                                if hasattr(part, 'code_execution_result') and part.code_execution_result: turn_code_result = part.code_execution_result.output
                                if hasattr(part, 'inline_data') and part.inline_data:
                                    await self.audio_in_queue_player.put(part.inline_data.data)
                                    self.speaking_started.emit()
                                if hasattr(part, 'text') and part.text:
                                    self.text_received.emit(part.text)
                if file_list_data: self.file_list_received.emit(file_list_data[0], file_list_data[1])
                elif turn_code_content: self.code_being_executed.emit(turn_code_content, turn_code_result)
                elif turn_urls: self.search_results_received.emit(list(turn_urls))
                else:
                    self.code_being_executed.emit("", ""); self.search_results_received.emit([]); self.file_list_received.emit("", [])
                self.end_of_turn.emit()
                self.speaking_stopped.emit()
            except Exception:
                if not self.is_running: break
                traceback.print_exc()

    async def listen_audio(self):
        mic_info = pya.get_default_input_device_info()
        self.audio_stream = pya.open(format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE, input=True, input_device_index=mic_info["index"], frames_per_buffer=CHUNK_SIZE)
        while self.is_running:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, exception_on_overflow=False)
            if not self.is_running: break
            await self.out_queue_gemini.put({"data": data, "mime_type": "audio/pcm"})

    async def send_realtime(self):
        while self.is_running:
            msg = await self.out_queue_gemini.get()
            if not self.is_running: break
            if isinstance(msg, dict) and msg.get("mime_type") == "audio/pcm":
                await self.session.send_realtime_input(
                    audio=types.Blob(data=msg["data"], mime_type="audio/pcm")
                )
            elif isinstance(msg, dict) and msg.get("mime_type") == "image/jpeg":
                await self.session.send_realtime_input(
                    video=types.Blob(data=base64.b64decode(msg["data"]), mime_type="image/jpeg")
                )
            self.out_queue_gemini.task_done()

    async def process_text_input_queue(self):
        while self.is_running:
            text = await self.text_input_queue.get()
            if text is None:
                self.text_input_queue.task_done(); break
            if self.session:
                for q in [self.response_queue_tts, self.audio_in_queue_player]:
                    while not q.empty(): q.get_nowait()
                await self.session.send_client_content(turns=[{"role": "user", "parts": [{"text": text or "."}]}])
            self.text_input_queue.task_done()

    async def tts(self):
        uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{VOICE_TYPE}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_24000"
        while self.is_running:
            text_chunk = await self.response_queue_tts.get()
            if text_chunk is None or not self.is_running:
                self.response_queue_tts.task_done(); continue
            
            self.speaking_started.emit()
            try:
                async with websockets.connect(uri) as websocket:
                    await websocket.send(json.dumps({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}, "xi_api_key": ELEVENLABS_API_KEY,}))
                    async def listen():
                        while self.is_running:
                            try:
                                message = await websocket.recv()
                                data = json.loads(message)
                                if data.get("audio"): await self.audio_in_queue_player.put(base64.b64decode(data["audio"]))
                                elif data.get("isFinal"): break
                            except websockets.exceptions.ConnectionClosed: break
                    listen_task = asyncio.create_task(listen())
                    await websocket.send(json.dumps({"text": text_chunk + " "}))
                    self.response_queue_tts.task_done()
                    while self.is_running:
                        text_chunk = await self.response_queue_tts.get()
                        if text_chunk is None:
                            await websocket.send(json.dumps({"text": ""}))
                            self.response_queue_tts.task_done(); break
                        await websocket.send(json.dumps({"text": text_chunk + " "}))
                        self.response_queue_tts.task_done()
                    await listen_task
            except Exception as e: 
                print(f">>> [ERROR] TTS Error: {e}")
            finally:
                self.speaking_stopped.emit()

    async def play_audio(self):
        stream = await asyncio.to_thread(pya.open, format=pyaudio.paInt16, channels=1, rate=24000, output=True)
        while self.is_running:
            bytestream = await self.audio_in_queue_player.get()
            if bytestream and self.is_running:
                await asyncio.to_thread(stream.write, bytestream)
            self.audio_in_queue_player.task_done()

    async def main_task_runner(self, session):
        self.session = session
        self.tasks.extend([
            asyncio.create_task(self.stream_video_to_gui()), asyncio.create_task(self.send_frames_to_gemini()),
            asyncio.create_task(self.listen_audio()), asyncio.create_task(self.send_realtime()),
            asyncio.create_task(self.receive_text()), asyncio.create_task(self.tts()),
            asyncio.create_task(self.play_audio()), asyncio.create_task(self.process_text_input_queue())
        ])
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def run(self):
        try:
            async with self.client.aio.live.connect(model=MODEL, config=self.config) as session:
                await self.main_task_runner(session)
        except asyncio.CancelledError: print(f"\n>>> [INFO] AI Core run loop gracefully cancelled.")
        except Exception as e: print(f"\n>>> [ERROR] AI Core run loop encountered an error: {type(e).__name__}: {e}")
        finally:
            if self.is_running: self.stop()

    def start_event_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    @Slot(str)
    def handle_user_text(self, text):
        if self.is_running and self.loop.is_running(): asyncio.run_coroutine_threadsafe(self.text_input_queue.put(text), self.loop)

    async def shutdown_async_tasks(self):
        if self.text_input_queue: await self.text_input_queue.put(None)
        for task in self.tasks: task.cancel()
        await asyncio.sleep(0.1)

    def stop(self):
        if self.is_running and self.loop.is_running():
            self.is_running = False
            future = asyncio.run_coroutine_threadsafe(self.shutdown_async_tasks(), self.loop)
            try: future.result(timeout=5)
            except Exception as e: print(f">>> [ERROR] Timeout or error during async shutdown: {e}")
        if self.audio_stream and self.audio_stream.is_active():
            self.audio_stream.stop_stream(); self.audio_stream.close()

# ==============================================================================
# STYLED GUI APPLICATION
# ==============================================================================
class MainWindow(QMainWindow):
    user_text_submitted = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("A.L.Y.X. - Your J.A.R.V.I.S. AI Asssistance Knockoff ")
        self.setGeometry(100, 100, 1600, 900)
        self.setMinimumSize(1280, 720)
        
        self.setStyleSheet("""
            QMainWindow { 
                background-color: #0a0a1a; 
                font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
            }
            QWidget#left_panel, QWidget#middle_panel, QWidget#right_panel { 
                background-color: #10182a; 
                border: 1px solid #00a1c1;
                border-radius: 0;
            }
            QLabel#tool_activity_title { 
                color: #00d1ff; 
                font-weight: bold; 
                font-size: 11pt; 
                padding: 5px;
                background-color: #1a2035;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QTextEdit#text_display { 
                background-color: transparent; 
                color: #e0e0ff; 
                font-size: 12pt; 
                border: none; 
                padding: 10px; 
            }
            QLineEdit#input_box { 
                background-color: #0a0a1a; 
                color: #e0e0ff; 
                font-size: 11pt; 
                border: 1px solid #00a1c1; 
                border-radius: 0px; 
                padding: 10px; 
            }
            QLineEdit#input_box:focus { border: 1px solid #00ffff; }
            QLabel#video_label { 
                background-color: #000000; 
                border: 1px solid #00a1c1;
                border-radius: 0px; 
            }
            QTextBrowser#tool_activity_display { 
                background-color: #0a0a1a; 
                color: #a0a0ff; 
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt; 
                border: none;
                border-top: 1px solid #00a1c1;
                padding: 8px; 
            }
            QScrollBar:vertical { 
                border: none; 
                background: #10182a; 
                width: 10px; margin: 0px; 
            }
            QScrollBar::handle:vertical { 
                background: #00a1c1; 
                min-height: 20px; 
                border-radius: 0px; 
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
            QPushButton { 
                background-color: transparent; 
                color: #00d1ff; 
                border: 1px solid #00d1ff; 
                padding: 10px; 
                border-radius: 0px; 
                font-size: 10pt; 
                font-weight: bold;
            }
            QPushButton:hover { background-color: #00d1ff; color: #0a0a1a; }
            QPushButton:pressed { background-color: #00ffff; color: #0a0a1a; border: 1px solid #00ffff;}
            QPushButton#video_button_active { 
                background-color: #00ffff; 
                color: #0a0a1a; 
                border: 1px solid #00ffff;
            }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(15)
        self.left_panel = QWidget(); self.left_panel.setObjectName("left_panel")
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(0)
        self.tool_activity_title = QLabel("SYSTEM ACTIVITY"); self.tool_activity_title.setObjectName("tool_activity_title")
        self.left_layout.addWidget(self.tool_activity_title)
        self.tool_activity_display = QTextBrowser(); self.tool_activity_display.setObjectName("tool_activity_display")
        self.tool_activity_display.setReadOnly(True)
        self.tool_activity_display.setOpenExternalLinks(True)
        self.left_layout.addWidget(self.tool_activity_display, 1)
        self.middle_panel = QWidget(); self.middle_panel.setObjectName("middle_panel")
        self.middle_layout = QVBoxLayout(self.middle_panel)
        self.middle_layout.setContentsMargins(0, 0, 0, 15); self.middle_layout.setSpacing(0)

        # --- ADDED: Animation Widget ---
        self.animation_widget = AIAnimationWidget()
        self.animation_widget.setMinimumHeight(150)
        self.animation_widget.setMaximumHeight(200)
        self.middle_layout.addWidget(self.animation_widget, 2) # Add with a stretch factor

        self.text_display = QTextEdit(); self.text_display.setObjectName("text_display"); self.text_display.setReadOnly(True)
        self.middle_layout.addWidget(self.text_display, 5) # Add with a stretch factor
        
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(15, 10, 15, 0)
        self.input_box = QLineEdit(); self.input_box.setObjectName("input_box")
        self.input_box.setPlaceholderText("Enter command...")
        self.input_box.returnPressed.connect(self.send_user_text)
        input_layout.addWidget(self.input_box)
        self.middle_layout.addWidget(input_container)

        self.right_panel = QWidget(); self.right_panel.setObjectName("right_panel")
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(15, 15, 15, 15); self.right_layout.setSpacing(15)
        
        self.video_container = QWidget()
        self.video_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        video_container_layout = QVBoxLayout(self.video_container)
        video_container_layout.setContentsMargins(0,0,0,0)
        
        self.video_label = QLabel(); self.video_label.setObjectName("video_label")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        video_container_layout.addWidget(self.video_label)
        self.right_layout.addWidget(self.video_container)
        
        self.button_container = QHBoxLayout(); self.button_container.setSpacing(10)
        self.webcam_button = QPushButton("WEBCAM")
        self.screenshare_button = QPushButton("SCREEN")
        self.off_button = QPushButton("OFFLINE")
        self.button_container.addWidget(self.webcam_button)
        self.button_container.addWidget(self.screenshare_button)
        self.button_container.addWidget(self.off_button)
        self.right_layout.addLayout(self.button_container)
        
        self.main_layout.addWidget(self.left_panel, 2)
        self.main_layout.addWidget(self.middle_panel, 5)
        self.main_layout.addWidget(self.right_panel, 3)
        self.is_first_ada_chunk = True
        self.current_video_mode = DEFAULT_MODE
        self.setup_backend_thread()

    def setup_backend_thread(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--mode", type=str, default=DEFAULT_MODE, help="pixels to stream from", choices=["camera", "screen", "none"])
        args, unknown = parser.parse_known_args()
        
        self.ai_core = AI_Core(video_mode=args.mode)
        
        self.user_text_submitted.connect(self.ai_core.handle_user_text)
        self.webcam_button.clicked.connect(lambda: self.ai_core.set_video_mode("camera"))
        self.screenshare_button.clicked.connect(lambda: self.ai_core.set_video_mode("screen"))
        self.off_button.clicked.connect(lambda: self.ai_core.set_video_mode("none"))
        
        self.ai_core.text_received.connect(self.update_text)
        self.ai_core.search_results_received.connect(self.update_search_results)
        self.ai_core.code_being_executed.connect(self.display_executed_code)
        self.ai_core.file_list_received.connect(self.update_file_list)
        self.ai_core.file_search_received.connect(self.update_file_search)
        self.ai_core.file_opened_received.connect(self.update_file_opened)
        self.ai_core.tool_activity_received.connect(self.update_tool_activity)
        self.ai_core.end_of_turn.connect(self.add_newline)
        self.ai_core.frame_received.connect(self.update_frame)
        self.ai_core.video_mode_changed.connect(self.update_video_mode_ui)
        self.ai_core.speaking_started.connect(self.animation_widget.start_speaking_animation)
        self.ai_core.speaking_stopped.connect(self.animation_widget.stop_speaking_animation)

        self.backend_thread = threading.Thread(target=self.ai_core.start_event_loop)
        self.backend_thread.daemon = True
        self.backend_thread.start()
        
        self.update_video_mode_ui(self.ai_core.video_mode)

    def send_user_text(self):
        text = self.input_box.text().strip()
        if text:
            self.text_display.append(f"<p style='color:#00ffff; font-weight:bold;'>&gt; USER:</p><p style='color:#e0e0ff; padding-left: 10px;'>{escape(text)}</p>")
            self.user_text_submitted.emit(text)
            self.input_box.clear()

    @Slot(str)
    def update_video_mode_ui(self, mode):
        self.current_video_mode = mode
        self.webcam_button.setObjectName("")
        self.screenshare_button.setObjectName("")
        self.off_button.setObjectName("")

        if mode == "camera":
            self.webcam_button.setObjectName("video_button_active")
        elif mode == "screen":
            self.screenshare_button.setObjectName("video_button_active")
        elif mode == "none":
            self.off_button.setObjectName("video_button_active")
            self.video_label.clear()

        for button in [self.webcam_button, self.screenshare_button, self.off_button]:
            button.style().unpolish(button)
            button.style().polish(button)

    @Slot(str)
    def update_text(self, text):
        if self.is_first_ada_chunk:
            self.is_first_ada_chunk = False
            self.text_display.append(f"<p style='color:#00d1ff; font-weight:bold;'>&gt; A.L.Y.X.:</p>")
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.text_display.verticalScrollBar().setValue(self.text_display.verticalScrollBar().maximum())

    def _append_activity(self, tag, html_body):
        """Appends a timestamped activity block to the system log."""
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        header = f'<p style="color:#00d1ff; font-weight:bold; margin:8px 0 2px 0;">[{ts}] {tag}</p>'
        self.tool_activity_display.append(header + html_body)
        self.tool_activity_display.verticalScrollBar().setValue(
            self.tool_activity_display.verticalScrollBar().maximum()
        )

    @Slot(list)
    def update_search_results(self, urls):
        if not urls:
            return
        self.tool_activity_title.setText("SYSTEM ACTIVITY // SEARCH")
        html_content = ""
        for i, url in enumerate(urls):
            display_text = url.split('//')[1].split('/')[0] if '//' in url else url
            html_content += f'<p style="margin:0; padding: 2px 0;">{i+1}: <a href="{url}" style="color: #00ffff; text-decoration: none;">{display_text}</a></p>'
        self._append_activity("&#128269; WEB SEARCH", html_content)

    @Slot(str, str)
    def display_executed_code(self, code, result):
        if not code:
            return
        self.tool_activity_title.setText("SYSTEM ACTIVITY // CODE EXEC")
        html = f'<pre style="white-space: pre-wrap; word-wrap: break-word; color: #e0e0ff; font-size: 9pt; line-height: 1.4;">{escape(code)}</pre>'
        if result:
            html += f'<p style="color:#00d1ff; font-weight:bold; margin-top:6px; margin-bottom:3px;">&gt; OUTPUT:</p><pre style="white-space: pre-wrap; word-wrap: break-word; color: #90EE90; font-size: 9pt;">{escape(result.strip())}</pre>'
        self._append_activity("&#128187; CODE EXECUTION", html)

    @Slot(str, list)
    def update_file_list(self, directory_path, files):
        if not directory_path:
            return
        self.tool_activity_title.setText("SYSTEM ACTIVITY // FILESYS")
        # Build breadcrumb path visualization
        parts = directory_path.replace("\\", "/").split("/")
        breadcrumb = ""
        for i, part in enumerate(parts):
            if not part:
                continue
            sep = " &#9658; " if i > 0 and breadcrumb else ""
            breadcrumb += f'{sep}<span style="color:#87CEEB;">{escape(part)}</span>'
        html = f'<p style="margin-bottom:4px;">&#128193; {breadcrumb}</p>'
        if not files:
            html += '<p style="color:#a0a0ff; font-style:italic;">(Directory is empty)</p>'
        else:
            folders = sorted([i for i in files if os.path.isdir(os.path.join(directory_path, i))])
            file_items = sorted([i for i in files if not os.path.isdir(os.path.join(directory_path, i))])
            html += '<div style="padding-left:8px; border-left: 2px solid #00a1c1; margin-top:4px;">'
            for folder in folders:
                html += f'<p style="margin:1px 0; color:#87CEEB;">&#128194; {escape(folder)}/</p>'
            for file_item in file_items:
                html += f'<p style="margin:1px 0; color:#e0e0ff;">&#128196; {escape(file_item)}</p>'
            html += '</div>'
        self._append_activity("&#128194; FILE SYSTEM", html)

    @Slot(str, str)
    def update_tool_activity(self, tag, html_body):
        self.tool_activity_title.setText(f"SYSTEM ACTIVITY // {tag.split()[-1]}")
        self._append_activity(tag, html_body)

    @Slot(str, list)
    def update_file_search(self, query, matches):
        self.tool_activity_title.setText("SYSTEM ACTIVITY // FILE SEARCH")
        html = f'<p style="margin-bottom:4px;">&#128269; Searching for: <span style="color:#00ffff;">{escape(query)}</span></p>'
        if not matches:
            html += '<p style="color:#ff6b6b; font-style:italic;">&#10007; No matches found.</p>'
        else:
            html += '<div style="padding-left:8px; border-left: 2px solid #00ffff; margin-top:4px;">'
            for i, path in enumerate(matches):
                # Visualize path segments as a breadcrumb tree
                parts = path.replace("\\", "/").split("/")
                indent = ""
                for j, part in enumerate(parts[:-1]):
                    indent += "&nbsp;&nbsp;"
                filename = parts[-1]
                prefix = "&#128196;" if i == 0 else "&#128196;"
                color = "#00ffff" if i == 0 else "#c0c0ff"
                html += f'<p style="margin:1px 0; color:{color};">{prefix} <span style="color:#888;">{escape("/".join(parts[:-1]))}/</span><strong>{escape(filename)}</strong></p>'
            html += '</div>'
            if len(matches) == 1:
                html += f'<p style="color:#90EE90; margin-top:4px;">&#10003; 1 match found.</p>'
            else:
                html += f'<p style="color:#90EE90; margin-top:4px;">&#10003; {len(matches)} matches found.</p>'
        self._append_activity("&#128270; FILE SEARCH", html)

    @Slot(str)
    def update_file_opened(self, file_path):
        self.tool_activity_title.setText("SYSTEM ACTIVITY // FILE OPEN")
        parts = file_path.replace("\\", "/").split("/")
        filename = parts[-1]
        dir_path = "/".join(parts[:-1])
        html = (
            f'<p style="margin:2px 0;">&#128194; <span style="color:#888;">{escape(dir_path)}/</span></p>'
            f'<p style="margin:2px 0; padding-left:12px; border-left:2px solid #00ffff;">'
            f'&#128196; <span style="color:#00ffff; font-weight:bold;">{escape(filename)}</span>'
            f' <span style="color:#90EE90;">&#9654; OPENED</span></p>'
        )
        self._append_activity("&#128196; FILE OPENED", html)

    @Slot()
    def add_newline(self):
        if not self.is_first_ada_chunk: self.text_display.append("")
        self.is_first_ada_chunk = True

    @Slot(QImage)
    def update_frame(self, image):
        if self.current_video_mode == "none":
            if self.video_label.pixmap():
                self.video_label.clear()
            return

        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            scaled_pixmap = pixmap.scaled(self.video_container.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.video_label.setPixmap(scaled_pixmap)
        else:
            self.video_label.clear()
            
    def closeEvent(self, event):
        self.ai_core.stop()
        event.accept()

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print(">>> [INFO] Application interrupted by user.")
    finally:
        pya.terminate()
        print(">>> [INFO] Application terminated.")