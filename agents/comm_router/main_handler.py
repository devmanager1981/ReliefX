import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS 
from agents.comm_router.comm_router import initiate_rescue_request
import traceback # Added for printing stack traces on error

# Initialize Flask application
app = Flask(__name__)

# NOTE: Set the UI_ORIGIN environment variable on your Cloud Run service
UI_ORIGIN = os.getenv("UI_ORIGIN", "*") 
CORS(app, origins=[UI_ORIGIN]) 


@app.route('/', methods=['POST'])
def index():
    """
    HTTP Cloud Run entry point for the Communication Router.
    This public endpoint is called by the Streamlit frontend.
    """
    
    # Use request.get_json(silent=True) to avoid crashing on non-JSON body
    data = request.get_json(silent=True)
    
    if not data:
        raw_data = request.data.decode('utf-8', errors='ignore')
        print(f"Endpoint Error: No JSON payload received. Raw Body: {raw_data}")
        return jsonify({"status": "error", "message": "Invalid request: Must send 'application/json' payload."}), 400

    region_name = data.get('region_name')
    event_name = data.get('event_name')

    # --- Security Guardrail (OWASP Input Validation) ---
    if not region_name or not event_name or len(region_name) > 100 or len(event_name) > 100:
        print(f"Endpoint Error: Invalid input. Region: {region_name}, Event: {event_name}")
        return jsonify({"status": "error", "message": "Invalid or missing 'region_name' or 'event_name'."}), 400
    # --- End Security Guardrail ---

    print(f"Received valid request to initiate workflow for {event_name} in {region_name}")
    
    try:
        # Call the core logic to fetch GEE AOI (now mocked), create the RescueRequest,
        # and trigger the Damage Analysis Agent (Phase 1).
        request_id = initiate_rescue_request(region_name, event_name)
        
        # Respond to the frontend with success and the tracking ID
        return jsonify({
            "status": "success", 
            "message": "Workflow initiated successfully. Damage Analysis Agent triggered.", 
            "request_id": request_id
        }), 200
        
    except Exception as e:
        # CRITICAL: Log the detailed exception that caused the failure
        print("--- CRITICAL INITIATION ERROR ---")
        print(f"Failed to initiate workflow: {e}")
        # Print full stack trace for detailed debugging in Cloud Run logs
        traceback.print_exc() 
        print("----------------------------------")
        
        # Return a clean 500 error to the caller
        return jsonify({"status": "error", "message": f"Server error: Failed to initiate workflow. Details logged."}), 500

if __name__ == '__main__':
    # For local development/testing only
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))