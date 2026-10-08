# Deploying (pilot, Coolify)

The pilot runs the production compose file, `docker-compose.yml`, on a Coolify
server. Nothing in it is Coolify-specific: any host that runs Docker Compose
behind a reverse proxy works the same way.

```text
https://zug.example.com      ──► web  :3000   (Next.js standalone)
https://api.zug.example.com  ──► api  :8000   (FastAPI)
                                 worker, postgres, redis, migrate: internal only
```

The browser calls the API directly, on its own domain, so the site needs two
domains. The API URL is compiled into the browser bundle when `web` is built.

## What happens on every deploy

1. postgres starts. Its data lives in the `postgres-data` volume, which must
   persist across deploys. Redis keeps nothing worth persisting.
2. **migrate** runs `alembic upgrade head` and exits. It also creates the
   PostGIS extension if missing. Coolify shows it as *exited*, which is
   expected.
3. api and worker start once migrate has succeeded.
4. On its first start the worker downloads and imports the timetable (about
   10 s), then re-checks it daily. Until that first import the map is empty
   and `/api/v1/health` reports `"dataset": null`.
5. web starts. Its healthcheck fetches `/`.

## First-time setup in Coolify

1. **New resource** → *Docker Compose* from the GitHub repository, branch
   `main`, compose file `/docker-compose.yml`. Turn on auto-deploy on push if
   wanted.
2. **Environment variables:** copy `.env.production.example`. Set a real
   `POSTGRES_PASSWORD` using letters and digits, since it goes into a URL.
   **Mark `NEXT_PUBLIC_API_URL` as a build variable.**
3. **Domains**, per service:
   - `web`: `https://zug.example.com:3000`
   - `api`: `https://api.zug.example.com:8000`

   The `:port` tells Coolify which container port to route to. It is not part
   of the public URL. Coolify issues the TLS certificates.
4. **Deploy.**

## Checking a deploy

```bash
curl https://api.zug.example.com/api/v1/health   # "status": "ok" and a "dataset" block
curl https://api.zug.example.com/api/v1/stats    # "total" > 0 during the day
```

Open the site:

- The HUD should say **LIVE** and count trains.
- Clicking a train draws its route.
- If the map loads but shows no trains and the browser console shows CORS or
  network errors, check `CORS_ORIGINS`. Then check `NEXT_PUBLIC_API_URL`, and
  remember that changing it needs a rebuild, not just a restart.

## Things to know

- **Ingress.** Phase 5 downloads only the static feed: about 400 KB a day. From
  Phase 6, the realtime feed is about 75 GB a day at a 60 s interval. It stays
  off until `GTFS_REALTIME_URL` is set, so check the host's transfer allowance
  first.
- **Basemap.** OpenFreeMap needs no key and has no SLA. Its attribution must
  stay visible on the map. Any CSP added later must allow
  `tiles.openfreemap.org`.
- **Rollback.** Redeploy the previous commit. Migrations are not reversed
  automatically, so before rolling back across a migration, check that the
  older code still works with the newer schema.
