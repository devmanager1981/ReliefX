import streamlit as st
import os
import json
import requests
import pandas as pd
from typing import Dict, Any, Optional, Tuple

# --- Import Shared Modules ---
# These imports assume the 'shared' module is installed as a package
# or available in the container's PYTHONPATH.
from shared.clients.firestore_client import get_document
from shared.models import RescueRequest, DamageReport, LogisticsPlan

# --- PRODUCTION CONFIGURATION ---
# Load configuration from environment variables set in Cloud Run
COMM_ROUTER_URL = os.getenv("COMM_ROUTER_URL")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reliefmesh-hackathon")

# Define the approved regions for analysis (Security Guardrail)
APPROVED_REGIONS = [
    "Cebu Province, Philippines",
    "Gia Lai Province, Vietnam",
    "Northern Mindanao, Philippines"
]

# --- SESSION STATE INITIALIZATION ---
if 'current_request_id' not in st.session_state:
    st.session_state.current_request_id = None
if 'workflow_running' not in st.session_state:
    st.session_state.workflow_running = False

# --- DATA FETCHING (CACHED) ---

@st.cache_data(ttl=5) # Cache data for 5 seconds to poll Firestore
def fetch_workflow_status(request_id: str) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict]]:
    """
    Fetches the status of all three documents from Firestore.
    This function is cached to provide efficient 5-second polling.
    """
    if not request_id:
        return None, None, None
        
    print(f"Polling Firestore for {request_id}...")
    req_doc = get_document("RescueRequests", request_id)
    dam_doc = get_document("DamageReports", request_id)
    log_doc = get_document("LogisticsPlans", request_id)
    
    # Check if the full workflow has completed
    if req_doc and dam_doc and log_doc and st.session_state.workflow_running:
        st.session_state.workflow_running = False
        st.toast("✅ Workflow Complete!", icon="🎉")
        
    return req_doc, dam_doc, log_doc

# --- UI WORKFLOW FUNCTIONS ---

def run_analysis(region: str, event: str):
    """
    Triggers the Communication Router (Phase 0) via an HTTP POST request.
    This is the main entry point for the agent workflow.
    """
    
    # --- Client-Side Guardrails ---
    if not COMM_ROUTER_URL:
        st.error("FATAL: `COMM_ROUTER_URL` is not set in the environment. Cannot start workflow.")
        return
        
    if not region or region not in APPROVED_REGIONS:
        st.error(f"Invalid region selected. Please choose from the approved list.")
        return

    if not event or len(event) > 100:
        st.error("Invalid event name. Must be between 1 and 100 characters.")
        return
    # --- End Guardrails ---

    st.session_state.workflow_running = True
    st.session_state.current_request_id = None # Clear previous ID

    payload = {
        "region_name": region,
        "event_name": event
    }
    
    try:
        with st.spinner("Calling Communication Router..."):
            response = requests.post(COMM_ROUTER_URL, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            new_id = result.get('request_id')
            st.session_state.current_request_id = new_id
            st.toast(f"✅ Workflow initiated! Request ID: {new_id}")
        else:
            st.error(f"❌ API Error ({response.status_code}): {response.text}")
            st.session_state.workflow_running = False

    except requests.exceptions.RequestException as e:
        st.error(f"❌ Connection Error: Could not reach Comm Router at {COMM_ROUTER_URL}.")
        st.session_state.workflow_running = False


# --- STREAMLIT UI LAYOUT ---

st.set_page_config(layout="wide", page_title="ReliefX Dashboard")

# --- 1. Header ---
st.title("🛰️ ReliefX Multi-Agent Response Dashboard")
st.markdown("Automated geospatial analysis and logistics planning for disaster response.")

# --- 2. Initiation Section ---
st.subheader("1. Initiate New Analysis")

with st.form("initiate_form"):
    col1, col2 = st.columns(2)
    with col1:
        # Guardrail: Use selectbox to restrict input to approved regions
        region_input = st.selectbox(
            "Select Region of Interest (AOI)",
            options=APPROVED_REGIONS,
            index=0,
            help="Select the pre-approved administrative region for analysis."
        )
    with col2:
        event_input = st.text_input(
            "Disaster Event Name", 
            "Typhoon Kalmaegi", 
            max_chars=100,
            help="Provide a name for this disaster event."
        )
    
    submit_button = st.form_submit_button(
        "▶️ Run Full Agent Workflow", 
        type="primary", 
        disabled=st.session_state.workflow_running
    )
    if submit_button:
        run_analysis(region_input, event_input)

# --- 3. Status and Data Display ---
st.markdown("---")
request_id = st.session_state.current_request_id

if not request_id:
    st.info("Workflow status will appear here once an analysis is initiated.")
    st.stop()

# --- Polling and Status Display ---
st.subheader(f"2. Workflow Status for ID: `{request_id}`")

# Fetch data using the cached function (provides 5-second poll)
req_doc, dam_doc, log_doc = fetch_workflow_status(request_id)

col1, col2, col3 = st.columns(3)
col1.metric("Rescue Request (Phase 0)", "✅ Found" if req_doc else "...Pending")
col2.metric("Damage Report (Phase 1)", "✅ Found" if dam_doc else "...Pending")
col3.metric("Logistics Plan (Phase 2)", "✅ Found" if log_doc else "...Pending")

if st.session_state.workflow_running:
    st.info("Polling for agent results every 5 seconds... (UI will update automatically)")

# --- 4. Geospatial Map Visualization ---
st.subheader("3. Geospatial Intelligence Map")

map_locations = []

# Add Road Cuts from Damage Report
if dam_doc and "road_cuts" in dam_doc:
    for rc in dam_doc["road_cuts"]:
        map_locations.append({
            'lat': rc.get('latitude'), 
            'lon': rc.get('longitude'), 
            'type': f"Road Cut (Severity: {rc.get('severity_score', 'N/A')})",
            'size': 100,
            'color': [255, 0, 0, 160] # Red
        })
        
# Add Priority Zones from Logistics Plan
if log_doc and "priority_zones" in log_doc:
    for pz in log_doc["priority_zones"]:
        map_locations.append({
            'lat': pz.get('latitude'), 
            'lon': pz.get('longitude'), 
            'type': f"Relief Zone (Pop: {pz.get('estimated_affected_population', 0):,})",
            'size': 200,
            'color': [0, 255, 0, 160] # Green
        })

if map_locations:
    df_locations = pd.DataFrame(map_locations).dropna(subset=['lat', 'lon'])
    if not df_locations.empty:
        st.map(df_locations, latitude='lat', longitude='lon', size='size', color='color', zoom=9)
    else:
        st.info("Geospatial data is still processing or contains no valid coordinates.")
else:
    st.info("Geospatial data points (Road Cuts, Relief Zones) will appear here as agents complete their work.")

# --- 5. Detailed Report Tabs ---
st.markdown("---")
st.subheader("4. Detailed Reports")

tab1, tab2, tab3 = st.tabs(["Rescue Request (Input)", "Damage Report (Agent 1)", "Logistics Plan (Agent 2)"])

with tab1:
    if req_doc:
        st.json(req_doc)
    else:
        st.warning("Rescue Request document pending or not found.")

with tab2:
    if dam_doc:
        st.metric("Total Damaged Buildings", f"{dam_doc.get('damaged_buildings_count', 0):,}")
        st.metric("Estimated Affected Population", f"{dam_doc.get('affected_population_estimate', 0):,}")
        st.metric("Flood Extent", f"{dam_doc.get('flood_extent_km2', 0):.2f} km²")
        
        st.markdown("**Infrastructure Damage Summary (from LLM):**")
        st.markdown(f"> {dam_doc.get('infrastructure_damage_summary', 'N/A')}")

        st.markdown("**Critical Road Cuts (from LLM):**")
        if "road_cuts" in dam_doc and dam_doc["road_cuts"]:
            st.dataframe(dam_doc["road_cuts"], use_container_width=True)
        
        st.caption(f"Generated by: {dam_doc.get('analysis_model', 'N/A')}")
    else:
        st.warning("Damage Report pending. This will appear after Phase 1 is complete.")

with tab3:
    if log_doc:
        st.markdown("**Logistics Summary Narrative (from LLM):**")
        st.markdown(f"> {log_doc.get('summary_narrative', 'N/A')}")
        
        st.markdown("**Key Logistics Challenges (from LLM):**")
        st.markdown(
            "\n".join([f"- 🚧 {c}" for c in log_doc.get('key_logistics_challenges', ['N/A'])])
        )
        
        st.markdown("**Priority Relief Zones & Resource Allocation (from LLM):**")
        if "priority_zones" in log_doc and log_doc["priority_zones"]:
            st.dataframe(log_doc["priority_zones"], use_container_width=True)
            
        st.caption(f"Generated by: {log_doc.get('analysis_model', 'N/A')}")
    else:
        st.warning("Logistics Plan pending. This will appear after Phase 2 is complete.")