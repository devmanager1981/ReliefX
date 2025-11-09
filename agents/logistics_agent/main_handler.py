import os
import base64
import json
from flask import Flask, request, jsonify

# Import the core logic function
from core_reasoning import get_logistics_plan

# Initialize Flask application
app = Flask(__name__)

@app.route('/', methods=['POST'])
def index():
    """
    HTTP Cloud Run entry point for the Logistics Agent (Phase 2).
    
    This function handles Pub/Sub push messages from the Damage Analysis Agent,
    decodes the base64 payload to get the request ID, and triggers the
    core logistics planning logic.
    """
    if request.method != 'POST':
        return 'Method Not Allowed', 405

    # 1. Extract and decode the Pub/Sub message data
    try:
        data = request.get_json(silent=True)
        if not data or 'message' not in data or 'data' not in data['message']:
            # Security Hardening: Reject requests that are not valid Pub/Sub envelopes
            print(f"Endpoint Error: Invalid Pub/Sub message format received.")
            return jsonify({"status": "error", "message": "Invalid Pub/Sub message format."}), 400

        # Decode the base64 data to get the JSON string sent by the Damage Agent
        encoded_data = data['message']['data']
        message_data_bytes = base64.b64decode(encoded_data)
        message_data_str = message_data_bytes.decode('utf-8')
        payload = json.loads(message_data_str)
        
        # Extract the request ID
        request_id = payload.get('request_id')

        if not request_id:
            raise ValueError("Decoded payload missing 'request_id'.")

    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to decode Pub/Sub JSON payload: {e}")
        return jsonify({'error': f'Invalid JSON in Pub/Sub message: {e}'}), 400
    except Exception as e:
        print(f"ERROR: Processing Pub/Sub message payload failed: {e}")
        return jsonify({'error': f'Invalid Pub/Sub payload or decoding error: {e}'}), 400 

    print(f"--- Pub/Sub trigger received for Logistics Plan, ID: {request_id} ---")

    # 2. Execute the core analysis logic
    success = get_logistics_plan(request_id)
    
    # 3. Acknowledge message (200 status prevents Pub/Sub from retrying)
    if success:
        print(f"Logistics planning for {request_id} completed successfully.")
        return 'Logistics planning completed successfully', 200
    else:
        # Internal failure logged, but message acknowledged to prevent infinite retries.
        print(f"Logistics planning failed internally for {request_id}.")
        return 'Analysis execution failed internally', 200 

if __name__ == '__main__':
    # This block is for LOCAL DEVELOPMENT testing only (e.g., `python main_handler.py`)
    # In production (Cloud Run), a Gunicorn server is used as the entry point.
    print("--- Starting Logistics Agent in local development mode ---")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8081)), debug=True)