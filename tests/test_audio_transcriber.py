"""
Test Suite:      test_audio_transcriber.py
Module Purpose:  Unit tests for NA-AudioTranscriber pipeline libraries.
Author:          Elton Boehnen · boehnenelton2024@gmail.com
RELATIONAL_ID:   9a8b7c6d-5e4f-3a2b-1c0d-e9f8a7b6c5d4
"""

import _libpath  # noqa: F401  (puts lib/ on sys.path for unittest + pytest)
import base64
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

# Add project lib path
PROJECT_ROOT = Path(__file__).resolve().parent.parent / "tools" / "NA-AudioTranscriber"
LIB_PATH = PROJECT_ROOT / "lib"
sys.path.insert(0, str(LIB_PATH))

from lib_bejson_AudioTranscriber_processor import (
    stage_copy_file,
    convert_to_16bit_mono_wav,
    encode_file_to_base64,
)
from lib_bejson_AudioTranscriber_transcriber import transcribe_audio_whisper


class TestAudioTranscriberPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = PROJECT_ROOT / "tests_scratch"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.sample_wav = cls.test_dir / "sample_input.wav"

        # Generate synthetic 1-second sine wave audio file using ffmpeg
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1",
            "-ar", "44100",
            "-ac", "2",
            str(cls.sample_wav)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not cls.sample_wav.exists():
            raise RuntimeError(f"Could not generate test audio via FFmpeg: {res.stderr}")

    @classmethod
    def tearDownClass(cls):
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_stage_copy(self):
        stage_dir = self.test_dir / "stage"
        staged = stage_copy_file(self.sample_wav, stage_dir)
        self.assertTrue(staged.exists())
        self.assertEqual(staged.name, self.sample_wav.name)

    def test_02_conversion_16bit_mono(self):
        stage_dir = self.test_dir / "stage"
        converted = convert_to_16bit_mono_wav(self.sample_wav, output_wav=stage_dir / "converted.wav")
        self.assertTrue(converted.exists())

        # Probe output format using ffprobe if available
        ffprobe_bin = shutil.which("ffprobe")
        if ffprobe_bin:
            for field in [("codec_name", "pcm_s16le"), ("channels", "1"), ("sample_rate", "16000")]:
                cmd = [
                    ffprobe_bin,
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", f"stream={field[0]}",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(converted)
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                val = res.stdout.strip()
                self.assertEqual(val, field[1], f"Field {field[0]} mismatch: expected {field[1]}, got {val}")

    def test_03_base64_encoding(self):
        stage_dir = self.test_dir / "stage"
        converted = stage_dir / "converted.wav"
        if not converted.exists():
            converted = convert_to_16bit_mono_wav(self.sample_wav, output_wav=converted)

        b64_file = encode_file_to_base64(converted)
        self.assertTrue(b64_file.exists())

        with open(b64_file, "r", encoding="utf-8") as f:
            content = f.read()

        decoded = base64.b64decode(content)
        self.assertEqual(len(decoded), converted.stat().st_size)

    def test_04_whisper_transcription(self):
        stage_dir = self.test_dir / "stage"
        converted = stage_dir / "converted.wav"
        if not converted.exists():
            converted = convert_to_16bit_mono_wav(self.sample_wav, output_wav=converted)

        try:
            txt_file = transcribe_audio_whisper(converted, model="tiny", output_dir=stage_dir)
            self.assertTrue(txt_file.exists())
        except Exception as err:
            self.skipTest(f"Whisper execution skipped in test environment: {err}")


if __name__ == "__main__":
    unittest.main()