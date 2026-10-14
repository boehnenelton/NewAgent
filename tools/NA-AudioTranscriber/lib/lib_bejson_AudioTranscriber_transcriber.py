"""
Library:         lib_bejson_AudioTranscriber_transcriber.py
Family:          AI
Module Purpose:  Audio transcription using Whisper CLI or Python whisper library.
Architecture:    BEJSON format & architectural specification summary
Version:         1.0.0
Release_Version: 300
Date:            2026-10-11
Author:          Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Format_Creator:  Elton Boehnen
RELATIONAL_ID:   c9b8a71d-2e3f-4a5b-6c7d-8e9f0a1b2c3d
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def transcribe_audio_whisper(
    audio_path: Path,
    model: str = "tiny",
    output_dir: Path = None,
    language: str = None,
) -> Path:
    """
    Transcribes audio using whisper CLI tool or python whisper.
    Generates text output in target directory.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file for transcription not found: {audio_path}")

    if output_dir is None:
        output_dir = audio_path.parent

    output_dir.mkdir(parents=True, exist_ok=True)
    out_txt_file = output_dir / f"{audio_path.stem}_transcript.txt"

    whisper_bin = shutil.which("whisper")

    if whisper_bin:
        cmd = [
            whisper_bin,
            str(audio_path),
            "--model",
            model,
            "--output_dir",
            str(output_dir),
            "--output_format",
            "txt",
        ]
        if language:
            cmd.extend(["--language", language])

        logger.info(f"Executing Whisper CLI: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Whisper CLI execution error: {result.stderr}")
            raise RuntimeError(f"Whisper CLI transcription failed: {result.stderr}")

        generated_txt = output_dir / f"{audio_path.stem}.txt"
        if generated_txt.exists():
            if generated_txt != out_txt_file:
                shutil.move(generated_txt, out_txt_file)
            logger.info(f"Transcription complete: {out_txt_file}")
            return out_txt_file

    # Fallback to python library if CLI executable returns non-standard behavior or fallback needed
    try:
        import whisper

        logger.info(f"Loading Whisper Python model: '{model}'")
        w_model = whisper.load_model(model)
        result = w_model.transcribe(str(audio_path), language=language)
        text_content = result.get("text", "").strip()

        tmp_file = out_txt_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(text_content + "\n")
        os.replace(tmp_file, out_txt_file)

        logger.info(f"Transcription complete via Python whisper: {out_txt_file}")
        return out_txt_file
    except Exception as exc:
        raise RuntimeError(f"Whisper transcription failed: {exc}") from exc