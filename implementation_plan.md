# Implementation Plan: Decoupled React (Next.js) + Django

## Overview

Convert the web app from HTMX/Django templates to a **decoupled architecture** where Next.js is the frontend and Django is a pure REST API. The existing `komunity-landing` repo already has Next.js 15 set up — the dashboard app will live alongside it or extend it.

> [!IMPORTANT]
> The existing `api_v1/` REST API already powers the mobile app and is production-ready. No API redesign is needed — we are purely building a new frontend on top of it.

---

## Current State Summary

| What | Where | Keep? |
|---|---|---|
| REST API | `api_v1/views.py` (75k bytes) | ✅ Fully keep |
| Django Admin | `/admin/` | ✅ Fully keep |
| DRF Token Auth | `settings.py` | ✅ Fully keep |
| CORS headers | Already installed + `CORS_ALLOW_ALL_ORIGINS=True` | ✅ Tighten in prod |
| Next.js landing page | `komunity-landing/` | ✅ Extend this |
| HTMX templates | `templates/` | ❌ Retire gradually |
| allauth/session auth | `accounts/` routes | 🔄 Keep for Admin only |

---

## Architecture After Migration

```
komunity-landing/          ← Next.js 15 app (dashboard + landing)
  app/
    page.tsx               ← Public landing page (already exists)
    (auth)/
      login/page.tsx       ← Login page
      register/page.tsx    ← Register page
    dashboard/
      layout.tsx           ← Auth-protected shell
      page.tsx             ← Home/feed
      wallet/page.tsx
      groups/page.tsx
      profile/page.tsx
      organisations/page.tsx
      fundraisers/page.tsx
  lib/
    api.ts                 ← Axios/fetch client (mirrors mobile app)
    auth.ts                ← Token storage + refresh
  components/
    [existing landing components]
    ui/                    ← Dashboard UI components

komunityWeb/               ← Django: API only
  api_v1/                  ← Unchanged
  admin/                   ← Unchanged
  templates/               ← Can be deleted after migration
  chema/urls.py etc.       ← HTMX routes removed over time
```

---

## Deployment Split

```
app.komunity.co.za    →  Next.js (Vercel / Railway)
api.komunity.co.za    →  Django (Render / Railway) — current host
api.komunity.co.za/admin/  →  Django Admin (unchanged)
```

During local development:
```
localhost:3000   →  Next.js
localhost:8000   →  Django
```

---

## Open Questions

> [!IMPORTANT]
> **Before proceeding, confirm these decisions:**

   <!-- go with option A -->

1. **Where does the dashboard live?** Two options:
   - **A** — Extend `komunity-landing` (single Next.js app: landing + dashboard). Simpler, one deployment.
   - **B** — Create a separate `komunity-web` Next.js repo (landing and dashboard are separate deployments).
   - *Recommendation: Option A — less infrastructure overhead.*


2. **What is the primary domain setup?**
   - `komunity.co.za` → landing/dashboard (Next.js)
   - `api.komunity.co.za` → Django API
   - Yes I want everything on one domain behind a reverse proxy?

3. **Authentication for the web dashboard:**
   - **Token-based** (same as mobile, stored in `localStorage` / `httpOnly cookie`) — simpler, already works
  
    <!-- let get remove the social auth -->
4. **Social login (Google/Facebook)?**
   - Django `allauth` currently handles this. Do you want to keep it for the web dashboard?
   - If yes, we route through Django's existing `/accounts/google/login/` and exchange for a DRF token.

5. **Which features of the HTMX app are in production/actively used** that need to be replicated first?

---

## Proposed Changes

---

### Phase 1 — Django Backend Cleanup & Hardening

#### [MODIFY] [settings.py](file:///c:/Users/tjman/Desktop/Komunity/komunityWeb/core/settings.py)
- Replace `CORS_ALLOW_ALL_ORIGINS = True` with an explicit allowlist:
  ```python
  CORS_ALLOWED_ORIGINS = [
      "http://localhost:3000",
      "https://app.komunity.co.za",
  ]
  CORS_ALLOW_CREDENTIALS = True
  ```
- Add `SESSION_COOKIE_SAMESITE = 'Lax'` and `CSRF_COOKIE_HTTPONLY = False` (needed for Next.js to read CSRF)

#### [MODIFY] [core/urls.py](file:///c:/Users/tjman/Desktop/Komunity/komunityWeb/core/urls.py)
- Keep `admin/` — untouched
- Keep `api/v1/` — untouched
- Remove HTMX app URL includes progressively (`chema.urls`, `user.urls`, `condolence.urls`, `wallet.urls`) as they are replaced

---

### Phase 2 — Next.js Dashboard Setup

#### [MODIFY] [komunity-landing/](file:///c:/Users/tjman/Desktop/Komunity/komunity-landing)
- Update `next.config.ts` — remove `output: 'export'` (static export prevents dynamic routes needed for dashboard). Switch to standard Next.js server mode or keep static export for landing + add a server-side rendered dashboard.

#### [NEW] `komunity-landing/lib/api.ts`
- Shared API client (Axios with base URL + token interceptor)
- Mirrors the `client.ts` pattern from `KomunityMobile`

#### [NEW] `komunity-landing/lib/auth.ts`
- `login(phone, pin)` → calls `/api/v1/auth/verify-pin/`
- `logout()` → clears token
- `getToken()` → reads from cookie or localStorage

#### [NEW] `komunity-landing/app/(auth)/login/page.tsx`
- Phone + PIN login form (same flow as the mobile app's `PhoneAuthScreen`)

#### [NEW] `komunity-landing/app/dashboard/layout.tsx`
- Auth guard: redirect to `/login` if no token
- Sidebar navigation (Groups, Wallet, Organisations, Fundraisers, Profile)

#### [NEW] Dashboard pages (one per feature):
- `dashboard/page.tsx` — Feed / Home
- `dashboard/groups/page.tsx`
- `dashboard/wallet/page.tsx`
- `dashboard/organisations/page.tsx`
- `dashboard/fundraisers/page.tsx`
- `dashboard/profile/page.tsx`

---

### Phase 3 — Django Template Cleanup (Post-Migration)

Once each feature is live in Next.js, the corresponding HTMX view + template can be removed:

#### [DELETE] `templates/chema/`, `templates/condolence/`, `templates/user/`, `templates/wallet/`
#### [MODIFY] `chema/urls.py`, `user/urls.py`, `condolence/urls.py`, `wallet/urls.py`
- Remove HTML view URL patterns

---

## Verification Plan

### During Development
- Run Django on `localhost:8000` and Next.js on `localhost:3000`
- Confirm CORS headers on API responses
- Test token auth flow end-to-end (login → protected route → API call)
- Confirm Django Admin accessible at `localhost:8000/admin/`

### Pre-Production
- Set `CORS_ALLOWED_ORIGINS` to production domains
- Ensure tokens stored in `httpOnly` cookies (not localStorage) in production
- Confirm `/admin/` is behind a reverse proxy with IP restriction if desired

### Manual Verification
- Log in via phone/PIN
- Access wallet, groups, organisations, fundraisers
- Confirm Django Admin is reachable at `api.komunity.co.za/admin/`
