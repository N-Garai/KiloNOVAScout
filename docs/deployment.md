# KilonovaScout Deployment Guide for Render

This document outlines the steps and environment variables required to deploy KilonovaScout to Render.

## 1. Project Structure

```
KiloNOVAScout/
├── .gitignore
├── Dockerfile
├── README.md
├── docs/
│   ├── architecture.md
│   └── deployment.md
├── src/
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── simulator.py
│   │   ├── tools.py
│   │   └── requirements.txt
│   └── frontend/
│       ├── index.html
│       ├── package.json
│       ├── postcss.config.js
│       ├── public/
│       │   └── favicon.svg
│       ├── src/
│       │   ├── App.jsx
│       │   ├── components/
│       │   │   ├── ArchitectureSection.jsx
│       │   │   ├── DashboardSection.jsx
│       │   │   ├── Footer.jsx
│       │   │   ├── HeroSection.jsx
│       │   │   ├── MissionSection.jsx
│       │   │   └── StarfieldBackground.jsx
│       │   ├── index.css
│       │   └── main.jsx
│       ├── tailwind.config.js
│       └── vite.config.js
└── version-docs/
    ├── guide.md
    ├── KiloNOVAScout.md
    └── QnA.md
```

## 2. Backend Setup (FastAPI)

- **Requirements:** `requirements.txt` lists all necessary Python packages.
- **Web Server:** The application uses Uvicorn, launched via `main.py`.

## 3. Frontend Setup (React/Vite)

- **Build Tool:** Vite is used for efficient development and building.
- **Dependencies:** `package.json` lists frontend dependencies.
- **Styling:** Tailwind CSS and Framer Motion are used for styling and animations.

## 4. Dockerfile

- The `Dockerfile` is configured to build and run the Python backend.
- It installs dependencies and exposes port 8000 for the FastAPI application.

## 5. Environment Variables for Render

Render requires certain environment variables to be set for your application to run correctly. These can be configured in your Render service settings under "Environment Variables".

### Required Environment Variables:

- **`LLM_MODEL`**: Specifies the language model to use. For free tier, use one of the following:
  - `google/gemini-1.5-flash` (Recommended for free tier)
  - `groq/llama3-8b-8192` (Requires Groq API key, check free tier limits)
  - `ollama/llama3` (If running Ollama locally, not applicable for Render deployment unless Ollama is hosted separately).
  *Default if not set:* `google/gemini-1.5-flash`

- **`OBSERVATORY_NAME`**: The name of the observatory to use for weather checks.
  *Default if not set:* `Palomar`

- **`OBSERVATORY_LAT`**: The latitude of the observatory in decimal degrees.
  *Default if not set:* `33.356` (for Palomar Observatory)

- **`OBSERVATORY_LON`**: The longitude of the observatory in decimal degrees.
  *Default if not set:* `-116.865` (for Palomar Observatory)

### Optional Environment Variables:

- **`LITELLM_API_KEY`**: If you are using a provider that requires an API key (e.g., Groq, OpenAI), you should set this. For Google AI Studio, no API key is typically needed if running through their hosted service or if LiteLLM handles authentication.

### Example Render Configuration:

| Variable Name       | Value                                        |
| :------------------ | :------------------------------------------- |
| `LLM_MODEL`         | `google/gemini-1.5-flash`                    |
| `OBSERVATORY_NAME`  | `Palomar`                                    |
| `OBSERVATORY_LAT`   | `33.356`                                     |
| `OBSERVATORY_LON`   | `-116.865`                                   |
| `LITELLM_API_KEY`   | `YOUR_API_KEY_HERE` (if applicable)          |


## 6. Hosting on Render

1.  **Create a new Web Service** on Render.
2.  **Connect your GitHub repository** (after pushing the code).
3.  **Configure Build Settings:**
    *   Build Command: `pip install -r src/backend/requirements.txt && npm install --prefix src/frontend && npm run build --prefix src/frontend`
4.  **Configure Start Command:** `python src/backend/main.py`
5.  **Set Environment Variables:** Enter the variables listed in Section 5.
6.  **Deploy.**

## 7. Database Considerations

For this hackathon submission, **no database is required**. The agent's state is managed in memory. For a production system requiring state persistence across restarts or distributed operation, consider adding a simple key-value store or a database.

## 8. Final Checks

- Ensure all Python syntax errors are resolved (especially f-strings).
- Verify `package.json` syntax and dependencies.
- Test the `/simulate-gcn-alert` endpoint locally to confirm the agent flow.
