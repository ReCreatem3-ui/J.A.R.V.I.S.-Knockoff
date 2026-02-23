# A.L.Y.X. — Your J.A.R.V.I.S. AI Assistant Knockoff

> A personal AI desktop assistant inspired by **A.D.A.** by [Nazir Louis](https://github.com/nazirlouis/ada).  
> This is a modified and extended version built on top of the original concept. Full credit and inspiration goes to the original author.

---

## 🎥 Original Project

This project is heavily inspired by the work of **Nazir Louis**:

- 📺 YouTube Tutorial: [Watch here](https://www.youtube.com/watch?v=aooylKf-PeA&t=7s)
- 💻 Original Repository: [nazirlouis/ada](https://github.com/nazirlouis/ada)

Please check out and support the original creator.

---

## ✨ What's New in This Version

Built on top of the original A.D.A., A.L.Y.X. adds the following improvements:

- ✅ Upgraded to `gemini-2.5-flash-native-audio-latest` for native voice responses
- ✅ Voice selection via Gemini's built-in voices — no longer dependent on ElevenLabs for output
- ✅ Fixed audio playback pipeline for the native audio model
- ✅ Smarter app launching, closing & management — searches Program Files for executables and can shut them down on command (OBS, Discord, Brave, Steam, Epic Games, MuMuPlayer, and more)
- ✅ Enhanced file management — move, search, navigate, and control files via voice or text command
- ✅ Improved Live system activity log — visualizes what the AI is doing in real time (searches, file paths, code execution, app launches, etc.)
- ✅ YouTube channel/video search via direct URL and handle lookup
- ✅ `search_and_open` — finds and opens YouTubers or topics directly
- ✅ `browser_search` — supports Google, YouTube, and Bing
- ✅ Google Search and Code Execution tools re-integrated
- ✅ Video feed no longer triggers unprompted AI commentary
- ✅ Smart site launcher — say "open YouTube", "open Reddit", or "open GitHub" to navigate directly to official homepages
- ✅ YouTube-specific navigation — attempts direct `@handle` URL lookup before falling back to channel search
- ✅ `search_and_open` — resolves and opens YouTubers, creators, or topics directly on YouTube or Google
- ✅ `open_direct_youtube` — searches YouTube filtered by channel, video, or general query via direct URL
- ✅ Fallback behavior — unrecognized site names are passed as a Google search query automatically

---

## 🛠️ Requirements

Install dependencies with:

```bash
pip install PySide6 opencv-python pyaudio google-genai python-dotenv pillow numpy websockets pyautogui
```

---

## 🔑 Setup

1. Clone or download this repository
2. Create a `.env` file in the same folder as `alyx.py`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
```

> **Note:** ElevenLabs is no longer used for voice output in this version, but the key is still required by the code to start.

3. Run the assistant:

```bash
python wilson.py
```

---

## 📱 Adding Custom App Paths

A.L.Y.X. already knows how to launch common apps by name. If an app fails to open, you can register it manually in `alyx.py`.

Find the `app_map` dictionary inside `_open_application` (search for `app_map = {`) and add your app like this:

```python
"mumuplayer": r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuNxMain.exe",
"filmora": r"C:\Program Files\Wondershare Filmora\Wondershare Filmora Launcher.exe",
"my game": r"C:\Program Files\MyGame\game.exe",
```

**How to find the correct path:**
1. Right-click the app's desktop shortcut
2. Select **Properties**
3. Copy the full path from the **Target** field
4. Paste it into `app_map` using the format above

---

## ✅ Supported Apps Out of the Box

Just say the name — no setup needed:

| Voice Command | App |
|---|---|
| "notepad" | Notepad |
| "sticky note" | Sticky Notes |
| "chrome" / "google chrome" | Google Chrome |
| "brave" / "brave browser" | Brave Browser |
| "firefox" | Firefox |
| "edge" / "microsoft edge" | Microsoft Edge |
| "vlc" | VLC Media Player |
| "vscode" / "visual studio code" | Visual Studio Code |
| "file explorer" | Windows Explorer |
| "cmd" / "command prompt" | Command Prompt |
| "powershell" | PowerShell |
| "terminal" / "windows terminal" | Windows Terminal |
| "task manager" | Task Manager |
| "calculator" | Windows Calculator |
| "snipping tool" | Snipping Tool |
| "paint" | Microsoft Paint |
| "word" / "microsoft word" | Microsoft Word |
| "excel" / "microsoft excel" | Microsoft Excel |
| "powerpoint" | Microsoft PowerPoint |
| "outlook" / "microsoft outlook" | Microsoft Outlook |
| "onenote" | Microsoft OneNote |
| "teams" / "microsoft teams" | Microsoft Teams |
| "discord" | Discord |
| "spotify" | Spotify |
| "steam" | Steam |
| "epic" / "epic games" | Epic Games Launcher |
| "obs" / "obs studio" | OBS Studio |
| "mumu" / "mumu player" | MuMuPlayer |
| "zoom" | Zoom |
| "telegram" | Telegram |
| "whatsapp" | WhatsApp |
| "skype" | Skype |

---

## 🗣️ Example Commands

```
"Open Discord"
"Close Discord"
"Open Command Prompt"
"Move notes.txt to Desktop"
"Search for my resume on my computer"
"Search for a png file named selfie"
"Open facebook.com"
"Search YouTube for lo-fi music"
"Open Ejiogu Dennis on YouTube"
"What's the weather today?"
"Create a file called notes.txt"
"Create a folder named Desktop"
```

---

## ⚠️ Disclaimer

This project was created purely for educational purposes as part of a school activity. The goal was to study an existing Python project, extend it, and document the process. The original code belongs to **Nazir Louis** — this is simply a modified version made for learning. No commercial intent whatsoever.

---

*"Just a J.A.R.V.I.S. knockoff — but it's mine." — ReCreatem3*
