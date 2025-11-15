API folder
==========

This folder contains a minimal Flask API that exposes the Projects collection from your MongoDB Atlas cluster.

Files
- app.py - the Flask application (connects to MongoDB using MONGODB_URI from your .env)
- requirements.txt - Python dependencies

Quick start
1. Ensure your repo root `.env` contains MONGODB_URI (or export it in your shell).
   Use the included `.env.example` as a template and do NOT commit your `.env` file.

   Example `.env` entry:

   MONGODB_URI="mongodb+srv://<db_user>:<db_password>@<cluster>.mongodb.net/?retryWrites=true&w=majority"

2. Recommended (Windows PowerShell) — run the repo-level setup helper from the repo root:

   ```powershell
   .\setup-dev.ps1
   ```

   That script will create `api/.venv` and install Python dependencies and run `npm install` in `frontend`.

3. Alternatively, manual steps (POSIX shell example):

   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python app.py

3. The API will listen on http://127.0.0.1:5000 and the frontend (Vite dev server) is allowed by CORS.

Endpoints
- GET  /api/projects             - list all projects
- GET  /api/projects/<projectId> - get project by ID
- POST /api/projects             - create a project (JSON body: projectId, name, description)

Security note
- Keep your MONGODB_URI secret. Do not commit real credentials into git.
