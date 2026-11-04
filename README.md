# Vocalis

Vocalis is a responsive voice-design studio built with FastAPI, Jinja templates, plain CSS and JavaScript. The monolith serves the site and API from one origin.

## Run locally

Python 3.12 is recommended. From PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

By default the application uses local SQLite so the site can start without a database service. Set `DATABASE_URL` in `.env` to use PostgreSQL. Tables are created at startup. The site is at `http://localhost:8000`; interactive API documentation is at `/docs`.

Set a unique `JWT_SECRET_KEY` before deployment. `APP_ENV=production` enforces a non-default secret of at least 32 characters. Set `CORS_ORIGINS` to the intended site origins.

## Site pages

- `/` — product landing page and how it works
- `/studio` — guest-capable, multi-step voice creation
- `/voices` — voice library and albums
- `/playground` — speech synthesis and voice settings
- `/dashboard` — credits, voice counts and recent activity
- `/billing` and `/pricing` — credit packs, M-Pesa and card checkout
- `/login` and `/register` — password and Google sign-in
- `/faq` — product help

The site uses the existing `/api/v1` endpoints. Authentication tokens and the guest generation ID are stored in browser local storage. A guest can generate once; registering with the same browser session claims the guest voice.

## Integrations

External providers require credentials; an unconfigured service responds with an error instead of simulating success.

- **Voice provider:** Set `VOICE_PROVIDER_BASE_URL` and `VOICE_PROVIDER_API_KEY`. The adapter calls `POST /voices` with voice specifications and expects `{ "id": "...", "preview_url": "https://..." }`. Speech calls `POST /voices/{id}/speech` and expects audio bytes.
- **Google sign-in:** Set `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, and `FIREBASE_APP_ID` for the browser SDK. Configure server-side Firebase credentials using Application Default Credentials or `FIREBASE_SERVICE_ACCOUNT_FILE`. The server verifies ID tokens before issuing a Vocalis token.
- **M-Pesa:** Configure the Daraja consumer key/secret, shortcode, passkey, callback URLs, and `MPESA_CALLBACK_SECRET`. Expose the callback URLs publicly and register the STK and C2B confirmation URLs with Safaricom. Manual Paybill/Till and QR payments are credited only after a matching C2B confirmation.
- **Cards:** Configure `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`; point Stripe's webhook at `/api/v1/webhooks/stripe`. Credits are awarded on verified payment events.

Credit pack definitions are in `app/domain.py`; generation and synthesis rates are set in `.env`. The frontend Google sign-in flow loads Firebase's browser SDK from Google's CDN only when the Firebase web configuration is present.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
