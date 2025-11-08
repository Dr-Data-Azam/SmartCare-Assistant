# Go to http://localhost:4000/ to launch a SMART App

import requests
import secrets
import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from urllib.parse import urlencode, urljoin
from dotenv import load_dotenv
from requests.exceptions import RequestException

# --- 1. Configuration & Logging Setup ---
load_dotenv()
app = FastAPI()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Load from .env
# We ONLY load static values. Auth/Token URLs will be discovered.
CLIENT_ID = os.getenv("CLIENT_ID", "my-smart-sandbox-app")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/callback")
FHIR_BASE = os.getenv("FHIR_BASE") # Must be set in .env, e.g., http://localhost:4013/v/r4/sim/YOUR_SIM_ID/fhir

# Global vars to hold discovered URLs
AUTH_URL = None
TOKEN_URL = None

# --- 2. SMART Endpoint Discovery (Runs on Startup) ---

def get_smart_config(fhir_base_url: str) -> dict:
    """
    Fetches the CapabilityStatement (metadata) and extracts SMART OAuth URIs.
    """
    metadata_url = f"{fhir_base_url.rstrip('/')}/metadata"
    log.info(f"Discovering SMART config from: {metadata_url}")
    try:
        resp = requests.get(metadata_url, headers={"Accept": "application/fhir+json"})
        resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        metadata = resp.json()
    except RequestException as e:
        log.error(f"Failed to fetch metadata: {e}")
        return {}
    except requests.exceptions.JSONDecodeError:
        log.error(f"Failed to decode JSON from metadata endpoint. Response: {resp.text[:200]}...")
        return {}

    try:
        # Navigate the CapabilityStatement
        rest_endpoints = metadata.get("rest", [])
        if not rest_endpoints:
            log.error("No 'rest' array found in CapabilityStatement")
            return {}
            
        security = rest_endpoints[0].get("security")
        if not security:
            log.error("No 'security' object found in 'rest' endpoint")
            return {}

        # Find the SMART OAuth extension
        smart_extension = next(
            (ext for ext in security.get("extension", []) if ext.get("url") == "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris"),
            None
        )
        
        if not smart_extension:
            log.error("SMART 'oauth-uris' extension not found in security metadata")
            return {}

        # Extract the authorize and token URLs
        uris = {}
        for ext in smart_extension.get("extension", []):
            if ext.get("url") == "authorize":
                uris["authorize_url"] = ext.get("valueUri")
            elif ext.get("url") == "token":
                uris["token_url"] = ext.get("valueUri")
        
        return uris

    except Exception as e:
        log.error(f"Error parsing CapabilityStatement: {e}")
        return {}

@app.on_event("startup")
def discover_endpoints():
    """
    On app startup, discover and set the global AUTH_URL and TOKEN_URL.
    """
    global AUTH_URL, TOKEN_URL
    
    if not FHIR_BASE:
        log.critical("FHIR_BASE is not set in environment. App cannot start.")
        # In a production app, you might want to raise an exception
        # to prevent the app from starting in a broken state.
        return

    log.info(f"Starting app. Discovering endpoints for FHIR_BASE: {FHIR_BASE}")
    config = get_smart_config(FHIR_BASE)
    
    AUTH_URL = config.get("authorize_url")
    TOKEN_URL = config.get("token_url")

    if not AUTH_URL or not TOKEN_URL:
        log.critical("!!! FAILED to discover AUTH_URL or TOKEN_URL from metadata.")
        log.critical("Ensure FHIR_BASE is correct and the FHIR server is running.")
    else:
        log.info(f"Successfully discovered SMART endpoints:")
        log.info(f"  AUTH_URL: {AUTH_URL}")
        log.info(f"  TOKEN_URL: {TOKEN_URL}")

# --- 3. FastAPI Routes ---

@app.get("/")
def home():
    return {
        "message": "SMART on FHIR Dev Sandbox test app. Go to /login to begin.",
        "config": {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "fhir_base_url": FHIR_BASE,
            "discovered_auth_url": AUTH_URL,
            "discovered_token_url": TOKEN_URL
        }
    }

@app.get("/login")
def login():
    if not AUTH_URL:
        log.error("Login attempt failed: AUTH_URL was not discovered on startup.")
        return JSONResponse(
            {"error": "SMART Endpoint Discovery Failed", 
             "message": "AUTH_URL is not set. Check app logs and FHIR_BASE env var."}, 
            status_code=500
        )

    state = secrets.token_urlsafe(16)
    
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": (
            "launch openid fhirUser offline_access "
            "patient/Patient.read "
            "patient/Observation.read "
            "patient/Condition.read "
            "patient/MedicationRequest.read"
        ),
        "aud": FHIR_BASE,
        "state": state
    }
    
    # --- Robust Logging (as requested) ---
    log.info("--- Initiating /login redirect ---")
    log.info(f"  CLIENT_ID: {CLIENT_ID}")
    log.info(f"  REDIRECT_URI: {REDIRECT_URI}")
    log.info(f"  AUTH_URL: {AUTH_URL}")
    log.info(f"  FHIR_BASE (aud): {FHIR_BASE}")
    # ----------------------------------------

    redirect_url = f"{AUTH_URL}?{urlencode(params)}"
    log.info(f"Redirecting user to: {redirect_url}")
    return RedirectResponse(redirect_url)

@app.get("/callback")
def callback(request: Request):
    
    # --- Robust Error Handling (as requested) ---
    auth_error = request.query_params.get("error")
    error_desc = request.query_params.get("error_description")
    
    if auth_error:
        log.error(f"Error in callback from auth server: {auth_error} - {error_desc}")
        return JSONResponse(
            {"error": auth_error, "error_description": error_desc}, 
            status_code=400
        )

    code = request.query_params.get("code")
    if not code:
        log.error("Callback received without 'code' or 'error' query param.")
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    if not TOKEN_URL:
        log.error("Callback failed: TOKEN_URL was not discovered on startup.")
        return JSONResponse(
            {"error": "SMART Endpoint Discovery Failed", 
             "message": "TOKEN_URL is not set. Check app logs."}, 
            status_code=500
        )

    # --- Token Exchange ---
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID
        # No client_secret for public client
    }
    
    log.info("Exchanging code for token...")
    try:
        token_response = requests.post(TOKEN_URL, data=data)
        token_response.raise_for_status() # Check for HTTP errors
    except RequestException as e:
        log.error(f"Token exchange POST failed: {e}")
        return JSONResponse(
            {"error": "Token exchange request failed", "details": str(e)}, 
            status_code=500
        )

    try:
        token_json = token_response.json()
    except requests.exceptions.JSONDecodeError:
        log.error(f"Failed to decode JSON from token response. Body: {token_response.text}")
        return JSONResponse(
            {"error": "Invalid JSON response from token endpoint"}, 
            status_code=500
        )
    
    if "error" in token_json:
        log.error(f"Token endpoint returned an error: {token_json}")
        return JSONResponse(
            {"error": "Token endpoint returned an error", "details": token_json}, 
            status_code=400
        )

    access_token = token_json.get("access_token")
    patient_id = token_json.get("patient")

    if not access_token:
        log.error(f"Token response did not include 'access_token'. Response: {token_json}")
        return JSONResponse(
            {"error": "Failed to obtain access token", "details": token_json},
            status_code=400
        )
    
    log.info(f"Successfully obtained access token. Patient ID: {patient_id}")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/fhir+json"}

    # --- FHIR Data Fetching ---
    
    def fhir_get(resource: str) -> dict:
        url = f"{FHIR_BASE}/{resource}"
        log.info(f"Fetching FHIR resource: {url}")
        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except RequestException as e:
            log.error(f"FHIR GET request failed for {url}: {e}")
            return {"error": f"{resource} request failed", "status": e.response.status_code if e.response else 'N/A', "body": str(e)}
        except requests.exceptions.JSONDecodeError:
            log.error(f"FHIR response was not valid JSON for {url}. Body: {resp.text[:200]}...")
            return {"error": "Invalid JSON response from FHIR server", "status": resp.status_code, "body": resp.text[:200]}

    if not patient_id:
        log.warning("No Patient ID in token response. Skipping patient-specific queries.")
        return {"access_token_details": token_json, "message": "Launch successful, but no patient ID was returned."}

    patient = fhir_get(f"Patient/{patient_id}")
    conditions = fhir_get(f"Condition?patient={patient_id}")
    observations = fhir_get(f"Observation?patient={patient_id}&category=laboratory")
    medications = fhir_get(f"MedicationRequest?patient={patient_id}")

    log.info("Successfully fetched all FHIR resources.")
    
    return {
        "token_response": token_json,
        "patient": patient,
        "conditions": conditions,
        "observations": observations,
        "medications": medications
    }

# --- 4. Run the App (for local debugging) ---
if __name__ == "__main__":
    import uvicorn
    if not FHIR_BASE:
        print("ERROR: 'FHIR_BASE' environment variable not set.")
        print("Please set it in your .env file or shell.")
        print("Example: FHIR_BASE=http://localhost:4013/v/r4/sim/YOUR_SIM_ID/fhir")
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)