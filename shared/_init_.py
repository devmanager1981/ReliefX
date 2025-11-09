import json
from datetime import datetime
from uuid import uuid4
from pydantic import ValidationError
# Import all models and required clients
from shared.models import RescueRequest, DamageReport, RoadCut
from shared.clients.firestore_client import write_document
from shared.clients.pubsub_client import publish_message, TOPIC_ID_LOGISTICS # IMPORTANT: Now triggering LOGISTICS directly

# --- CONFIGURATION ---
# Define a standard GeoJSON AOI for the POC (Cebu Province, Philippines)
CEBU_AOI_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [
            [123.3, 9.8], [124.0, 9.8], [124.0, 10.8], [123.3, 10.8], [123.3, 9.8]
        ]
    ]
}

def mock_damage_report(request_id: str):
    """
    MOCKS the execution of the Damage Analysis Agent (Phase 1).
    Creates a realistic, structured DamageReport and writes it to Firestore,
    which is the required input for the Logistics Agent.
    """
    print(f"MOCKING: Creating dummy DamageReport for ID: {request_id}")
    
    # Hardcoded, realistic road cuts for the Cebu AOI
    road_cuts = [
        RoadCut(
            latitude=10.31,
            longitude=123.95,
            severity_score=5,
            description="Major bridge on N. Bacalso Ave. washed out by floodwaters; completely impassable."
        ),
        RoadCut(
            latitude=10.25,
            longitude=123.83,
            severity_score=4,
            description="Landslide near Barangay Sudlon I, blocking one lane of the mountain road."
        ),
        RoadCut(
            latitude=10.55,
            longitude=124.05,
            severity_score=3,
            description="Minor road collapse near Daanbantayan, passable only by heavy machinery."
        )
    ]
    
    # Create the DamageReport object
    mock_report = DamageReport(
        request_id=request_id,
        flood_km2=68.5, # Realistic flood area for a large typhoon event
        damaged_buildings_count=1240, # Realistic count
        infrastructure_damage_summary="Significant and widespread damage across the central and southern sectors. Three critical road arteries are severed due to washouts and landslides, isolating large population centers. Power infrastructure is compromised in 90% of the AOI.",
        road_cuts=road_cuts,
        analysis_model="MOCK_DamageAgent_Disabled" # Flagging the mock status
    )

    # Write the mock document to Firestore
    try:
        write_document("DamageReports", request_id, mock_report)
        print(f"MOCKING SUCCESS: DamageReport/{request_id} created.")
    except Exception as e:
        print(f"ERROR: Failed to write MOCK DamageReport to Firestore: {e}")
        raise RuntimeError("Failed to store mock damage report.")


def initiate_rescue_request(region_name: str, event_name: str) -> str:
    """
    Creates the initial RescueRequest document, MOCKS the Damage Agent, 
    and triggers the Logistics Agent.
    """
    request_id = str(uuid4()) # Generate a unique request ID
    timestamp = datetime.utcnow().isoformat()
    
    # 1. Prepare and Write the RescueRequest Pydantic model
    aoi_geojson_str = json.dumps(CEBU_AOI_GEOJSON)
    
    try:
        new_request = RescueRequest(
            request_id=request_id,
            region_name=region_name,
            event_name=event_name,
            aoi_geojson=aoi_geojson_str,
            timestamp=timestamp,
            pre_event_uri=None, 
            post_event_uris=[]
        )
        write_document("RescueRequests", request_id, new_request)
        print(f"RescueRequest {request_id} successfully created.")
    except Exception as e:
        print(f"Error creating/writing RescueRequest to Firestore: {e}")
        raise RuntimeError("Failed to store initial request.")
        
    # 2. MOCK THE DAMAGE AGENT (Required by user while the actual agent is fixed)
    try:
        mock_damage_report(request_id)
    except Exception as e:
        # If mock creation fails, we cannot proceed to logistics
        print(f"CRITICAL MOCK FAILURE: Cannot proceed. {e}")
        raise
        
    # 3. Trigger the next active agent (Logistics Agent) via Pub/Sub
    try:
        publish_message(
            TOPIC_ID_LOGISTICS, # Trigger Phase 2 directly
            {"request_id": request_id}
        )
        print(f"Logistics workflow triggered for ID: {request_id}")
    except Exception as e:
        print(f"Error publishing Pub/Sub message for Logistics: {e}")
        pass 
        
    return request_id

if __name__ == '__main__':
    # Test execution
    TEST_REGION = "Cebu Province (Test Run)"
    TEST_EVENT = "Typhoon Kalmaegi (Test)"
    print(f"Running Communication Router test for {TEST_EVENT} in {TEST_REGION}")
    
    try:
        new_id = initiate_rescue_request(TEST_REGION, TEST_EVENT)
        print(f"\n--- COMM ROUTER SUCCESSFUL ---")
        print(f"New Request ID: {new_id}")
        print("Check 'RescueRequests' and 'DamageReports' collections in Firestore.")
        print("Check Cloud Run logs for 'logistics-trigger' Pub/Sub message.")
    except Exception as e:
        print(f"\n--- COMM ROUTER FAILED ---")
        print(f"Failure reason: {e}")