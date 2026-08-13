#!/usr/bin/env python3
import argparse
import requests
import os
import sys
import json

def main():
    parser = argparse.ArgumentParser(description="Whisper CLI Tool - Transcribe audio via Flask API")
    parser.add_argument("file", help="Path to the audio file (wav, mp3, m4a, etc.)")
    parser.add_argument("--url", default="http://localhost:5000/transcribe", help="Flask API transcription endpoint")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)
        
    print(f"[*] Transcribing: {os.path.basename(args.file)}")
    print(f"[*] Sending request to: {args.url}")
    
    try:
        with open(args.file, 'rb') as f:
            files = {'file': f}
            response = requests.post(args.url, files=files)
            
            if response.status_code != 200:
                print(f"Error {response.status_code}: {response.text}")
                sys.exit(1)
                
            data = response.json()
            
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print("\n--- Transcription ---\n")
                print(data.get("text", "No text returned."))
                print("\n---------------------\n")
                
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the Flask server. Is it running?")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
