# Kopano Industrial Supply — Frontend

React 19 + TypeScript + Vite frontend for the FastAPI B2B catalogue and quotation backend supplied with this project.

## Requirements
- Node.js 20.19+ or 22.12+
- The Kopano FastAPI backend running on `http://localhost:8000`

## Run locally

1. Start the backend in a separate terminal:

   ```bash
   cd tradeline-project/backend
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

2. Start this frontend in another terminal:

   ```bash
   cd tradeline-project/frontend
   npm install
   npm run dev
   ```

3. Open the Vite URL printed in the terminal (normally `http://localhost:5173`). During local development, Vite proxies `/api` requests to `http://localhost:8000`.

## First administrator

Create the first administrator using the backend's documented command, from the backend directory:

```bash
python -m app.create_admin_user admin@example.com "Administrator Name"
```

Follow the prompt to set the administrator password. The administrator can then sign in through the same frontend login as clients and sales staff. Admins have both the sales workspace and team management access.

## Features
- Public catalogue sourced from the backend inventory CSV; search, category/brand/stock filters, sorting and pagination.
- Quote basket and RFQ submission for signed-in client accounts.
- Client dashboard, request history, received quotes, profile update, and accept/decline actions.
- Sales pipeline, RFQ search/filter, line pricing and discounts, VAT calculation, draft save/send, and sent quote withdrawal for correction.
- Administrator staff management: add sales users, one-time temporary passwords, deactivate/reactivate, and reset passwords.
- Shared authentication flow; role and company permissions are enforced by the backend.
- Mandatory first-login password change for newly provisioned staff accounts.
- Responsive layouts for desktop and mobile.

## API URL

For local development, the Vite proxy handles `/api` automatically. For a deployed frontend, set `VITE_API_URL` to the full backend origin before building. Configure the backend's `ALLOWED_ORIGINS` to include the deployed frontend origin.

## Important notes
- Public catalogue pricing is not displayed because the inventory source contains no prices.
- A quote's prices become visible to the client only after the backend records it as sent.
- The frontend does not process payments or place orders; it handles quotation requests and decisions.
- The contact email shown in the support helper is a placeholder and should be replaced with the business's real support contact before production.


## Frontend structure

The React frontend is split by responsibility rather than keeping all screens in `App.tsx`:

```text
src/
  App.tsx                  # App-level state and screen navigation
  components/ui.tsx        # Shared UI building blocks
  pages/                   # Individual application screens
    CataloguePage.tsx
    BasketPage.tsx
    LoginPage.tsx
    RegisterPage.tsx
    ChangePasswordPage.tsx
    ClientWorkspace.tsx
    SalesWorkspace.tsx
    QuoteWorkspace.tsx
    TeamWorkspace.tsx
    AuthPage.tsx            # Shared authentication layout/form presentation
  services/api.ts          # HTTP/API client and auth token handling
  types/index.ts            # Shared TypeScript data types
  utils/format.ts           # Currency, date and display formatting
  index.css                # Global design system and responsive styles
```

`App.tsx` now focuses on session state and deciding which page to show. Authentication flows have separate page entry points and share the same visual/auth form implementation.
