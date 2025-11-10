import streamlit as st
import os
import json
import requests
import pandas as pd
import time
from typing import Dict, Any, Optional, Tuple

# --- Import Shared Modules (Now using the real clients) ---
# NOTE: These imports assume the 'shared/clients' structure is correctly 
# configured in your container's PYTHONPATH (e.g., in the Dockerfile).
try:
    # Attempt to import the real Firestore client
    from shared.clients.firestore_client import get_document
except ImportError:
    # Mock function for local testing if shared module is not available
    def get_document(collection, doc_id):
        print("WARNING: Firestore client mock used. Ensure 'shared' module is configured correctly.")
        return None

# --- PRODUCTION CONFIGURATION ---
# Load configuration from environment variables set in Cloud Run
# Ensure this is the correct URL for your Comm Router deployment
COMM_ROUTER_URL = os.getenv("COMM_ROUTER_URL", "https://comm-router-agent-438247172781.europe-west1.run.app") # Fallback for local testing
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reliefmesh-hackathon")

# Define the approved regions for analysis (Security Guardrail)
APPROVED_REGIONS = [
    "Cebu Province, Philippines",
    "Gia Lai Province, Vietnam",
    "Northern Mindanao, Philippines"
]
REPORT_COLLECTION = "DamageReports"
LOGISTICS_COLLECTION = "LogisticsPlans"
REQUEST_COLLECTION = "RescueRequests"

# --- SESSION STATE INITIALIZATION ---
if 'current_request_id' not in st.session_state:
    st.session_state.current_request_id = None
if 'workflow_running' not in st.session_state:
    st.session_state.workflow_running = False

# --- CORE FUNCTIONS ---

def fetch_workflow_status(request_id: str) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict]]:
    """Fetches the three workflow documents from Firestore by request_id."""
    if not request_id:
        return None, None, None
    
    # Fetch the original request
    req_doc = get_document(REQUEST_COLLECTION, request_id)
    
    # Fetch the damage analysis report (Phase 1 result)
    dam_doc = get_document(REPORT_COLLECTION, request_id)
    
    # Fetch the logistics plan (Phase 2 result)
    log_doc = get_document(LOGISTICS_COLLECTION, request_id)
    
    return req_doc, dam_doc, log_doc

def handle_submit(region_name: str, event_name: str):
    """
    Calls the external Communication Router service to initiate the workflow.
    This runs the Geo-Spatial query, saves the request, and triggers the first agent.
    """
    st.session_state.workflow_running = True
    st.session_state.current_request_id = None
    
    st.sidebar.info(f"Initiating workflow for **{event_name}** in **{region_name}**...")
    
    payload = {
        "region_name": region_name,
        "event_name": event_name
    }
    
    try:
        # Call the public HTTP endpoint of the Communication Router
        response = requests.post(COMM_ROUTER_URL, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            request_id = result.get("request_id")
            
            if request_id:
                st.session_state.current_request_id = request_id
                st.sidebar.success(f"Workflow successfully started! Tracking ID: **{request_id}**")
                # Immediately rerun to start the polling loop
                st.rerun() 
            else:
                st.sidebar.error("Router failed to return a valid request ID.")
                st.session_state.workflow_running = False
        else:
            error_message = response.json().get("message", "Unknown error from router.")
            st.sidebar.error(f"Router Error: {error_message}")
            st.session_state.workflow_running = False

    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"Network/Connection Error: Could not reach Communication Router. ({e})")
        st.session_state.workflow_running = False
    except Exception as e:
        st.sidebar.error(f"An unexpected error occurred: {e}")
        st.session_state.workflow_running = False


# --- STREAMLIT UI LAYOUT ---

st.set_page_config(
    page_title="ReliefMesh Agent Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🌊 ReliefMesh Disaster Response Dashboard")
st.caption(f"Project ID: {PROJECT_ID} | Comm Router: `{COMM_ROUTER_URL}`")

# 1. Sidebar for Input
with st.sidebar:
    st.header("1. Initiate New Request")

    selected_region = st.selectbox(
        "Select Target Region:",
        options=[""] + APPROVED_REGIONS,
        index=0,
        placeholder="Choose a region..."
    )
    
    event_name = st.text_input(
        "Enter Disaster/Event Name:",
        placeholder="e.g., Typhoon Kalmaegi"
    )

    if st.button("Start AI Workflow", type="primary", disabled=st.session_state.workflow_running):
        if selected_region and event_name:
            handle_submit(selected_region, event_name)
        else:
            st.sidebar.warning("Please select a region and enter an event name.")

    st.markdown("---")
    # Display current status and tracking info
    st.subheader("Current Status")
    if st.session_state.current_request_id:
        st.markdown(f"**Tracking ID:**")
        st.code(st.session_state.current_request_id, language="text")
    
    if st.session_state.workflow_running:
        st.info("Workflow is running... Data will appear on the right when available.")
    else:
        st.success("Workflow Complete or Idle.")


# 2. Main Dashboard Area

# Fetch current status data
req_doc, dam_doc, log_doc = fetch_workflow_status(st.session_state.current_request_id)

if not req_doc and not st.session_state.workflow_running:
    st.info("Start a new AI workflow using the form on the left sidebar.")
elif st.session_state.current_request_id:
    
    tab1, tab2, tab3 = st.tabs(["Request Details", "Damage Report (Phase 1)", "Logistics Plan (Phase 2)"])

    # --- Tab 1: Request Details (Base Data) ---
    with tab1:
        st.header("Original Rescue Request")
        if req_doc:
            st.metric("Region", req_doc.get('region_name', 'N/A'))
            st.metric("Event Name", req_doc.get('event_name', 'N/A'))
            st.metric("Time Initiated", req_doc.get('timestamp', 'N/A'))
            
            st.markdown("---")
            st.markdown("#### Area of Interest (GeoJSON):")
            st.code(req_doc.get('aoi_geojson', 'N/A'), language='json')
        else:
            st.warning("Awaiting initial request document...")


    # --- Tab 2: Damage Analysis (Phase 1) ---
    with tab2:
        st.header("Disaster Damage Analysis")
        if dam_doc:
            st.success("✅ Damage Analysis Complete")
            
            cols = st.columns(3)
            # Use data from GEE/Geo-Spatial Analysis, which is enriched by the LLM
            cols[0].metric("Affected Population", f"{dam_doc.get('affected_population_estimate', 0):,}")
            cols[1].metric("Flood Extent", f"{dam_doc.get('flood_extent_km2', 0):.2f} km²")
            cols[2].metric("Infrastucture Score", f"{dam_doc.get('damage_score', 'N/A')}/10")
            
            st.markdown("---")
            st.markdown("#### Infrastructure Damage Summary (from LLM):")
            st.markdown(f"> {dam_doc.get('infrastructure_damage_summary', 'N/A')}")

            st.markdown("---")
            st.markdown("#### Critical Road Cuts (from LLM):")
            if "road_cuts" in dam_doc and dam_doc["road_cuts"]:
                # The LLM output for road cuts is designed to be a list of dicts (tabular data)
                try:
                    df_road_cuts = pd.DataFrame(dam_doc["road_cuts"])
                    st.dataframe(df_road_cuts, use_container_width=True)
                except ValueError:
                    st.caption("Road cuts data not in tabular format. Showing raw JSON:")
                    st.json(dam_doc["road_cuts"]) # Fallback if not standard DataFrame format
            else:
                st.caption("No critical road cuts identified.")
            
            st.caption(f"Generated by: Damage Analysis Agent ({dam_doc.get('analysis_model', 'N/A')})")
            
        elif req_doc:
            st.info("Damage Report pending. Damage Analysis Agent (Phase 1) is running...")
        
        else:
            st.warning("Please initiate a request first.")


    # --- Tab 3: Logistics Plan (Phase 2) ---
    with tab3:
        st.header("Logistics and Resource Allocation Plan")
        if log_doc:
            st.success("✅ Logistics Plan Complete")
            
            st.markdown("#### Logistics Summary Narrative (from LLM):")
            st.markdown(f"> {log_doc.get('summary_narrative', 'N/A')}")
            
            st.markdown("---")
            st.markdown("#### Key Logistics Challenges (from LLM):")
            challenges = log_doc.get('key_logistics_challenges', [])
            if challenges:
                st.markdown(
                    "\n".join([f"- 🚧 {c}" for c in challenges])
                )
            else:
                st.caption("No key challenges explicitly listed.")
            
            st.markdown("#### Priority Relief Zones & Resource Allocation (from LLM):")
            if "priority_relief_zones" in log_doc and log_doc["priority_relief_zones"]:
                # Ensure it's rendered as a DataFrame for structured data
                try:
                    df_relief_zones = pd.DataFrame(log_doc["priority_relief_zones"])
                    st.dataframe(df_relief_zones, use_container_width=True)
                except ValueError:
                    st.caption("Relief zones data not in tabular format. Showing raw JSON:")
                    st.json(log_doc["priority_relief_zones"]) # Fallback if not standard DataFrame format
            
            st.caption(f"Generated by: Logistics Agent ({log_doc.get('logistics_model', 'N/A')})")

        elif dam_doc:
            st.info("Logistics Plan pending. Logistics Agent (Phase 2) is running...")
        
        elif req_doc:
            st.info("Awaiting Damage Analysis to complete Phase 1 before starting Logistics.")
        
        else:
            st.warning("Please initiate a request first.")
            
# --- Conditional Rerun for Polling (Crucial for real-time updates) ---
if st.session_state.workflow_running and log_doc is None:
    # Auto-poll every 2 seconds if the workflow is running AND the final report is not ready
    
    # NOTE: time.sleep is executed on the server, ensuring a 2-second gap 
    # between reruns, preventing excessive Firestore/CPU load.
    time.sleep(2)
    st.rerun() # Triggers a full Streamlit rerun to fetch new data

if log_doc is not None and st.session_state.workflow_running:
    # Workflow completed, stop the polling
    st.session_state.workflow_running = False