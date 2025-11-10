import logging
import json
import os
import time
from datetime import datetime
from typing import Dict, Any

# Pydantic v2 validation error handling
from pydantic import ValidationError

# --- NEW IMPORTS (Using Vertex AI) ---
import vertexai
from vertexai.generative_models import GenerativeModel, Part
# --- FIX: Changed import path from google.cloud.aiplatform.* to vertexai.generative_models.*
from vertexai.generative_models import GenerationConfig as AIGenerationConfig
from vertexai.generative_models import Part as AIPart

# Shared components
from shared.models import RescueRequest, DamageReport
from shared.clients.pubsub_client import publish_message, TOPIC_ID_LOGISTICS
from shared.clients.firestore_client import get_document, write_document # <-- write_document ADDED FOR SAVING REPORT
from shared.clients.gee_utils import fetch_geospatial_stats 

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION (Production Settings) ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reliefmesh-hackathon")
REGION = os.getenv("GCP_REGION", "europe-west1") 
MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash") 
REQUEST_COLLECTION = "RescueRequests"
REPORT_COLLECTION = "DamageReports"

# --- LAZY CLIENT INITIALIZATION ---
_GENERATIVE_MODEL = None # Global placeholder for the initialized GenerativeModel instance
_VERTEX_INITIALIZED = False

def get_gemini_client():
    """Initializes and returns the global Vertex AI GenerativeModel instance."""
    global _GENERATIVE_MODEL, _VERTEX_INITIALIZED
    
    if not _VERTEX_INITIALIZED:
        # Initialize it here, inside the function on the first call
        try:
            # 1. Initialize Vertex AI first.
            vertexai.init(project=PROJECT_ID, location=REGION)
            
            # 2. Instantiate the GenerativeModel.
            _GENERATIVE_MODEL = GenerativeModel(MODEL_ID)
            _VERTEX_INITIALIZED = True
            logger.info(f"Vertex AI Client initialized for {MODEL_ID} in {REGION}.")
            
        except Exception as e:
            logger.critical(f"FATAL: Failed to initialize Vertex AI client: {e}")
            # Re-raise to stop the agent if the client can't be initialized
            raise
    return _GENERATIVE_MODEL

# --- LLM System Prompt ---
SYSTEM_PROMPT = """
You are a highly analytical disaster report generator. Your task is to synthesize raw geospatial statistics (Earth Engine data) into a concise, actionable JSON DamageReport.

Your output MUST strictly adhere to the provided JSON schema. Do not include any text, markdown, or commentary outside of the JSON object itself.

Crucial Directives:
1. Generate a narrative summary for 'weather_impact'.
2. Generate descriptive text for any 'road_cuts' identified.
3. If no road cuts are found, return an empty list for 'road_cuts'.
4. Do not make up any numbers; use the provided GEE statistics exactly as they are.
"""

# --- Core Analysis Workflow ---

def get_damage_analysis(request_id: str) -> bool:
    """
    Core function to orchestrate the damage analysis workflow.
    1. Fetches RescueRequest from Firestore (with retry).
    2. Calls GEE utility to fetch geospatial stats (simulated or real).
    3. Prompts the LLM to synthesize data into a DamageReport JSON.
    4. Validates and writes the DamageReport to Firestore.
    5. Triggers the Logistics Agent.
    """
    
    # 1. Fetch RescueRequest from Firestore with Retry (Fixes Race Condition)
    MAX_RETRIES = 5
    BACKOFF_SECONDS = 2
    request_data = None
    
    for attempt in range(MAX_RETRIES):
        try:
            request_data = get_document(REQUEST_COLLECTION, request_id)
            if request_data:
                # Validate the raw fetched data against the expected input schema
                request = RescueRequest(**request_data) 
                logger.info(f"Successfully fetched and validated RescueRequest {request_id} on attempt {attempt + 1}.")
                break
            else:
                logger.warning(f"Request ID {request_id} not found in Firestore on attempt {attempt + 1}/{MAX_RETRIES}.")
        except Exception as e:
            logger.error(f"Error fetching RescueRequest {request_id}: {e}")
            
        if attempt < MAX_RETRIES - 1:
            wait_time = BACKOFF_SECONDS * (2 ** attempt)
            logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
        else:
            logger.critical(f"Failed to fetch or validate RescueRequest {request_id} after {MAX_RETRIES} attempts.")
            return False # Failed to get the required input document

    # Get the Pydantic object (guaranteed to be valid here)
    # The 'request' variable is available from the successful 'break' block above
    try:
        request: RescueRequest 
    except NameError:
         # Should not happen if the retry loop executed correctly
         logger.critical(f"Critical error: RescueRequest object not defined after retry loop for ID: {request_id}")
         return False
    
    # 2. Call GEE utility to fetch geospatial stats
    logger.info(f"Fetching geospatial stats for: {request.region_name}...")
    try:
        # fetch_geospatial_stats handles both real GEE calls AND simulation/fallback
        # It is guaranteed to return a dictionary, even on failure.
        gee_stats = fetch_geospatial_stats(request.region_name, json.loads(request.aoi_geojson))
        
        # Check if the fallback was used (a good guardrail against GEE failure)
        if "CRITICAL FALLBACK" in gee_stats.get("analysis_region", ""):
             logger.warning("GEE Analysis returned CRITICAL FALLBACK (simulated) data.")
        else:
             logger.info("GEE Analysis completed successfully with live data (or default simulated if GEE is blocked).")
             
    except Exception as e:
        # This catch should theoretically not happen if gee_utils.py is robust
        logger.critical(f"GEE Analysis FAILED unexpectedly before returning fallback: {e}")
        return False 

    # 3. Prepare LLM Input and Generate Report
    user_prompt = f"Synthesize the following disaster request and geospatial statistics into a DamageReport JSON object. DO NOT DEVIATE from the provided statistics.\n\nDisaster Request:\n{json.dumps(request.model_dump(), indent=2)}\n\nGeospatial Statistics:\n{json.dumps(gee_stats, indent=2)}"

    try:
        # Configuration for structured JSON output using the DamageReport schema
        # AIGenerationConfig is now correctly imported from vertexai.generative_models
        config = AIGenerationConfig(
            response_mime_type="application/json",
            response_schema=DamageReport.model_json_schema(),
        )
        
        prompt = [AIPart.from_text(user_prompt)] # AIPart is now correctly imported

        model = get_gemini_client()
        
        response = model.generate_content(
            contents=prompt,
            config=config,
            system_instruction=SYSTEM_PROMPT, 
        )
        
        # 4. Process LLM response and Pydantic validation (Fixes Pydantic Model Mixup)
        report_json_str = response.text.strip()
        
        # Validate and parse the response text against the *DamageReport* Pydantic model
        report_data_dict = json.loads(report_json_str) 
        
        # Inject required metadata fields not generated by the LLM
        report_data_dict["request_id"] = request_id
        report_data_dict["analysis_model"] = MODEL_ID
        report_data_dict["timestamp"] = datetime.now().isoformat()
        
        # Final Pydantic validation before writing
        damage_report = DamageReport(**report_data_dict)
        
    except ValidationError as e:
        logger.critical(f"CRITICAL VALIDATION ERROR: LLM returned invalid JSON for DamageReport schema: {e}")
        logger.debug(f"Raw LLM Response: {report_json_str if 'report_json_str' in locals() else 'Not available'}")
        return False
    except Exception as e:
        logger.critical(f"CRITICAL ERROR: LLM Generation, JSON decoding, or general failure for {request_id}: {e}")
        return False

    # 5. Write to Firestore and Trigger Logistics Agent
    try:
        # Write the validated Pydantic model's dictionary representation to Firestore
        write_document(REPORT_COLLECTION, request_id, damage_report.model_dump())
        logger.info(f"Damage Report saved to Firestore: {REPORT_COLLECTION}/{request_id}")
        
        # Trigger Logistics Agent (Handoff to Phase 2)
        publish_message(TOPIC_ID_LOGISTICS, {"request_id": request_id})
        logger.info(f"Successfully triggered Logistics Agent for ID: {request_id}")
        
        return True

    except Exception as e:
        logger.critical(f"CRITICAL WRITE/PUBLISH ERROR for {request_id}: {e}")
        return False
}