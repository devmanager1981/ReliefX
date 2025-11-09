import os
import json
from google.cloud import pubsub_v1
from typing import Dict, Any, Optional

# --- CONFIGURATION ---
# Use environment variables for production, with fallbacks for local dev
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "reliefmesh-hackathon") 

# Topic ID for triggering the Damage Analysis Agent (Phase 1)
TOPIC_ID_DAMAGE_ANALYSIS = os.getenv("TOPIC_ID_DAMAGE", "topic-damage-analysis-trigger")

# Topic ID for triggering the Logistics Agent (Phase 2)
TOPIC_ID_LOGISTICS = os.getenv("TOPIC_ID_LOGISTICS", "topic-logistics-agent-trigger") 

# --- Client Initialization ---
# Initialize Pub/Sub Client in the global scope.
# This is the recommended pattern for Cloud Run to reuse the client.
publisher: Optional[pubsub_v1.PublisherClient] = None
try:
    publisher = pubsub_v1.PublisherClient()
    print("Pub/Sub Publisher Client Initialized successfully.")
except Exception as e:
    print(f"CRITICAL ERROR: Failed to initialize Pub/Sub Publisher Client: {e}")
    publisher = None

# --- Pub/Sub Client Function ---

def publish_message(topic_id: str, message_data: Dict[str, Any]) -> str:
    """
    Publishes a JSON message to a specified Pub/Sub topic.
    
    Args:
        topic_id: The short name of the topic (e.g., "topic-damage-analysis-trigger").
        message_data: A dictionary to be sent as the message payload. 
                      This typically contains the {"request_id": "..."}.
    
    Returns:
        The message ID string from Pub/Sub upon successful publish.
    
    Raises:
        RuntimeError: If the client is not initialized or if publishing fails.
    """
    if not publisher:
        print("Error: Pub/Sub client not initialized. Cannot publish message.")
        raise RuntimeError("Pub/Sub client not initialized.")
        
    try:
        topic_path = publisher.topic_path(PROJECT_ID, topic_id)
        
        # Serialize the message payload to a JSON string and encode as bytes
        data_bytes = json.dumps(message_data).encode("utf-8")
        
        print(f"Publishing message to topic: {topic_id}")
        
        # The publish call is asynchronous
        future = publisher.publish(topic_path, data_bytes)
        
        # Calling .result() blocks until the message is successfully published
        # or raises an exception. This is a good guardrail to ensure
        # the message is sent before the Cloud Run instance terminates.
        message_id = future.result()
        
        print(f"Published message {message_id} to {topic_id}.")
        return message_id
        
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to publish message to {topic_id}: {e}")
        raise RuntimeError(f"Pub/Sub publish failed to {topic_id}") from e