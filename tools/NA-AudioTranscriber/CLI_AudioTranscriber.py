#!/usr/bin/env python3
"""
CLI Tool:        CLI_AudioTranscriber.py
Description:     Copies audio files to stage folder, converts to 16-bit 16kHz mono WAV, transcribes via Whisper, and Base64 encodes output.
Version:         1.0.0
Package_Version: 100
Date:            2026-10-11
Author:          Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID:   f7a6b5c4-d3e2-1f0a-9b8c-7d6e5f4a3b2c
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Self-locating script path
SCRIPT_PATH = Path(__file__).resolve().parent
LIB_PATH = SCRIPT_PATH / "lib"
if str(LIB_PATH) not in sys.path:
    sys.path.insert(0, str(LIB_PATH))

from lib_bejson_AudioTranscriber_processor import (
    stage_copy_file,
    convert_to_16bit_mono_wav,
    encode_file_to_base64,
)
from lib_bejson_AudioTranscriber_transcriber import transcribe_audio_whisper

VERSION = "1.0.0"
PACKAGE_VERSION = "100"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("NA-AudioTranscriber")


def load_config() -> dict:
    config_file = SCRIPT_PATH / "config" / "config.json"
    if not config_file.exists():
        return {
            "stage_dir": "stage/",
            "default_whisper_model": "tiny",
            "audio_sample_rate": 16000,
            "audio_channels": 1,
        }
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            values = data.get("Values", [])
            conf = {}
            for row in values:
                if len(row) >= 2:
                    conf[row[0]] = row[1]
            return conf
    except Exception as err:
        logger.warning(f"Could not parse config.json: {err}. Using defaults.")
        return {
            "stage_dir": "stage/",
            "default_whisper_model": "tiny",
            "audio_sample_rate": 16000,
            "audio_channels": 1,
        }


def process_audio_pipeline(source_file: Path, whisper_model: str = "tiny") -> dict:
    """Executes the complete pipeline: Copy -> Convert -> Transcribe -> Base64 Encode."""
    source_file = source_file.resolve()
    if not source_file.is_file():
        raise FileNotFoundError(f"Source file does not exist: {source_file}")

    config = load_config()
    stage_dir = SCRIPT_PATH / config.get("stage_dir", "stage/")
    stage_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[1/4] Copying '{source_file.name}' to stage folder...")
    staged_file = stage_copy_file(source_file, stage_dir)

    print("\n[2/4] Converting audio to 16-bit mono 16kHz WAV...")
    wav_file = convert_to_16bit_mono_wav(
        staged_file,
        sample_rate=config.get("audio_sample_rate", 16000),
        channels=config.get("audio_channels", 1),
    )

    print(f"\n[3/4] Transcribing audio using Whisper (model: '{whisper_model}')...")
    transcript_file = transcribe_audio_whisper(
        wav_file,
        model=whisper_model,
        output_dir=stage_dir,
    )

    print("\n[4/4] Encoding converted WAV audio to Base64...")
    b64_file = encode_file_to_base64(wav_file)

    print("\n==================================================")
    print(" PIPELINE COMPLETED SUCCESSFULLY")
    print("==================================================")
    print(f" Staged File:     {staged_file}")
    print(f" Converted WAV:   {wav_file}")
    print(f" Transcript File: {transcript_file}")
    print(f" Base64 File:     {b64_file}")
    print("==================================================\n")

    return {
        "staged_file": str(staged_file),
        "wav_file": str(wav_file),
        "transcript_file": str(transcript_file),
        "b64_file": str(b64_file),
    }


def register_project():
    reg_script = Path("/storage/emulated/0/Admin/data/project_db/cli_project_register.py")
    if not reg_script.exists():
        reg_script = Path("/storage/emulated/0/Admin/repos/new/NewAgent/cli_project_register.py")

    import subprocess
    if reg_script.exists():
        print(f"Registering project at {SCRIPT_PATH}...")
        res = subprocess.run([sys.executable, str(reg_script), "--register", str(SCRIPT_PATH)], capture_output=True, text=True)
        print(res.stdout or res.stderr)
    else:
        print("Registration daemon script not found.")


def interactive_menu():
    print("==================================================")
    print(" NA-AudioTranscriber CLI Pipeline Tool")
    print(" Author: Elton Boehnen")
    print(f" Version: {VERSION} (PKG {PACKAGE_VERSION})")
    print("==================================================")
    print(" 1. Transcribe & Process Audio File")
    print(" 2. Process Directory of Audio Files")
    print(" 3. View Configuration")
    print(" 4. About & Credits")
    print(" 5. Exit")
    print("==================================================")

    choice = input("Select an option [1-5]: ").strip()
    if choice == "1":
        file_path = input("Enter input audio file path: ").strip()
        model = input("Enter Whisper model (tiny/base/small/medium/large) [default: tiny]: ").strip() or "tiny"
        if file_path:
            process_audio_pipeline(Path(file_path), whisper_model=model)
    elif choice == "2":
        dir_path = input("Enter audio directory path: ").strip()
        model = input("Enter Whisper model [default: tiny]: ").strip() or "tiny"
        if dir_path and Path(dir_path).is_dir():
            audio_extensions = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".mp4"}
            files = [p for p in Path(dir_path).iterdir() if p.suffix.lower() in audio_extensions]
            print(f"Found {len(files)} audio files in '{dir_path}'. Processing...")
            for f in files:
                try:
                    process_audio_pipeline(f, whisper_model=model)
                except Exception as e:
                    logger.error(f"Failed to process {f.name}: {e}")
    elif choice == "3":
        cfg = load_config()
        print("\nCurrent Configuration:")
        for k, v in cfg.items():
            print(f" - {k}: {v}")
    elif choice == "4":
        print("\nNA-AudioTranscriber")
        print("Author: Elton Boehnen · boehnenelton2024@gmail.com")
        print("Website: boehnenelton2024.pages.dev · github.com/boehnenelton")
        print("Format Creator: Elton Boehnen")
    elif choice == "5":
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="NA-AudioTranscriber CLI Suite")
    parser.add_argument("--file", "-f", type=str, help="Input audio file to process")
    parser.add_argument("--dir", "-d", type=str, help="Directory of audio files to process")
    parser.add_argument("--model", "-m", type=str, default="tiny", help="Whisper model size (tiny, base, small, etc.)")
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s {VERSION}-PKG{PACKAGE_VERSION}")
    parser.add_argument("--register", action="store_true", help="Register project in Master DB")

    args = parser.parse_args()

    if args.register:
        register_project()
        return

    if args.file:
        process_audio_pipeline(Path(args.file), whisper_model=args.model)
    elif args.dir:
        dir_p = Path(args.dir)
        if not dir_p.is_dir():
            print(f"Error: Directory '{args.dir}' does not exist.")
            sys.exit(1)
        audio_exts = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".mp4"}
        for item in dir_p.iterdir():
            if item.is_file() and item.suffix.lower() in audio_exts:
                process_audio_pipeline(item, whisper_model=args.model)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()