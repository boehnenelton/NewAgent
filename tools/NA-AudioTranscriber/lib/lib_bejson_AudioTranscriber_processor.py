"""
Library:         lib_bejson_AudioTranscriber_processor.py
Family:          Utility
Module Purpose:  Stage copying, FFmpeg audio conversion to 16-bit mono 16kHz WAV, and Base64 encoding.
Architecture:    BEJSON format & architectural specification summary
Version:         1.0.0
Release_Version: 300
Date:            2026-10-11
Author:          Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Format_Creator:  Elton Boehnen
RELATIONAL_ID:   e8a71b2d-3c4f-5a6b-7c8d-9e0f1a2b3c4d
"""

import base64
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def stage_copy_file(source_path: Path, stage_dir: Path) -> Path:
    """Copies input file into the stage directory."""
    if not source_path.exists():
        raise FileNotFoundError(f"Source audio file not found: {source_path}")

    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_file = stage_dir / source_path.name
    shutil.copy2(source_path, staged_file)
    logger.info(f"Copied '{source_path}' to stage: '{staged_file}'")
    return staged_file


def convert_to_16bit_mono_wav(
    input_audio: Path,
    output_wav: Path = None,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Path:
    """
    Converts audio file to 16-bit PCM 16kHz Mono WAV using ffmpeg.
    Command: ffmpeg -y -i <input> -acodec pcm_s16le -ac 1 -ar 16000 <output>
    """
    if not input_audio.exists():
        raise FileNotFoundError(f"Input audio file does not exist: {input_audio}")

    if output_wav is None:
        output_wav = input_audio.parent / f"{input_audio.stem}_16bit_mono.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_audio),
        "-acodec",
        "pcm_s16le",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        str(output_wav),
    ]

    logger.info(f"Executing FFmpeg conversion: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"FFmpeg error: {result.stderr}")
        raise RuntimeError(f"FFmpeg audio conversion failed: {result.stderr}")

    logger.info(f"Audio successfully converted to 16-bit mono WAV: {output_wav}")
    return output_wav


def encode_file_to_base64(file_path: Path, output_b64: Path = None) -> Path:
    """Encodes file to Base64 text representation and writes output."""
    if not file_path.exists():
        raise FileNotFoundError(f"Target file for Base64 encoding not found: {file_path}")

    if output_b64 is None:
        output_b64 = file_path.parent / f"{file_path.name}.b64"

    with open(file_path, "rb") as f_in:
        raw_bytes = f_in.read()

    b64_encoded = base64.b64encode(raw_bytes).decode("utf-8")

    # Atomic write pattern
    tmp_file = output_b64.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f_out:
        f_out.write(b64_encoded)

    os.replace(tmp_file, output_b64)
    logger.info(f"Encoded file to Base64: {output_b64}")
    return output_b64