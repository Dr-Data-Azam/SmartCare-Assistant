from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
import requests, secrets
from urllib.parse import urlencode
from dotenv import load_dotenv
import os

load_dotenv()
app = FastAPI()

# Epic Sandbox Credentials
CLIENT_ID = os.getenv("CLIENT_ID")
REDIRECT_URI = os.getenv("REDIRECT_URI")
AUTH_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"
TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
FHIR_BASE = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"


@app.get("/")
def home():
    """Entry point"""
    return {"message": "Welcome to the SMART on FHIR Epic test app. Go to /login to begin."}


@app.get("/login")
def login():
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": (
            "launch offline_access openid fhirUser "
            "patient/Patient.read "
            "patient/Observation.read "
            "patient/Condition.read "
            "patient/MedicationRequest.read"
        ),
        "aud": FHIR_BASE,
        "state": state
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")




@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    # Step 1: Exchange code for access token
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID
    }

    token_response = requests.post(TOKEN_URL, data=data)
    token_json = token_response.json()
    access_token = token_json.get("access_token")
    patient_id = token_json.get("patient")

    if not access_token or not patient_id:
        return JSONResponse(
            {"error": "Missing token or patient ID", "details": token_json},
            status_code=400
        )

    # Step 2: Set headers
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json"
    }

    # Helper to fetch FHIR resources
    def fhir_get(resource: str):
        url = f"{FHIR_BASE}/{resource}"
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            return {
                "error": f"{resource} request failed",
                "status": resp.status_code,
                "body": resp.text[:500]
            }
        return resp.json()

    # Step 3: Fetch full data
    patient = fhir_get(f"Patient/{patient_id}")
    conditions = fhir_get(f"Condition?patient={patient_id}")
    observations = fhir_get(f"Observation?patient={patient_id}&category=laboratory")
    medications = fhir_get(f"MedicationRequest?patient={patient_id}")

    # Step 4: Return everything together
    return {
        "patient": patient,
        "conditions": conditions,
        "observations": observations,
        "medications": medications
    }


