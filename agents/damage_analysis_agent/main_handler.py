import os
import json
import base64
from flask import Flask, request, jsonify

# Import the core logic function
from .core_analysis import get_damage_analysis 

# Initialize Flask application
app = Flask(__name__)

@app.route('/', methods=['POST'])
def index():
    """
    HTTP Cloud Run entry point for the Damage Analysis Agent.
    
    This function handles Pub/Sub push messages, decodes the base64 payload
    containing the request ID, and triggers the core damage analysis logic.
    """
    if request.method != 'POST':
        return 'Method Not Allowed', 405

    # 1. Extract and decode the Pub/Sub message data
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            raise ValueError("Invalid Pub/Sub message format.")

        # Pub/Sub payload is base64 encoded in the 'data' field of the 'message' object
        pubsub_message = data['message']
        
        if 'data' not in pubsub_message:
            # Handles Pub/Sub keepalive or empty messages
            print("Received Pub/Sub keepalive or empty message.")
            return 'OK', 204 # No Content

        # Decode the base64 data to get the JSON string sent by the Communication Agent
        encoded_data = pubsub_message['data']
        message_data_bytes = base64.b64decode(encoded_data)
        message_data_str = message_data_bytes.decode('utf-8')
        message_json = json.loads(message_data_str)
        
        # Extract the request ID
        request_id = message_json.get('request_id')

        if not request_id:
            raise ValueError("Decoded payload missing 'request_id'.")

    except Exception as e:
        print(f"ERROR: Processing Pub/Sub message payload failed: {e}")
        # Return 400 for structural errors to signal Pub/Sub to retry appropriately
        return jsonify({'error': f'Invalid Pub/Sub payload or decoding error: {e}'}), 400 

    print(f"--- Pub/Sub trigger received for RescueRequest ID: {request_id} ---")

    # 2. Execute the core analysis logic
    success = get_damage_analysis(request_id)
    
    # 3. Acknowledge message (200 status prevents Pub/Sub from retrying the message)
    if success:
        return 'Damage Analysis completed successfully', 200
    else:
        # Internal failure logged, but message acknowledged to prevent infinite retries.
        print(f"Damage analysis failed internally for {request_id}.")
        return 'Analysis execution failed internally', 200