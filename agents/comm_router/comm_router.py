import json
from datetime import datetime
from uuid import uuid4
from pydantic import ValidationError
from typing import Dict, Any

# --- Import Shared Modules ---
from shared.models import RescueRequest
from shared.clients.firestore_client import write_document
from shared.clients.pubsub_client import publish_message, TOPIC_ID_DAMAGE_ANALYSIS
# Import GEE utility to fetch the REAL Area of Interest (AOI)
from shared.clients.gee_utils import fetch_aoi_geojson 

def initiate_rescue_request(region_name: str, event_name: str) -> str:
    """
    Initiates the multi-agent workflow for a new rescue request.

    This is the first step in the production pipeline.
    1. Creates a unique Request ID.
    2. Fetches the real AOI (GeoJSON) from Google Earth Engine.
    3. Creates and saves the initial RescueRequest document to Firestore.
    4. Triggers the Damage Analysis Agent (Phase 1) via Pub/Sub.
    
    Args:
        region_name: The target geographical area (e.g., "Cebu Province, Philippines").
        event_name: The name of the disaster (e.g., "Typhoon Kalmaegi").

    Returns:
        The unique request ID for tracking the workflow.
    """
    # 1. Generate a unique ID for this request
    request_id = str(uuid4())
    print(f"Initiating new workflow. Request ID: {request_id}")

    # 2. Fetch the real AOI from GEE (REMOVING MOCK)
    try:
        # This function calls GEE to get the boundary for the selected region
        aoi_data = fetch_aoi_geojson(region_name)
        aoi_geojson_str = json.dumps(aoi_data)
        print(f"Successfully fetched GEE AOI for {region_name}.")
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to fetch GEE AOI for '{region_name}': {e}")
        raise RuntimeError(f"Could not fetch GEE AOI: {e}") from e

    # 3. Create and save the initial RescueRequest
    try:
        rescue_request = RescueRequest(
            request_id=request_id,
            region_name=region_name,
            event_name=event_name,
            timestamp=datetime.now().isoformat(),
            aoi_geojson=aoi_geojson_str  # Store the real AOI
        )
        
        write_document("RescueRequests", request_id, rescue_request.model_dump())
        print(f"Rescue Request saved to Firestore: RescueRequests/{request_id}")

    except ValidationError as e:
        print(f"CRITICAL ERROR: Pydantic validation failed for RescueRequest: {e}")
        raise
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to save RescueRequest to Firestore: {e}")
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
        # Log the error but allow the function to succeed as the RescueRequest was saved.
        # Downstream monitoring should alert on failed Pub/Sub triggers.
        pass 
        
    return request_id