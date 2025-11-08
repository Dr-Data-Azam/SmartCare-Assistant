from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
import os, requests, secrets
from urllib.parse import urlencode

app = FastAPI()

# Hardcode or .env
CLIENT_ID = "my-smart-sandbox-app"
REDIRECT_URI = "http://localhost:8000/callback"
FHIR_BASE = "http://localhost:4013/v/r4/sim/eyJrIjoiMSIsImoiOiIxIiwiYiI6IjUyNSJ9/fhir"

# You’d normally fetch these from metadata
AUTH_URL = FHIR_BASE.replace("/fhir", "/auth/authorize")
TOKEN_URL = FHIR_BASE.replace("/fhir", "/auth/token")

@app.get("/")
def home():
    return {"message": "Go to /login"}

@app.get("/login")
def login():
    state = secrets.token_urlsafe(8)
    params = dict(
        client_id=CLIENT_ID,
        response_type="code",
        redirect_uri=REDIRECT_URI,
        scope="launch patient/*.read openid fhirUser",
        aud=FHIR_BASE,
        state=state
    )
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")

@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return {"error": "Missing authorization code"}

    # Exchange code for token
    data = dict(
        grant_type="authorization_code",
        code=code,
        redirect_uri=REDIRECT_URI,
        client_id=CLIENT_ID
    )
    token = requests.post(TOKEN_URL, data=data).json()
    if "error" in token:
        return {"error": "Token exchange failed", "details": token}

    access_token = token.get("access_token")
    patient_id = token.get("patient")
    if not access_token or not patient_id:
        return {"error": "Missing access_token or patient ID", "details": token}

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/fhir+json"}

    def get_resource(path: str):
        """Helper to GET any FHIR resource."""
        r = requests.get(f"{FHIR_BASE}/{path}", headers=headers)
        return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}

    # --- Fetch multiple FHIR resources ---
    patient = get_resource(f"Patient/{patient_id}")
    conditions = get_resource(f"Condition?patient={patient_id}")
    observations = get_resource(f"Observation?patient={patient_id}&category=laboratory")
    medications = get_resource(f"MedicationRequest?patient={patient_id}")

    return {
        "patient": patient,
        "conditions": conditions,
        "observations": observations,
        "medications": medications
    }