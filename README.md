# W.I.L.S.O.N. - Your J.A.R.V.I.S. AI Assistance Knockoff

A personal AI desktop assistant inspired by **A.D.A.** by [Nazir Louis](https://github.com/nazirlouis/ada).

> This project is a modified and extended version built on top of the original A.D.A. concept. Full credit and inspiration goes to the original author.

---

## 🎥 Original Project

This project is heavily inspired by the work of **Nazir Louis**:

- 📺 YouTube Tutorial: [Watch here](https://www.youtube.com/watch?v=aooylKf-PeA&t=7s)
- 💻 Original GitHub Repository: [nazirlouis/ada](https://github.com/nazirlouis/ada)

Please check out and support the original creator's work.

---

## ✨ What's Different in This Version

Built on top of the original A.D.A., this version includes the following additions and fixes:

- ✅ Upgraded to `gemini-2.5-flash-native-audio-latest` for native voice responses
- ✅ Voice selection via Gemini's built-in voices (no longer dependent on ElevenLabs for output)
- ✅ Fixed audio playback pipeline for the native audio model
- ✅ Smarter app launching — searches Program Files for executables (OBS, Discord, Brave, Steam, Epic Games, MumuPlayer, etc.)
- ✅ YouTube channel/video search via direct URL and handle lookup
- ✅ `search_and_open` function to find and open YouTubers directly
- ✅ `browser_search` for Google, YouTube, and Bing
- ✅ Google Search and Code Execution tools re-integrated
- ✅ Video feed no longer triggers unprompted AI commentary

---

## 🛠️ Requirements

```
pip install PySide6 opencv-python pyaudio google-genai python-dotenv pillow numpy websockets pyautogui
```

---

## 🔑 Setup

1. Clone or download this repository
2. Create a `.env` file in the same folder as `wilson.py`:

```
GEMINI_API_KEY=your_gemini_api_key_here
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
```

> Note: ElevenLabs is no longer used for voice output in this version, but the key is still required by the code to start.

3. Run the assistant:

```
python wilson.py
```

---

## 🗎 Adding Custom App Paths

By default, Wilson knows how to open common apps like Chrome, Discord, Notepad, etc. If an app fails to open, you can add it manually in `wilson.py`.

Find the `app_map` dictionary inside the `_open_application` function (search for `app_map = {`) and add your app like this:

```python
"mumuplayer": r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuNxMain.exe",
"filmora": r""C:\Program Files\Wondershare Filmora\Wondershare Filmora Launcher.exe",
"my game": r"C:\Program Files\MyGame\game.exe",
```

**How to find the correct path:**
1. Right-click the app's desktop shortcut
2. Click **Properties**
3. Copy the full path from the **Target** field
4. Paste it into the `app_map` using the format above

**Already supported apps** (just say the name):

| What you say | App |
|---|---|
| "notepad" | Notepad |
| "sticky note" | Sticky Note |
| "chrome" / "google chrome" | Google Chrome |
| "brave" / "brave browser" | Brave Browser |
| "firefox" | Firefox |
| "edge" / "microsoft edge" | Microsoft Edge |
| "vlc" | VLC Media Player |
| "vscode" | Visual Studio Code |
| "file explorer" | Windows Explorer |
| "cmd" / "command prompt" | Command Prompt |
| "powershell" | PowerShell |
| "task manager " | Task Manager |
| "outlook" | Microsoft Outlook |
| "word" | Microsoft Word |
| "edge" | Microsoft Edge |
| "powerpoint" | Microsoft Powerpoint |
| "microsoft teams" | Microsoft Teams |
| "calculator " | Windows Calculator |
| "snipping tool" | Snipping Tool |

---

## 🗣️ Example Commands

- *"Open Discord"*
- *"Open Brave browser"*
- *"Search YouTube for lo-fi music"*
- *"Open Ejiogu Dennis on YouTube"*
- *"What's the weather today?"*
- *"Create a file called notes.txt"*
- *"Open facebook.com"*
- *"Search for class suspension Philippines 2026"*
- *"Search Wilson lo siento"*

---

## ⚠️ Disclaimer

This project was created purely for educational purposes as part of a school activity. The goal was to find a Python project on YouTube, study it, and upload it to GitHub as a practice exercise. The original code belongs to Nazir Louis — this is simply a modified version made for learning. No commercial intent whatsoever.

---

*"Just a J.A.R.V.I.S. knockoff — but it's mine.", ReCreatem3*
