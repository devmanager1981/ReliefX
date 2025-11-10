import json
from datetime import datetime
from uuid import uuid4
from pydantic import ValidationError
from typing import Dict, Any

# --- Import Shared Modules ---
from shared.models import RescueRequest # Imports the now-fixed model
from shared.clients.firestore_client import write_document
from shared.clients.pubsub_client import publish_message, TOPIC_ID_DAMAGE_ANALYSIS
# Import GEE utility (MOCKED)
from shared.clients.gee_utils import fetch_geospatial_stats 

def initiate_rescue_request(region_name: str, event_name: str) -> str:
    """
    Initiates the multi-agent workflow for a new rescue request.

    This is the first step in the production pipeline.
    1. Creates a unique Request ID.
    2. Fetches the AOI (now mocked to guarantee success).
    3. Creates and saves the initial RescueRequest document to Firestore.
    4. Triggers the Damage Analysis Agent (Phase 1) via Pub/Sub.
    """
    # 1. Generate a unique ID for this request
    request_id = str(uuid4())
    print(f"Initiating new workflow. Request ID: {request_id}")

    # 2. Fetch the AOI and Stats (Using the MOCKED function)
    # NOTE: We fetch the full stats, but ONLY the AOI is stored in RescueRequest.
    gee_stats = fetch_geospatial_stats(region_name)
    # Extract the necessary GeoJSON structure from the stats
    aoi_geojson_layer = gee_stats.get("aoi_geojson_layer", {})
    
    # Ensure the AOI is serialized correctly for storage in the RescueRequest model
    try:
        # Converts the dictionary received from the MOCKED gee_utils function into a JSON string
        aoi_geojson_str = json.dumps(aoi_geojson_layer)
        print("GEE Analysis (MOCKED) completed by Comm Router. AOI data is ready for storage.")
    except Exception as e:
        # Fallback in case serialization fails (shouldn't happen with the mock)
        print(f"CRITICAL ERROR: Failed to serialize MOCKED AOI GeoJSON: {e}")
        aoi_geojson_str = json.dumps({"type": "FeatureCollection", "features": []})

    # 3. Create and save the initial RescueRequest
    try:
        # IMPORTANT: Only pass the FIVE fields required by the corrected RescueRequest model.
        rescue_request = RescueRequest(
            request_id=request_id,
            region_name=region_name,
            event_name=event_name,
            timestamp=datetime.now().isoformat(),
            aoi_geojson=aoi_geojson_str  # Store the safe, serialized AOI
        )
        
        write_document("RescueRequests", request_id, rescue_request.model_dump())
        print(f"Rescue Request saved to Firestore: RescueRequests/{request_id}")

    except ValidationError as e:
        print(f"CRITICAL ERROR: Pydantic validation failed for RescueRequest. This likely means the model definition in models.py is wrong or missing a field: {e}")
        # Re-raise to signal a fatal error back to the HTTP handler
        raise
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to save RescueRequest to Firestore: {e}")
        # Re-raise to signal a fatal error back to the HTTP handler
        raise

    # 4. Trigger the Damage Analysis Agent (Phase 1) via Pub/Sub
    try:
        publish_message(
            TOPIC_ID_DAMAGE_ANALYSIS, 
            {"request_id": request_id}
        )
        print(f"Damage Analysis Agent (Phase 1) triggered via Pub/Sub topic: {TOPIC_ID_DAMAGE_ANALYSIS}")
    except Exception as e:
        print(f"ERROR: Failed to publish Pub/Sub message for Damage Analysis: {e}")
        # Since the request is already saved, we must re-raise the exception 
        # so the handler can return an appropriate error to the caller.
        raise
        
    return request_id