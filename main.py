from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
import requests
from urllib.parse import urlencode

app = FastAPI()

# Replace this with your actual Client ID from Epic
CLIENT_ID = "YOUR_CLIENT_ID"
REDIRECT_URI = "http://localhost:8000/callback"
AUTH_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"
TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
FHIR_BASE = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"

@app.get("/")
def root():
    return {"message": "Epic SMART on FHIR Test — Go to /login to start."}

@app.get("/login")
def login():
    # SMART requires 'aud' (audience = FHIR base URL)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "launch openid fhirUser patient/*.read",
        "aud": FHIR_BASE,
        "state": "xyz"
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
        "client_id": CLIENT_ID,
    }

    token_response = requests.post(TOKEN_URL, data=data)
    token_json = token_response.json()

    if "access_token" not in token_json:
        return JSONResponse({"error": "Token exchange failed", "details": token_json}, status_code=400)

    access_token = token_json["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # Try fetching one patient (you could also use token_json["patient"] if available)
    patient_response = requests.get(f"{FHIR_BASE}/Patient", headers=headers)
    if patient_response.status_code != 200:
        return JSONResponse({"error": "Failed to fetch patient data", "details": patient_response.text}, status_code=400)

    return patient_response.json()
