# ANVAR LUXURY Website

This folder is the Render/GitHub website version of the Android app UI.

## Render setup

1. Upload the contents of this `WEBSITE` folder to GitHub.
2. Create a Render web service.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add these Render environment variables:
   - `TENANT_ID`
   - `CLIENT_ID`
   - `CLIENT_SECRET`

Do not commit real secrets to GitHub. Use Render environment variables.
