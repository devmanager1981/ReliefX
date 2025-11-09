import os
import json
from flask import Flask, request, jsonify
from comm_router import initiate_rescue_request # The core logic is imported

# Initialize Flask application
app = Flask(__name__)

@app.route('/', methods=['POST'])
def index():
    """
    HTTP Cloud Run entry point for the Communication Router.
    This public endpoint is called by the Streamlit frontend.
    
    Payload expected:
    {
        "region_name": "Cebu Province, Philippines",
        "event_name": "Typhoon Kalmaegi"
    }
    """
    
    data = request.get_json(silent=True)
    if not data:
        print("Endpoint Error: No JSON payload received.")
        return jsonify({"status": "error", "message": "No data received"}), 400

    region_name = data.get('region_name')
    event_name = data.get('event_name')

    # --- Security Guardrail (OWASP Input Validation) ---
    # Protects against injection attacks or payload stuffing.
    # We enforce that inputs exist and are of reasonable length.
    if not region_name or not event_name or len(region_name) > 100 or len(event_name) > 100:
        print(f"Endpoint Error: Invalid input. Region: {region_name}, Event: {event_name}")
        return jsonify({"status": "error", "message": "Invalid or missing 'region_name' or 'event_name'."}), 400
    # --- End Security Guardrail ---

    print(f"Received valid request to initiate workflow for {event_name} in {region_name}")
    
    try:
        # Call the core logic to fetch GEE AOI, create the RescueRequest,
        # and trigger the Damage Analysis Agent (Phase 1).
        request_id = initiate_rescue_request(region_name, event_name)
        
        # Respond to the frontend with success and the tracking ID
        return jsonify({
            "status": "success", 
            "message": "Workflow initiated successfully. Damage Analysis Agent triggered.", 
            "request_id": request_id
        }), 200
        
    except Exception as e:
        print(f"CRITICAL ERROR in Comm Router main_handler: {e}")
        return jsonify({"status": "error", "message": f"Server error: Failed to initiate workflow."}), 500

if __name__ == '__main__':
    # This block is for LOCAL DEVELOPMENT testing only (e.g., `python main_handler.py`)
    # In production (Cloud Run), a Gunicorn server is used as the entry point.
    print("--- Starting Communication Router in local development mode ---")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)