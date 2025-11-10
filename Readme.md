ReliefX: AI-Driven Disaster Response Planning

ReliefX is a multi-agent system designed to accelerate disaster relief logistics by integrating geospatial data analysis with generative AI reasoning. The system automatically processes pre- and post-event satellite imagery to identify damage and then generates an optimal resource deployment plan based on those findings.

This has been developed to showcase  the capabilities of Google cloud run as part of #cloudrunhackathon 

1. Architecture and Workflow

The ReliefX system operates as an asynchronous pipeline orchestrated by Google Cloud services.

Core Components

Component

Technology

Role

Frontend

Streamlit

Provides the human interface to initiate a new request and view real-time status and reports (Damage and Logistics).

Communication Router

Cloud Run (Python/Flask)

Receives initial requests, persists the RescueRequest to Firestore, and triggers the first agent via Pub/Sub.

Damage Analysis Agent

Cloud Run (Python, GEE, Gemini/Gemma)

Fetches pre/post-event satellite imagery via Google Earth Engine (GEE), analyzes the images using a multimodal model (e.g., Gemma on GPU or Gemini 2.5 Flash) to identify damaged infrastructure (e.g., road cuts), and saves a DamageReport to Firestore.

Logistics Agent

Cloud Run (Python, Gemini 2.5 Flash)

Triggered by the Damage Report completion. It consumes the DamageReport and an inventory mock, then uses Gemini 2.5 Flash with structured output to generate a tactical LogisticsPlan, saving the final plan to Firestore.

Data Backbone

Firestore & Pub/Sub

Firestore acts as the centralized state manager for all reports and requests. Pub/Sub provides asynchronous, decoupled communication between the agents.

Data Flow Diagram

Request Initiation: User clicks "Run Analysis" in Streamlit.

Router: Streamlit calls the Communication Router Cloud Run service.

Damage Trigger: The Router saves the RescueRequest to Firestore and publishes a message to damage-analysis-trigger Pub/Sub topic.

Analysis: The Damage Analysis Agent is triggered, runs GEE/AI analysis, and writes DamageReport to Firestore.

Logistics Trigger: The Damage Agent publishes a message to the logistics-trigger Pub/Sub topic.

Planning: The Logistics Agent is triggered, reads the DamageReport, uses Gemini to generate the LogisticsPlan, and writes the final plan to Firestore.

Dashboard Update: The Streamlit frontend listens to Firestore, updating the dashboard and map in real-time as reports are generated.

2. Prerequisites

To run and deploy this system, you will need:

GCP Project: A valid Google Cloud Project with Billing enabled.

Google Cloud SDK: Authenticated and configured (gcloud auth login, gcloud config set project [PROJECT_ID]).

Python: Python 3.9+ and pip.

Google Earth Engine (GEE): The GCP project must be linked to a GEE account (requires manual setup outside of this repository).

Service Accounts: Cloud Run services require appropriate service accounts with permissions for Firestore, Pub/Sub, GCS, and the Vertex AI/GenAI API.

3. Local Setup and Testing

This project uses a monorepo structure. Ensure you run commands from the root directory.

3.1. Install Dependencies

Install the required Python packages for all agents and the Streamlit UI:

pip install -r requirements.txt


3.2. Initialize Local Environment

Before running the agents, you must initialize GEE (if running the real Damage Agent) and ensure your local environment can access Firestore.

GEE Authentication (Required for gee_utils.py):

earthengine authenticate


Local Application Default Credentials (for Firestore/Pub/Sub access):

gcloud auth application-default login


3.3. Run Agents Locally

Since Cloud Run services are simple Flask apps, they can be run locally for integration testing.

Start the Communication Router (Port 8080):

python comm_router/main_handler.py


Start the Logistics Agent (Port 8081 - Pub/Sub simulated):

python logistics_agent/main_handler.py
# Note: This agent expects a POST request containing a {'request_id': '...'} payload.


Run the Streamlit UI:

# Run from the root of the project to ensure monorepo imports work
PYTHONPATH=. streamlit run ui/streamlit_app.py


4. Deployment to Google Cloud

Each agent is deployed as a separate Cloud Run service triggered either by Pub/Sub or by a direct HTTP call (for the Communication Router).

4.1. Create Pub/Sub Topics

Create the topics that will serve as triggers for the agents:

gcloud pubsub topics create damage-analysis-trigger
gcloud pubsub topics create logistics-trigger


4.2. Deploy the Agents

Create a Dockerfile for each agent directory (comm_router/, damage_analysis_agent/, logistics_agent/) and deploy using the following pattern.

Deploy Communication Router (HTTP Trigger):

gcloud run deploy comm-router \
  --source comm_router \
  --region=us-central1 \
  --allow-unauthenticated \
  # Ensure the service account has Firestore Write and Pub/Sub Publish permissions.


Deploy Damage Analysis Agent (Pub/Sub Trigger):

gcloud run deploy damage-analysis-agent \
  --source damage_analysis_agent \
  --region=europe-west1 \
  --cpu=8 --memory=32Gi \
  --add-cloud-sql-instance=[OPTIONAL_SQL_INSTANCE] \
  --execution-environment=gen2 \
  --set-env-vars=GCS_BUCKET_NAME="[YOUR-PROJECT-ID]-sat-exports" \
  --no-allow-unauthenticated \
  --service-account=[GEMMA-SERVICE-ACCOUNT] \
  --trigger-topic=damage-analysis-trigger


Deploy Logistics Agent (Pub/Sub Trigger):

gcloud run deploy logistics-agent \
  --source logistics_agent \
  --region=us-central1 \
  --no-allow-unauthenticated \
  --trigger-topic=logistics-trigger


Once deployed, update the COMM_ROUTER_URL variable in your Streamlit application (ui/streamlit_app.py) to point to the live URL of the deployed comm-router service.
