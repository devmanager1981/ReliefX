import json
import os
from pydantic import ValidationError
from google import genai
from google.genai import types 
from typing import Dict, Any, List
from datetime import datetime

# --- Import Shared Modules ---
from shared.models import DamageReport, LogisticsPlan
from shared.clients.firestore_client import get_document, write_document

# --- CONFIGURATION (Production Settings) ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reliefmesh-hackathon")
# Region must match the build plan for Vertex AI endpoints
REGION = os.getenv("GCP_REGION", "europe-west1") 
MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash") # Using Flash for logistics
PLAN_COLLECTION = "LogisticsPlans"

# --- AGENT GUARDRAILS (SECURITY AND FORMAT ENFORCEMENT) ---
SYSTEM_INSTRUCTION = (
    "You are the Logistics Planning Agent, a specialized AI for disaster relief. "
    "Your sole purpose is to analyze a DamageReport and an inventory of available resources "
    "to produce a structured, factual, and optimized LogisticsPlan. "
    "Your response MUST be a single, valid JSON object that strictly adheres to the provided `LogisticsPlan` schema. "
    "DO NOT include conversational text, preambles, apologies, or markdown (like ```json). "
    "Your role is to plan, not to chat. "
    "Prioritize resource allocation to areas with high population impact and critical road damage. "
    "DO NOT allocate more resources than are available in the inventory."
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
    client = None # Ensure client is None so get_logistics_plan fails fast

def get_available_resources_mock() -> Dict[str, int]:
    """
    PRODUCTION PLACEHOLDER: Simulates an external resource inventory system.
    
    In a full production environment, this function would make an API call
    to an external inventory database (e.g., SAP, Salesforce, or another microservice)
    to get real-time stock levels.
    """
    print("Fetching available resources (using production placeholder)...")
    return {
        "Water Filters (units)": 200,
        "Medical Kits (Level 2)": 50,
        "Ready-to-Eat Meals (kits)": 5000,
        "Tents (family size)": 150,
        "Fuel (liters)": 10000,
        "Heavy Machinery (bulldozers/excavators)": 2,
    }

def construct_llm_prompt(damage_report: DamageReport, resources: Dict[str, Any]) -> str:
    """Constructs the comprehensive prompt for the Logistics LLM."""
    
    # We serialize the inputs to JSON to include in the prompt
    damage_json = damage_report.model_dump_json(indent=2)
    resources_json = json.dumps(resources, indent=2)

    prompt = (
        f"Analyze the following disaster scenario and generate a Logistics Plan. "
        f"The output MUST be a single JSON object matching the required Pydantic schema for `LogisticsPlan`.\n\n"
        f"1. **Damage Report (Input Data)**:\n"
        f"   - Analysis:\n```json\n{damage_json}\n```\n\n"
        f"2. **Available Resources (Inventory)**:\n"
        f"   - Stock:\n```json\n{resources_json}\n```\n\n"
        f"Based on this data, define priority relief zones, outline the key logistics challenges, "
        f"and allocate the available resources to the zones. Ensure your plan is actionable."
    )
    return prompt

def get_logistics_plan(request_id: str) -> bool:
    """
    Core logic for the Logistics Agent (Phase 2).
    
    Workflow:
    1. Fetch DamageReport from Firestore.
    2. Get available resources (from placeholder inventory).
    3. Call the LLM (with guardrails) to synthesize the LogisticsPlan JSON.
    4. Validate, add metadata, and write the plan to Firestore.
    """
    if not client:
        print("Agent cannot run: GenAI Client failed to initialize.")
        return False

    # 1. Fetch the DamageReport (Input for this agent)
    damage_doc = get_document("DamageReports", request_id)
    if not damage_doc:
        print(f"Error: DamageReport {request_id} not found in Firestore. Cannot start planning.")
        return False
    
    try:
        damage_report = DamageReport(**damage_doc)
    except ValidationError as e:
        print(f"Input Validation Error: DamageReport data for {request_id} is malformed: {e}")
        return False

    # 2. Get Available Resources (Placeholder for external API)
    available_resources = get_available_resources_mock()

    # 3. Construct Prompt and LLM Call
    prompt = construct_llm_prompt(damage_report, available_resources)
    logistics_plan_schema = types.Schema.from_pydantic(LogisticsPlan)
    
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=logistics_plan_schema,
        system_instruction=SYSTEM_INSTRUCTION # Applying the security guardrail
    )

    print(f"Sending DamageReport to LLM for logistics planning for {request_id}...")
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[prompt],
            config=config,
        )
        plan_json = response.text
    except Exception as e:
        print(f"CRITICAL ERROR: Gemini API call failed: {e}")
        return False

    # 4. Validate and Write to Firestore
    try:
        report_data = json.loads(plan_json)
        
        # Inject required metadata fields not generated by the LLM
        report_data["request_id"] = request_id
        report_data["analysis_model"] = MODEL_ID
        report_data["timestamp"] = datetime.now().isoformat()
        
        # Pydantic validation (Guardrail): ensures LLM output matches our schema
        logistics_plan = LogisticsPlan(**report_data)
        
        write_document(PLAN_COLLECTION, request_id, logistics_plan.model_dump())
        print(f"Logistics Plan saved to Firestore: {PLAN_COLLECTION}/{request_id}")
        
        # This is the final step in the agent chain
        print(f"--- Workflow successfully completed for {request_id} ---")
        return True

    except ValidationError as e:
        print(f"CRITICAL VALIDATION ERROR: LLM returned invalid JSON for LogisticsPlan schema: {e}")
        print(f"Raw Response: {plan_json}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during final write: {e}")
        return False