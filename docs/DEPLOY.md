# Deploying the free live demo

The app ships as a **single Docker image**: FastAPI serves both the API and the built React app.

## Option A: Render (recommended)

1. Push this repo to GitHub.
2. On [render.com](https://render.com): **New → Blueprint**, then pick the repo. Render reads `render.yaml`.
3. Database:
   - **Simplest:** leave `DATABASE_URL` empty. The app uses SQLite inside the container and reseeds on every boot.
   - **Postgres:** create a free database on [Neon](https://neon.tech) (free tier doesn't expire) and paste its connection string into `DATABASE_URL`. `postgres://…` URLs are converted automatically.
4. Deploy. The first boot generates about 18k synthetic tickets and trains the model (roughly 20–40 seconds on the free tier).
5. Copy the `https://opspulse-xxxx.onrender.com` URL into the README.

`RESET_ON_STARTUP=true` is set in the blueprint. Free instances sleep after about 15 minutes idle and reseed on wake, so the demo queue is always relative to "today" and visitors' changes don't pile up.

## Option B: any Docker host

```bash
docker build -t opspulse .
docker run -p 8000:8000 -e RESET_ON_STARTUP=true opspulse
# or with Postgres:
docker run -p 8000:8000 -e DATABASE_URL=postgresql://user:pass@host/db opspulse
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./opspulse.db` | SQLAlchemy URL; `postgres://` is accepted |
| `SEED_ON_STARTUP` | `true` | Seed synthetic data if the DB is empty |
| `RESET_ON_STARTUP` | `false` | Drop and reseed on every boot |
| `HISTORY_DAYS` | `365` | Days of synthetic history |
| `MODEL_DIR` | `./models` | Where the trained model is stored |
| `PORT` | `8000` | Port (set automatically by Render) |
