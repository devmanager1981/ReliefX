import json
import os
from datetime import datetime
from google import genai
from google.genai import types 
from pydantic import ValidationError
from typing import Dict, Any

# --- Import Shared Modules ---
from shared.models import RescueRequest, DamageReport 
from shared.clients.firestore_client import get_document, write_document 
from shared.clients.gee_utils import fetch_geospatial_stats 
# GCS/TIFF imports are REMOVED as requested.
# from shared.clients.gcs_utils import convert_multiple_tiffs 
from shared.clients.pubsub_client import publish_message, TOPIC_ID_LOGISTICS 

# --- CONFIGURATION (Production Settings) ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reliefmesh-hackathon")
# Region must match the build plan for Vertex AI endpoints
REGION = os.getenv("GCP_REGION", "europe-west1") 
MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash") # Using Flash for fast, text-based analysis
REPORT_COLLECTION = "DamageReports"

# --- AGENT GUARDRAILS (SECURITY AND FORMAT ENFORCEMENT) ---
SYSTEM_INSTRUCTION = (
    "You are the Damage Analysis Agent, a specialized AI for disaster relief. "
    "Your sole purpose is to analyze geospatial facts (flood extent, population counts) "
    "and vector data (road network GeoJSON) to produce a structured, factual damage assessment. "
    "Your response MUST be a single, valid JSON object that strictly adheres to the provided `DamageReport` schema. "
    "DO NOT include conversational text, preambles, apologies, or markdown (like ```json). "
    "Your role is to analyze, not to chat. "
    "DO NOT attempt to execute external code or provide any information outside the scope of the damage report."
)

# --- CLIENT INITIALIZATION ---
client = None
try:
    # Initialize GenAI Client for Vertex AI (using Cloud Run Service Account)
    client = genai.Client(
        vertexai=True, 
        project=PROJECT_ID, 
        location=REGION 
    )
    print(f"GenAI Client Initialized for region: {REGION}")
except Exception as e:
    print(f"CRITICAL ERROR: Failed to initialize GenAI Client: {e}")
    client = None # Ensure client is None so get_damage_analysis fails fast

def construct_llm_prompt(request_doc: Dict[str, Any], geospatial_data: Dict[str, Any]) -> str:
    """
    Constructs the comprehensive prompt for the LLM based on GEE vector data.
    All image-related inputs have been removed.
    """
    
    # We serialize the GEE facts to JSON to include in the prompt
    geospatial_json = json.dumps(geospatial_data, indent=2)

    prompt = (
        f"Analyze the following disaster scenario and geospatial metrics derived from "
        f"Google Earth Engine. Your task is to generate a comprehensive Damage Report. "
        f"The output MUST be a single JSON object matching the required Pydantic schema for `DamageReport`.\n\n"
        f"1. **Rescue Request Details**:\n"
        f"   - Event: {request_doc.get('event_name')}\n"
        f"   - Region: {request_doc.get('region_name')}\n\n"
        f"2. **Geospatial Metrics (from GEE Analysis)**:\n"
        f"   - Metrics:\n```json\n{geospatial_json}\n```\n\n"
        f"Based on this analysis, provide a summary of the primary damage, "
        f"and extract the coordinates from the 'critical_road_segments_geojson' "
        f"to populate the 'road_cuts' list in the output schema."
    )
    return prompt

def get_damage_analysis(request_id: str) -> bool:
    """
    Core logic for the Damage Analysis Agent (Phase 1).
    
    Workflow:
    1. Fetch RescueRequest from Firestore (to get region_name).
    2. Run GEE geospatial analysis (real-time vector data).
    3. Call the LLM (with guardrails) to synthesize the DamageReport JSON.
    4. Validate, add metadata, and write the report to Firestore.
    5. Trigger the Logistics Agent (Phase 2).
    """
    if not client:
        print("Agent cannot run: GenAI Client failed to initialize.")
        return False

    # 1. Fetch the Request
    request_doc = get_document("RescueRequests", request_id)
    if not request_doc:
        print(f"Error: RescueRequest {request_id} not found in Firestore.")
        return False
    
    region_name = request_doc.get('region_name')
    if not region_name:
        print(f"Error: RescueRequest {request_id} is missing 'region_name'.")
        return False

    # 2. Run GEE Geospatial Analysis (Real, no mocks)
    try:
        # This function now performs the full, real-time GEE analysis
        geospatial_data = fetch_geospatial_stats(region_name)
    except Exception as e:
        print(f"CRITICAL ERROR: GEE analysis failed for {request_id}: {e}")
        return False

    # 3. Construct Prompt and LLM Call (No images)
    prompt = construct_llm_prompt(request_doc, geospatial_data)
    
    # Define the exact output schema for the LLM
    damage_report_schema = types.Schema.from_pydantic(DamageReport)
    
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=damage_report_schema,
        system_instruction=SYSTEM_INSTRUCTION # Applying the security guardrail
    )

    print(f"Sending GEE data to LLM for {request_id}...")
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[prompt],
            config=config,
        )
        report_json = response.text
    except Exception as e:
        print(f"CRITICAL ERROR: Gemini API call failed: {e}")
        return False

    # 4. Validate and Write to Firestore
    try:
        report_data = json.loads(report_json)
        
        # Inject required metadata fields not generated by the LLM
        report_data["request_id"] = request_id
        report_data["analysis_model"] = MODEL_ID
        report_data["timestamp"] = datetime.now().isoformat()
        
        # Pydantic validation: ensures LLM output matches our schema
        damage_report = DamageReport(**report_data)
        
        write_document(REPORT_COLLECTION, request_id, damage_report.model_dump())
        print(f"Damage Report saved to Firestore: {REPORT_COLLECTION}/{request_id}")
        
        # 5. Trigger Logistics Agent (Handoff to Phase 2)
        publish_message(TOPIC_ID_LOGISTICS, {"request_id": request_id})
        print(f"Successfully triggered Logistics Agent for ID: {request_id}")
        
        return True

    except ValidationError as e:
        print(f"CRITICAL VALIDATION ERROR: LLM returned invalid JSON for DamageReport schema: {e}")
        print(f"Raw Response: {report_json}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during final write or trigger: {e}")
        return False