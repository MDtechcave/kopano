# Kopano Industrial Supply — Full Project

This bundle contains the FastAPI backend and the React frontend.

## 1. Start the backend

Open a terminal in the `backend` folder:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# Windows Git Bash:
source .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`; interactive API docs are at `http://localhost:8000/docs`.

## 2. Create the first administrator

Open a second terminal in `backend` and activate the same virtual environment, then run:

```bash
python -m app.create_admin_user admin@example.com "Administrator Name"
```

Follow the prompt to set the administrator password. Use the actual admin email you want. Admins can work in the sales workspace and manage the team. Staff users are created by an admin and receive a one-time temporary password.

## 3. Start the frontend

Open a third terminal in the `frontend` folder:

```bash
npm install
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). Vite forwards `/api` calls to the backend at `http://localhost:8000`.

## 4. Test the workflow

- Register a client account through the website.
- Submit an RFQ from the catalogue basket.
- Sign in as the administrator, open the sales workspace, price the request, save a draft, and send the quote.
- Sign back in as the client to review and accept or decline the quotation.
- Use Team management to add staff accounts and reset or deactivate them.

## Notes

- The backend test suite contains 62 tests; all 62 passed during preparation of this bundle.
- The frontend is React 19, TypeScript, Vite 8 and Tailwind CSS 4.
- A full frontend production build could not be run in this environment because dependency installation timed out. The TSX source passed TypeScript syntax transpilation; run `npm install` then `npm run build` locally and report any build output so remaining environment-specific issues can be fixed.
- The support email shown in the UI (`info@example.com`) is a placeholder. Replace it with the business's real support contact before production.
- This is a quotation workflow only; it does not process payments or place orders.
