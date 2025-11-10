import os
import logging
from flask import Flask, request, jsonify
from pydantic import ValidationError
from datetime import datetime

# Shared components
from shared.models import RescueRequest
from shared.clients.pubsub_client import publish_message, TOPIC_ID_DAMAGE_ANALYSIS
from shared.clients.firestore_client import write_document

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Ensure these environment variables are set in your Cloud Run service
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
REQUEST_COLLECTION = os.getenv("FIRESTORE_REQUEST_COLLECTION", "RescueRequests")
# TOPIC_ID_DAMAGE_ANALYSIS is imported from shared.clients.pubsub_client

# Basic Flask app setup
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health_check():
    """
    Standard health check endpoint for Cloud Run.
    """
    return "ReliefX Communication Agent is running!", 200

@app.route("/rescue-request", methods=["POST"])
def receive_rescue_request():
    """
    Receives a new rescue request, validates it, writes to Firestore,
    and publishes a message to trigger damage analysis.
    """
    if not request.is_json:
        logger.error("Request must be JSON")
        return jsonify({"error": "Request must be JSON"}), 400

    try:
        # Validate incoming JSON against Pydantic model
        # The timestamp and status will be set by the agent, not the client
        request_data = request.get_json()
        
        # Add server-side metadata before validation or Pub/Sub
        request_data["timestamp"] = datetime.now().isoformat()
        request_data["status"] = "RECEIVED" # Initial status
        
        rescue_request = RescueRequest(**request_data)
        logger.info(f"Received and validated RescueRequest: {rescue_request.request_id}")

        # 1. Write to Firestore
        write_document(REQUEST_COLLECTION, rescue_request.request_id, rescue_request.model_dump())
        logger.info(f"RescueRequest {rescue_request.request_id} written to Firestore.")

        # 2. Publish message to Pub/Sub to trigger Damage Analysis Agent
        pubsub_payload = {"request_id": rescue_request.request_id}
        publish_message(TOPIC_ID_DAMAGE_ANALYSIS, pubsub_payload)
        logger.info(f"Message published to {TOPIC_ID_DAMAGE_ANALYSIS} for request ID: {rescue_request.request_id}")

        return jsonify({
            "status": "success",
            "message": "Rescue request received and processing initiated.",
            "request_id": rescue_request.request_id
        }), 202 # 202 Accepted, as processing is asynchronous

    except ValidationError as e:
        logger.error(f"Validation error for incoming request: {e.errors()}")
        return jsonify({"error": "Invalid request payload", "details": e.errors()}), 400
    except Exception as e:
        logger.exception(f"An unexpected error occurred in receive_rescue_request: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    # In a production Cloud Run environment, gunicorn would typically manage this.
    # This block is mostly for local testing.
    if not PROJECT_ID:
        logger.critical("GCP_PROJECT_ID environment variable not set. Exiting.")
        exit(1)
    
    # Cloud Run provides the PORT env var
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False) # debug=False for prod-like testing