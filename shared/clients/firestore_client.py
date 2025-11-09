from google.cloud import firestore
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# --- Client Initialization ---
# Initialize Firestore Client in the global scope.
# This is the recommended pattern for Cloud Run, as the client object
# can be reused across function invocations, avoiding cold starts.
try:
    db = firestore.Client()
    print("Firestore Client Initialized successfully.")
except Exception as e:
    print(f"CRITICAL ERROR: Failed to initialize Firestore Client: {e}")
    db = None # Set to None to prevent application from running

# --- Firestore Client Functions ---

def get_document(collection_name: str, document_id: str) -> Optional[Dict[str, Any]]:
    """
    Securely retrieves a single document by its unique ID from a collection.
    
    Security: This function is not vulnerable to NoSQL injection as it uses
    the document ID (key) for lookup, not a user-supplied query filter.
    """
    if not db:
        print("Error: Firestore not initialized. Cannot get document.")
        return None
    try:
        doc_ref = db.collection(collection_name).document(document_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        else:
            print(f"Warning: Document not found: {collection_name}/{document_id}")
            return None
    except Exception as e:
        print(f"Error reading document {collection_name}/{document_id}: {e}")
        return None

def write_document(collection_name: str, document_id: str, data: dict or BaseModel) -> bool:
    """
    Writes or overwrites a document in a collection with the given data.
    This function handles both Pydantic models and standard dictionaries.
    """
    if not db:
        print("Error: Firestore not initialized. Cannot write document.")
        return False
    try:
        doc_ref = db.collection(collection_name).document(document_id)
        
        # Ensure data is a dictionary before writing
        if isinstance(data, BaseModel):
            # If a Pydantic model is passed, convert it to a serializable dictionary
            write_data = data.model_dump()
        elif isinstance(data, dict):
            write_data = data
        else:
            raise TypeError("Data to write must be a dict or Pydantic BaseModel.")

        doc_ref.set(write_data)
        return True
    except Exception as e:
        print(f"Error writing document {collection_name}/{document_id}: {e}")
        return False

def query_collection(collection_name: str) -> List[Dict[str, Any]]:
    """
    Queries an entire collection and returns a list of all documents.
    
    This is suitable for small, known collections, such as fetching all
    agent workflow statuses for display in the Streamlit UI.
    """
    if not db:
        print("Error: Firestore not initialized. Cannot query collection.")
        return []
    
    try:
        docs_stream = db.collection(collection_name).stream()
        results = []
        for doc in docs_stream:
            doc_data = doc.to_dict()
            doc_data['id'] = doc.id # Include the document ID for reference
            results.append(doc_data)
        return results
    except Exception as e:
        print(f"Error querying collection {collection_name}: {e}")
        return []