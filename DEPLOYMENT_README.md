# VoltPilot Render deployment patch

This patch configures the React app to use `VITE_API_BASE_URL` in production while preserving `/api` + the Vite proxy for local development. It lets FastAPI accept comma-separated production origins using `FRONTEND_ORIGINS` while retaining localhost origins. `render.yaml` defines a Render Blueprint with a FastAPI Web Service and React/Vite static site.

## Deploy
1. Extract the patch into the project root (`C:\Users\Nishel\voltpilot`) and allow the three included paths to merge/replace.
2. Review the diff, run local checks, then commit and push to GitHub.
3. In Render, choose New > Blueprint, connect `Nishel-mm/voltpilot-retail-decision-agent`, branch `main`, and let Render read `render.yaml`.
4. If either Render subdomain must use a different name, update both `VITE_API_BASE_URL` on the static site and `FRONTEND_ORIGINS` on the API service to the actual `https://...onrender.com` URLs, then redeploy.
5. Test `https://<API service>.onrender.com/api/health` and the frontend URL.

## Important SQLite limitation
The app currently stores data in SQLite. Render free web services have ephemeral filesystems and may spin down after inactivity; database changes can be lost after spin-down/redeploy/restart. This Blueprint is suitable for a quick judge/demo preview, not durable shared production data. For persistent multi-user data, migrate the data layer to a managed PostgreSQL service or use a paid persistent disk plan before relying on live records. The current app's SQLite DB is initialized/seeded in the backend at startup, so a fresh instance should boot with demo data, but sales entered on a prior ephemeral instance may not survive.
