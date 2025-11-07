from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
import requests, secrets
from urllib.parse import urlencode

app = FastAPI()

CLIENT_ID = "ac189f0d-639c-4e3e-b7c0-e881e74bb53f"
REDIRECT_URI = "http://localhost:8000/callback"
AUTH_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"
TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
FHIR_BASE = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"

@app.get("/")
def home():
    return {"message": "Welcome to the SMART on FHIR Epic test app."}

@app.get("/login")
def login():
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "launch openid fhirUser patient/*.read",
        "aud": FHIR_BASE,
        "state": state
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")

@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID
    }

    token_response = requests.post(TOKEN_URL, data=data)
    if token_response.status_code != 200:
        return JSONResponse({"error": "Token exchange failed", "details": token_response.text}, status_code=400)

    token_json = token_response.json()
    access_token = token_json.get("access_token")
    patient_id = token_json.get("patient")

    if not access_token:
        return JSONResponse({"error": "No access token in response", "details": token_json}, status_code=400)

    headers = {"Authorization": f"Bearer {access_token}"}
    fhir_url = f"{FHIR_BASE}/Patient/{patient_id}" if patient_id else f"{FHIR_BASE}/Patient"
    patient_response = requests.get(fhir_url, headers=headers)

    if patient_response.status_code != 200:
        return JSONResponse({"error": "Failed to fetch patient data", "details": patient_response.text}, status_code=400)

    return patient_response.json()
