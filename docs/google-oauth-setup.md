# Google sign-in setup (Google Cloud Console)

TaskFlex uses **Google Identity Services (GIS)**: the browser gets a Google
`id_token` from the official "Sign in with Google" button, and the backend
verifies its signature against Google's public keys before creating or
signing into the account. No client secret and no redirect URIs are needed —
only the Client ID.

When `GOOGLE_CLIENT_ID` is empty the Google buttons are hidden automatically
and everything else works exactly as before, so this step is optional.

## 1. Create the OAuth Client ID

1. Open <https://console.cloud.google.com/> and sign in with any Google account.
2. At the top, click the project picker → **New project** → name it (e.g. `taskflex`) → **Create**.
3. Open the menu → **APIs & Services → OAuth consent screen**.
   - Choose **External** → **Create**.
   - Fill in **App name** (`TaskFlex`), **User support email**, and **Developer contact email**. Everything else can stay default.
   - Click **Save and continue** through Scopes and Test users (no changes needed).
   - While the app is in **Testing** mode, any Google account can still sign in — you can publish it later under **Audience → Publish app**.
4. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   - **Application type:** Web application
   - **Name:** TaskFlex web
   - **Authorized JavaScript origins** — add every address users visit your site from:
     - `http://localhost:5173` (Vite dev server)
     - `http://localhost:4173` (if you preview the production build locally)
     - `https://yourdomain.com` (your production domain, once live)
   - **Authorized redirect URIs** — leave empty. The GIS button flow does not redirect.
5. Click **Create** and copy the **Client ID** (it ends in `.apps.googleusercontent.com`).

## 2. Give the Client ID to the backend

The frontend reads the Client ID at runtime from `GET /api/v1/auth/google/config`,
so you never rebuild the frontend to change it.

- **Local development:** set it in `backend/.env`, then restart the backend:

  ```
  GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
  ```

- **Production:** set it in the `.env` next to `docker-compose.prod.yml`
  (see `.env.prod.example`), then `docker compose -f docker-compose.prod.yml up -d backend`.

## 3. How it behaves

| Situation | What happens |
| --- | --- |
| First-time Google login | Account auto-created (email pre-verified, profile + wallet created, no password, no phone yet). The role picked on the sign-up page is used. |
| Google login with an existing email | Signs into that account; if it wasn't email-verified yet, it is marked verified (Google proved the address). |
| Existing password account | Keeps working. Password login and Google sign-in both reach the same account. |
| Google-created account + password login | Rejected with "This account uses Google sign-in" — there is no password set. Use Google, or reset a password via "Forgot password?". |
| Suspended account | Google sign-in is refused with ACCOUNT_DISABLED, same as password login. |

Every token is verified server-side (signature, audience, issuer, expiry,
`email_verified`), so a stolen or forged credential cannot create sessions.
Never put the Client ID in a place that requires secrecy — a GIS Client ID is
public by design; security comes from the backend verification.

## 4. Testing it

1. Start the stack (`backend` on :8000, `npm run dev` in `frontend/`).
2. Open <http://localhost:5173/login> — the "Sign in with Google" button should appear below the form.
3. Click it and choose a Google account. You should land in the app, signed in.
4. Check the database: the new user has `password_hash IS NULL` and `is_email_verified = true`.

If the button shows but errors after clicking, the usual cause is a missing
**Authorized JavaScript origin** — the origin shown in your browser's address
bar must be listed exactly (scheme + host + port, no trailing slash).
