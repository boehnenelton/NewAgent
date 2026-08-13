import os
import whisper
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import tempfile
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Global model variable for lazy loading
model = None

def get_model():
    global model
    if model is None:
        logger.info("Loading Whisper model 'base'...")
        model = whisper.load_model("base")
    return model

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/transcribe', methods=['POST'])
def transcribe():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        logger.info(f"Processing transcription for: {file.filename}")
        m = get_model()
        result = m.transcribe(tmp_path)
        return jsonify({
            "text": result["text"],
            "language": result.get("language"),
            "segments": result.get("segments", [])
        })
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Whisper Flask Wrapper on port {port}...")
    app.run(host='0.0.0.0', port=port)
