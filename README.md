# 🎵 ACE-Step Live Stream

A self-hosted, open-source system where a live YouTube stream generates continuous music using **ACE-Step** (a diffusion-based music generation model running locally on GPU). A local LLM (via **Unsloth Studio** or any OpenAI-compatible API) analyzes viewer chat messages and dynamically adjusts the musical direction in real time.

## 📋 Features

- **Real-time Chat Analysis**: Polls YouTube Live chat every 45 seconds
- **AI Vibe Analysis**: Uses OpenAI-compatible API to determine musical direction
- **Dynamic Music Generation**: Generates 30-second songs based on chat mood
- **Continuous Streaming**: FFmpeg RTMP streaming to YouTube Live
- **Multi-language Support**: Handles English and other languages
- **Comprehensive Logging**: Structured logging with loguru
- **Production Ready**: Async/await patterns, error handling, and configuration management

## 🏗️ Architecture

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

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- NVIDIA GPU (RTX 3090+, recommended) or A100 for ACE-Step
- FFmpeg installed and on PATH
- YouTube API OAuth2 credentials with `youtube` scope
- Unsloth Studio running an OpenAI-compatible endpoint

### Installation

1. **Clone ACE-Step:**
   ```bash
   git clone https://github.com/ace-step/ACE-Step.git && cd ACE-Step && pip install -e .
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start ACE-Step API:**
   ```bash
   ace-step --port 8002
   ```

4. **Start Unsloth Studio (OpenAI-compatible):**
   ```bash
   unsloth-server --host 0.0.0.0 --port 8000
   ```

## ⚙️ Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# YouTube API Configuration
YOUTUBE_API_KEY=your_youtube_api_key_here
LIVE_CHAT_ID=your_live_chat_id_here
YOUTUBE_STREAM_URL=rtmp://a.rtmp.youtube.com/live2
YOUTUBE_STREAM_KEY=your_stream_key_here
# Leave false when you create/manage the Live event in YouTube Studio.
YOUTUBE_MANAGE_BROADCAST=false
# Required only when automated broadcast lifecycle management is enabled.
YOUTUBE_OAUTH_ACCESS_TOKEN=

# Vibe Analyzer Configuration (Unsloth Studio / OpenAI-compatible API)
VIBE_API_URL=http://localhost:8000
VIBE_API_MODEL=unsloth-mistral

# Music Generator Configuration (ACE-Step)
ACE_STEP_URL=http://127.0.0.1:8002

# Stream Configuration
DEFAULT_ENERGY=3
DEFAULT_GENRE=lofi
DEFAULT_TAGS=chill,lofi hip hop,relaxed
DEFAULT_VOCAL_STYLE=instrumental
DEFAULT_DIRECTION=default chill lofi beat
DEFAULT_LYRICS_LANGUAGE=en

# Chat Monitor Configuration
CHAT_POLL_INTERVAL=45
CHAT_MAX_RESULTS=20

# Music Generator Configuration
GENERATION_INTERVAL=5
DEFAULT_DURATION=30

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=stream.log
```

### Setting Up YouTube Live

1. Create a YouTube Live event
2. Get your **Live Chat ID** from the event URL
3. Get your **Stream Key** from YouTube Studio
4. Set environment variables with these values

`YOUTUBE_API_KEY` is sufficient for reading public chat. Creating, binding, or
transitioning a broadcast needs an OAuth access token with YouTube permissions;
set `YOUTUBE_MANAGE_BROADCAST=true` only when that token is configured. The
stream key is never written to `state.json`.

### Local or LAN Test Stream

Set `STREAM_OUTPUT=local` and start the application normally. It opens an MP3
endpoint at `http://localhost:8090/stream.mp3` without creating a YouTube
broadcast. On another device on the same network, replace `localhost` with the
streaming computer's LAN IP address (for example, `http://192.168.1.50:8090/stream.mp3`).
Open that URL with **VLC** using *Media → Open Network Stream*, or add it as an
Internet radio URL in an iTunes-compatible client. Ensure the computer firewall
permits inbound TCP traffic on `LOCAL_STREAM_PORT` (default `8090`).

### Manual Music Steering

Every output mode starts a steering API at `http://127.0.0.1:8091/steer` by
default. A steering request immediately analyzes or applies the requested vibe,
updates `mood.json`, and queues a new song. It does not need YouTube chat.

```bash
# Natural-language nudge, interpreted by the configured local LLM
curl -X POST http://127.0.0.1:8091/steer ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"switch to calm instrumental jazz with soft piano\"}"

# Direct, deterministic override
curl -X POST http://127.0.0.1:8091/steer ^
  -H "Content-Type: application/json" ^
  -d "{\"vibe\":{\"genre\":\"electronic\",\"energy\":8,\"tags\":[\"deep bass\",\"driving beat\"]}}"
```

The endpoint binds only to localhost by default. To control it from the LAN,
set `STEERING_HOST=0.0.0.0`, choose a long `STEERING_TOKEN`, and send it in the
`X-Steer-Token` header. Do not expose this control port to the public internet.

## 📁 Project Structure

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
├── .env                              # Environment variables (create from .env.example)
├── .env.example                      # Environment template
├── requirements.txt                  # Dependencies list
└── README.md                         # This file
```

## 🎮 Usage

### Running the Stream

```bash
# Terminal 1: Start ACE-Step API
ace-step --port 8002

# Terminal 2: Start Unsloth Studio (OpenAI-compatible endpoint)
unsloth-server --host 0.0.0.0 --port 8000

# Terminal 3: Run orchestrator
python main.py
```

### Testing Components

```bash
# Test chat monitor
python chat_monitor.py

# Test vibe analyzer
python vibe_analyzer.py

# Test music generator
python music_generator.py

# Test stream controller
python stream_controller.py

# Run the regression suite
python -m unittest discover -s tests -v
```

## 📊 Data Flow

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

## 🔧 Component Details

### Chat Monitor (`chat_monitor.py`)

- Polls YouTube Live chat via YouTube Data API v3
- Runs as async background task (aiohttp + asyncio)
- Polls every 45 seconds
- Skips super chats, member-only messages, system messages
- Keeps rolling window of last 20 messages per analysis cycle
- Emits structured dicts: `[{"author": str, "text": str, "timestamp": datetime}]`

### Vibe Analyzer (`vibe_analyzer.py`)

- Reads chat messages and sends to OpenAI-compatible API
- Outputs structured JSON describing musical direction
- Validates and clamps vibe values
- Fallback to default vibe if API is unreachable

### Music Generator (`music_generator.py`)

- Sends vibe JSON to ACE-Step via OpenRouter-compatible API
- Receives base64-encoded MP3 audio
- Saves to `queue/` directory
- Creates directories if they don't exist

### Stream Controller (`stream_controller.py`)

- Manages FFmpeg RTMP streaming
- YouTube API broadcast lifecycle management
- Creates live broadcast via `POST /youtube/v3/liveBroadcasts`
- Binds stream via `POST /youtube/v3/liveStreams`
- Transitions to testing status via `PATCH /youtube/v3/liveBroadcasts/{id}?status=testing`

### Orchestrator (`main.py`)

- Ties all components together into a perpetual loop
- Starts YouTube broadcast
- Pre-generates initial songs
- Starts FFmpeg streaming
- Runs chat monitor → vibe analyzer → music generator continuously

## 🎯 Example Chat Interactions

| Viewer Chat | Vibe Analysis Result | ACE-Step Prompt | Generated Music |
|---|---|---|---|
| "play some jazz!" | energy:7, genre:"jazz", tags:["smooth saxophone","swing"], instrumental:true | `<prompt>Upbeat jazz track, smooth saxophone, swing, energy level 7/10</prompt>` | Smooth jazz with saxophone, upbeat tempo |
| "more bass!!" + "heavy drums" | energy:9, genre:"electronic", tags:["bass heavy","driving beat"], instrumental:true | `<prompt>Upbeat electronic track, bass heavy, driving beat, energy level 9/10</prompt>` | High-energy electronic with heavy bass and drums |
| "something tropical~" | energy:4, genre:"tropical house", tags:["breezy","palm trees"], instrumental:true | `<prompt>Upbeat tropical house track, breezy, palm trees, energy level 4/10</prompt>` | Relaxed tropical house with airy synths |
| "let's hear some vocals!" + "pop song about love" | energy:6, genre:"pop", tags:["catchy","romantic"], vocal_style:"soulful pop vocals" | `<prompt>soulful pop vocals in pop style, catchy</prompt>\n<lyrics>[Verse]\nSoulful pop vocals\nDancing under neon lights[/Verse]` | Pop song with soulful female vocals about love |

## 📝 LLM Prompt Template

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
- Handle emojis and slang gracefully
- If chat is empty or contains only system messages, return default vibe
- If chat contains mixed languages, prioritize the dominant language
- If chat is in a language other than English, set lyrics_language accordingly
```

## 🔍 Troubleshooting

### Common Issues

**1. FFmpeg not found**
- Install FFmpeg: `sudo apt-get install ffmpeg` (Linux) or download from ffmpeg.org

**2. YouTube API errors**
- Verify API key is correct
- Check API quota limits
- Ensure `youtube` scope is granted

**3. ACE-Step API errors**
- Verify ACE-Step is running: `ace-step --port 8002`
- Check API URL in environment variables

**4. Vibe analyzer API errors**
- Verify Unsloth Studio is running: `unsloth-server --host 0.0.0.0 --port 8000`
- Check API URL in environment variables

**5. No songs in queue**
- Wait for generation to complete
- Check logs for errors
- Verify ACE-Step is generating audio

### Logging

Logs are written to individual log files for each component:
- `chat_monitor.log`
- `vibe_analyzer.log`
- `music_generator.log`
- `stream_controller.log`
- `main.log`

Logs are rotated every 10 MB and retained for 7 days.

## 📚 ACE-Step Advantages

| Feature | MusicGen | **ACE-Step** |
|---|---|---|
| Architecture | Autoregressive codec (EnCodec + Transformer) | **Diffusion + DCAE + Flow Matching** |
| Output length | Fixed 10s instrumental chunks | **Up to 4 min full songs with vocals** |
| Generation speed | Moderate (autoregressive token-by-token) | **15× faster than LLM baselines on A100** |
| Vocals | Separate vocal model needed | **Built-in, multilingual (19+ languages)** |
| Editing capabilities | Basic prompting only | **Cover, repaint, lyric edit, remix, variations** |
| Flow manipulation | N/A | **Fine-grained control via flow ODE solving** |
| Open source | Yes (Meta) | **Yes (MIT license)** |

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- [ACE-Step](https://github.com/ace-step/ACE-Step) - Diffusion-based music generation
- [Unsloth Studio](https://unsloth.ai/) - LLM training and inference
- [YouTube Data API](https://developers.google.com/youtube/v3) - YouTube API v3
- [FFmpeg](https://ffmpeg.org/) - Multimedia framework

## 📞 Support

For issues and questions:
- Open an issue on GitHub
- Check the troubleshooting section
- Review the logs for error messages

---

**Built with ❤️ for the AI music community**
