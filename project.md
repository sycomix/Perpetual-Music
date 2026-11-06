# 🎵 Live Perpetual Generative Music AI — Final Plan & Code Generation Prompt

---

## Project: ACE-Step Live Stream

A self-hosted, open-source system where a live YouTube stream generates continuous music using **ACE-Step** (a diffusion-based music generation model running locally on GPU). A local LLM (via **Unsloth Studio** or any OpenAI-compatible API) analyzes viewer chat messages and dynamically adjusts the musical direction in real time.

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         YouTube Live Stream                          │
│                                                                      │
│   ┌──────────────┐    ┌──────────────────────┐    ┌──────────────┐  │
│   │ Chat Monitor  │    │ Vibe Analyzer        │    │ Music Generator│  │
│   │ (aiohttp)     │───▶│ (Unsloth Studio /     │───▶│ (ACE-Step     │  │
│   │ Polls every   │    │ OpenAI-compatible)   │    │ OpenRouter   │  │
│   │ 45 seconds    │    │ → vibe JSON          │    │ Compatible   │  │
│   └──────────────┘    └──────────┬───────────┘    └──────┬───────┘  │
│                                 │                        │            │
│                          mood.json              queue/     playing/   │
│                    ┌──────────┴──────────────────────────┤           │
│                    │ Stream Controller (FFmpeg RTMP)      │           │
│                    └─────────────────────────────────────┘           │
│                                                                      │
│  Chat viewers ──▶ Live chat ──▶ Vibe shifts ──▶ Music changes       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Specifications

### 2.1 Chat Monitor (`chat_monitor.py`)

**Purpose:** Polls YouTube Live chat via the YouTube Data API v3 and collects recent meaningful messages.

**Key behaviors:**
- Runs as an async background task (aiohttp + asyncio)
- Polls every 45 seconds
- Skips super chats, member-only messages, system messages
- Keeps a rolling window of last 20 messages per analysis cycle
- Emits structured dicts: `[{"author": str, "text": str, "timestamp": datetime}]`

**API calls:**
```
GET https://youtube.googleapis.com/youtube/v3/liveChatMessages
    ?part=snippet
    &liveChatId={LIVE_CHAT_ID}
    &key={API_KEY}
    &maxResults=20
```

### 2.2 Vibe Analyzer (`vibe_analyzer.py`)

**Purpose:** Reads the chat messages, sends them to an **OpenAI-compatible API** (Unsloth Studio or similar), and outputs structured JSON describing the musical direction.

**API Configuration:**
- Endpoint: `http://localhost:8000/v1/chat/completions` (default for Unsloth)
- Format: OpenAI Chat Completions (`messages` array, `model`, `temperature`)
- Fallback: default vibe if API is unreachable

### 2.3 Music Generator (`music_generator.py`)

**Purpose:** Sends the vibe JSON to ACE-Step via its OpenRouter-compatible API, receives base64-encoded MP3 audio, and saves it to the `queue/` directory.

**ACE-Step configuration:**
- Run locally: `ace-step --port 8002` or install as pip package
- API endpoint: `POST http://127.0.0.1:8002/v1/chat/completions`
- Supports OpenAI-compatible format (messages array, audio_config, sample_mode)

**Generation parameters:**
- Duration: 30 seconds per song (configurable)
- Instrumental mode when chat prefers no vocals
- Sample mode so LLM auto-generates lyrics and prompt tags
- Language auto-detection via `use_cot_language`

### 2.4 Stream Controller (`stream_controller.py`)

**Purpose:** Manages the FFmpeg RTMP stream that plays songs from the queue directory in a continuous loop, broadcasting to YouTube Live.

**FFmpeg command:**
```bash
ffmpeg -re -stream_loop -1 \
    -i /path/to/queue/*.mp3 \
    -c:a aac -b:a 192k \
    -f flv rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}
```

**YouTube API integration:**
- Creates a live broadcast via `POST /youtube/v3/liveBroadcasts`
- Binds the stream via `POST /youtube/v3/liveStreams`
- Transitions to testing status via `PATCH /youtube/v3/liveBroadcasts/{id}?status=testing`

### 2.5 Orchestrator (`main.py`)

**Purpose:** Ties all components together into a perpetual loop that:
1. Starts the YouTube broadcast
2. Pre-generates initial songs
3. Starts FFmpeg streaming
4. Runs chat monitor → vibe analyzer → music generator continuously

---

## 3. Data Flow

```
YouTube Chat ──poll──▶ [Chat Monitor] ─msgs──▶ [Vibe Analyzer]
                                                    │
                                                    ▼
                                               vibe JSON (JSON)
                                                    │
                                                    ▼
                                              [Music Generator]
                                                    │
                                                    ▼
                                              ACE-Step API call
                                                    │
                                                    ▼
                                              base64 MP3 → queue/
                                                    │
                                                    ▼
                                              FFmpeg picks up & streams
```

---

## 4. LLM Prompt Template (OpenAI Format)

The following prompt is sent to the local LLM via OpenAI-compatible API:

```
You are a "Vibe Curator" for a live AI music stream on YouTube.
Viewers are chatting in real-time, and their collective mood determines the next song.

Analyze these recent chat messages and determine:
1. The overall emotional tone (energy level 0-10)
2. Preferred genre(s) — pick ONE primary genre
3. Preferred mood/atmosphere (descriptive tags)
4. Whether vocals should be present or instrumental
5. A short creative direction summary (max 80 characters)

Chat messages:
{chat_messages}

Output ONLY valid JSON with this exact structure:
{
    "energy": <integer 0-10>,
    "genre": "<single genre name>",
    "tags": ["tag1", "tag2", "tag3"],
    "vocal_style": "<description or 'instrumental'>",
    "direction": "<short creative summary>",
    "lyrics_language": "en"
}

Rules:
- If chat is split, pick the dominant direction
- If no music preference, default to chill lofi/ambient
- Energy 0 = very slow/calm, 10 = very fast/intense
- Genre must be a single clear word (e.g., "jazz", "electronic")
- Tags should describe instrumentation and atmosphere
- If chat mentions lyrics in another language, set lyrics_language accordingly
```

---

## 5. ACE-Step Generation Prompt Format

The vibe JSON is translated into ACE-Step's OpenRouter-compatible API format:

**Instrumental mode:**
```json
{
    "messages": [
        {"role": "user", "content": "<prompt>Upbeat {genre} track, {tags[0]}, {tags[1]}, energy level {energy}/10</prompt>"}
    ],
    "audio_config": {
        "duration": 30,
        "instrumental": true,
        "vocal_language": "en"
    },
    "sample_mode": true,
    "use_cot_caption": true
}
```

**Vocal mode:**
```json
{
    "messages": [
        {"role": "user", "content": "<prompt>{vocal_style} vocals in {genre} style, {tags[0]}</prompt>\n<lyrics>[Verse]\nFeeling the rhythm of the night\n{direction}[/Verse]"}
    ],
    "audio_config": {
        "duration": 30,
        "instrumental": false,
        "vocal_language": "{lyrics_language}"
    },
    "sample_mode": true,
    "use_cot_caption": true
}
```

---

## 6. File Structure

```
ace-step-live-stream/
├── main.py                           # Orchestrator entry point
├── chat_monitor.py                   # YouTube chat polling
├── vibe_analyzer.py                  # LLM-based vibe analysis (OpenAI API)
├── music_generator.py                # ACE-Step generation via API
├── stream_controller.py              # FFmpeg RTMP streaming
├── prompts/
│   ├── llm_vibe_prompt.txt           # Raw prompt template
│   └── ace_step_instrumental.json    # Instrumental mode template
│   └── ace_step_vocal.json           # Vocal mode template
├── queue/                            # Generated songs waiting to play
├── playing/                          # Currently streaming
├── played/                           # Already played (archive)
├── mood.json                         # Current vibe state
├── state.json                        # Stream statistics
└── requirements.txt                  # Dependencies list
```

---

## 7. Deployment

### Prerequisites:
- Python 3.10+
- NVIDIA GPU (RTX 3090+, recommended) or A100 for ACE-Step
- FFmpeg installed and on PATH
- YouTube API OAuth2 credentials with `youtube` scope
- Unsloth Studio running an OpenAI-compatible endpoint

### Steps:
1. Clone ACE-Step: `git clone https://github.com/ace-step/ACE-Step.git && cd ACE-Step && pip install -e .`
2. Start ACE-Step API: `ace-step --port 8002`
3. Start Unsloth Studio (OpenAI-compatible): `python unsloth_server.py --host 0.0.0.0 --port 8000`
4. Install Python dependencies: `pip install -r requirements.txt`
5. Set environment variables:
   ```bash
   export YOUTUBE_API_KEY="..."
   export LIVE_CHAT_ID="..."
   export YOUTUBE_STREAM_URL="rtmp://a.rtmp.youtube.com/live2"
   export YOUTUBE_STREAM_KEY="..."
   ```
6. Run orchestrator: `python main.py`

---

## 8. Code Generation LLM Prompt

The following prompt is sent to an LLM (GPT-4, Claude, etc.) to generate all source code for the project:

```
You are a senior Python developer and systems architect. Generate the complete source code for a "Live Perpetual Generative Music AI" system. The system consists of 5 Python files plus configuration. Generate ALL files in full.

=== CONTEXT ===
A YouTube Live stream generates continuous AI music using ACE-Step (a diffusion-based music generation model running locally on GPU). Viewers chat in the live chat, and a local LLM running via Unsloth Studio (OpenAI-compatible API) analyzes their messages to determine the musical direction (genre, energy, style) every 45 seconds. The new vibe is sent to ACE-Step which generates a full song (30s), saved to queue/. FFmpeg plays songs from the queue via RTMP to YouTube Live.

=== ARCHITECTURE ===
1. chat_monitor.py — Asyncio + aiohttp, polls YouTube Live chat every 45s, returns list of message dicts
2. vibe_analyzer.py — Sends chat messages to OpenAI-compatible API (http://localhost:8000/v1/chat/completions), parses JSON response into vibe dict with keys: energy(0-10), genre, tags[], vocal_style, direction, lyrics_language
3. music_generator.py — Sends vibe to ACE-Step OpenRouter-compatible API (http://127.0.0.1:8002/v1/chat/completions), receives base64 MP3, saves to queue/ directory
4. stream_controller.py — Manages FFmpeg RTMP streaming of queue/*.mp3 files in a loop, YouTube API broadcast lifecycle management
5. main.py — Orchestrator that starts broadcast, pre-generates 3 initial songs with default vibe, starts FFmpeg, then runs chat_monitor.run(on_chat_messages callback)
- The callback analyzes chat and generates new songs reflecting updated vibes
- async def main() — reads env vars for config, creates LiveMusicStream, calls run()

=== SPECIFIC REQUIREMENTS ===

**chat_monitor.py:**
- Class ChatMonitor with __init__(self, api_key, live_chat_id)
- Method poll_chat() → returns list of dicts or None
- Each dict: {"author": str, "text": str, "timestamp": datetime}
- Skips messages without textMessageDetails.messageText
- Keeps last 20 messages per poll cycle
- Method run(self, callback) — asyncio loop calling callback with msgs every 45s

**vibe_analyzer.py:**
- Class VibeAnalyzer with __init__(self, api_url="http://localhost:8000", model="unsloth-mistral")
- ANALYSIS_PROMPT constant (the full vibe prompt from Section 4 above)
- Method analyze(self, chat_messages: List[Dict]) → Dict — sends messages to OpenAI-compatible API via aiohttp POST to {api_url}/v1/chat/completions with {"messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 300}, parses JSON response, validates/defaults keys
- Static method _default_vibe() → returns safe default dict
- Static method _validate_vibe(vibe) → ensures all required keys present, clamps energy 0-10

**music_generator.py:**
- Class MusicGenerator with __init__(self, ace_step_url="http://127.0.0.1:8002")
- Creates queue/, playing/, played/ directories
- Method generate_song(self, vibe: Dict) → str (filename) — builds ACE-Step API call based on vocal_style (instrumental vs vocal), sends POST to {ace_step_url}/v1/chat/completions with sample_mode=true, extracts audio from response["choices"][0]["message"]["audio"][0]["audio_url"]["url"], decodes base64, saves to queue/
- Method update_state(self, **kwargs) — updates state.json
- Method run_generation_loop(self, vibe: Dict) — async loop generating songs every 5s

**stream_controller.py:**
- Class StreamController with __init__(self, youtube_stream_url, youtube_stream_key)
- Creates queue/, playing/, played/ directories
- Method start_broadcast() → bool — POST to /youtube/v3/liveBroadcasts creating broadcast, POST to /liveStreams binding RTMP, PATCH to transition to testing status
- Method stop_broadcast() — PATCH broadcast status to complete
- Method get_status() → Dict — reads state.json
- Method start_ffmpeg_stream() — subprocess.Popen(["ffmpeg", "-re", "-stream_loop", "-1", "-i", "queue/*.mp3", ...])
- Method stop_ffmpeg_stream() — terminate process

**main.py:**
- Class LiveMusicStream orchestrating all components
- async def run() — starts broadcast, generates 3 initial songs with default vibe, starts FFmpeg, then runs chat_monitor.run(on_chat_messages callback)
- The callback analyzes chat and generates new songs reflecting updated vibes
- async def main() — reads env vars for config, creates LiveMusicStream, calls run()

=== ACE-Step API DETAILS ===
Endpoint: POST {ace_step_url}/v1/chat/completions
Body format: {"messages": [{"role": "user", "content": "..."}], "audio_config": {...}, "sample_mode": true}
audio_config fields: duration (float, seconds), instrumental (bool), vocal_language (str)
When instrumental=true and sample_mode=true, the LLM auto-generates prompt/tags from chat context

=== PROMPT TRANSFORMATION ===
The vibe dict is translated into ACE-Step prompts:
- If vocal_style == "instrumental": content = f"<prompt>Upbeat {genre} track, {tags[0]}, {tags[1]}, energy level {energy}/10</prompt>"
- If vocal_style != "instrumental": content = f"<prompt>{vocal_style} vocals in {genre} style, {tags[0]}</prompt>\n<lyrics>[Verse]\n{direction}[/Verse]"

=== OUTPUT FORMAT ===
Generate each file fully. Separate files with clear markers like:
--- FILE: main.py ---
[file content]
--- FILE: chat_monitor.py ---
[file content]
... etc for all 5 files plus requirements.txt and mood.json template.

Do NOT abbreviate or use comments like "# ... rest of code" — generate every line.
```

---

## 9. How Chat Influences Music (Example Flow)

| Viewer Chat | Vibe Analysis Result | ACE-Step Prompt | Generated Music |
|---|---|---|---|
| "play some jazz!" | energy:7, genre:"jazz", tags:["smooth saxophone","swing"], instrumental:true | `<prompt>Upbeat jazz track, smooth saxophone, swing, energy level 7/10</prompt>` | Smooth jazz with saxophone, upbeat tempo |
| "more bass!!" + "heavy drums" | energy:9, genre:"electronic", tags:["bass heavy","driving beat"], instrumental:true | `<prompt>Upbeat electronic track, bass heavy, driving beat, energy level 9/10</prompt>` | High-energy electronic with heavy bass and drums |
| "something tropical~" | energy:4, genre:"tropical house", tags:["breezy","palm trees"], instrumental:true | `<prompt>Upbeat tropical house track, breezy, palm trees, energy level 4/10</prompt>` | Relaxed tropical house with airy synths |
| "let's hear some vocals!" + "pop song about love" | energy:6, genre:"pop", tags:["catchy","romantic"], vocal_style:"soulful pop vocals" | `<prompt>soulful pop vocals in pop style, catchy</prompt>\n<lyrics>[Verse]\nSoulful pop vocals\nDancing under neon lights[/Verse]` | Pop song with soulful female vocals about love |

---

## 10. Key ACE-Step Advantages Over MusicGen for This Use Case

| Feature | MusicGen | **ACE-Step** |
|---|---|---|
| Architecture | Autoregressive codec (EnCodec + Transformer) | **Diffusion + DCAE + Flow Matching** |
| Output length | Fixed 10s instrumental chunks | **Up to 4 min full songs with vocals** |
| Generation speed | Moderate (autoregressive token-by-token) | **15× faster than LLM baselines on A100** |
| Vocals | Separate vocal model needed | **Built-in, multilingual (19+ languages)** |
| Editing capabilities | Basic prompting only | **Cover, repaint, lyric edit, remix, variations** |
| Flow manipulation | N/A | **Fine-grained control via flow ODE solving** |
| Open source | Yes (Meta) | **Yes (MIT license)** |

---

## 11. Running the System

```bash
# Terminal 1: Start ACE-Step API
ace-step --port 8002

# Terminal 2: Start Unsloth Studio (OpenAI-compatible endpoint)
unsloth-server --host 0.0.0.0 --port 8000

# Terminal 3: Run orchestrator
python main.py
```

The system starts a YouTube Live broadcast, pre-generates 3 initial songs with default chill lofi vibe, starts FFmpeg RTMP streaming, then enters the perpetual loop where chat messages are analyzed every 45 seconds and new songs are generated reflecting the updated vibe.

---

## 12. Configuration Files

**mood.json** (auto-generated by Vibe Analyzer):
```json
{
    "energy": 3,
    "genre": "lofi",
    "tags": ["chill", "lofi hip hop", "relaxed"],
    "vocal_style": "instrumental",
    "direction": "default chill lofi beat",
    "lyrics_language": "en"
}
```

**state.json** (auto-generated by Stream Controller):
```json
{
    "broadcastId": null,
    "streamKey": null,
    "liveChatId": null,
    "isActive": false,
    "songsGenerated": 0,
    "lastUpdated": "2026-10-23T00:00:00+00:00"
}
```

**requirements.txt:**
```
aiohttp>=3.9.0
ace-step @ git+https://github.com/ace-step/ACE-Step.git
requests>=2.31.0
```

---

This plan and prompt are now fully updated to use **Unsloth Studio / OpenAI-compatible API** for the vibe analyzer instead of Ollama. Ready to generate all source files.