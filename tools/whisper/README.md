# Whisper Flask Service

A basic Flask wrapper and CLI tool for OpenAI's Whisper transcription model.

## Features
- **Flask API**: REST endpoint for audio transcription.
- **Web UI**: Mobile-first interface for easy uploading.
- **CLI Tool**: Command-line interface to interact with the API.

## Installation (Termux/Android)

1. **System Dependencies**:
   ```bash
   pkg install python-numpy python-pillow libsndfile ffmpeg
   ```

2. **Python Dependencies**:
   ```bash
   pkg install tur-repo
   pkg install python-torch python-torchaudio
   pip install openai-whisper flask flask-cors requests
   ```

## Usage

1. **Start the Flask Server**:
   ```bash
   python3 app.py
   ```

2. **Transcribe via Web**:
   Open `http://localhost:5000` in your browser.

3. **Transcribe via CLI**:
   ```bash
   python3 whisper_cli.py /path/to/audio.wav
   ```
