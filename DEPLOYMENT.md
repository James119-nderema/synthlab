# Deploy SynthLab with Docker Compose

This setup runs Django under Gunicorn. Docker Compose keeps the SQLite database
and uploaded/generated datasets in named volumes so they survive container
rebuilds and restarts. It is suitable for a single application host; SQLite is
not intended for multiple application replicas.

## Requirements

- Docker Engine with the Docker Compose plugin
- A host with enough disk space for the ML dependencies and generated datasets
- A DNS name and HTTPS reverse proxy for a public deployment

The pinned PyTorch and scientific-computing dependencies make the image large.
The included setup runs on CPU; generation can take longer than on a CUDA host.

## First deployment

From the repository root:

1. Create the environment file and generate a strong Django secret:

   ```sh
   cp .env.example .env
   python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
   ```

2. Edit `.env`. Set `DJANGO_SECRET_KEY` to the generated value,
   `DJANGO_ALLOWED_HOSTS` to the host name (comma separated), and
   `DJANGO_CSRF_TRUSTED_ORIGINS` to full origins including `https://`.
   Keep `DJANGO_DEBUG=false`.

3. Build and start the service:

   ```sh
   docker compose up --build -d
   docker compose logs -f web
   ```

4. Create an administrator account:

   ```sh
   docker compose exec web python manage.py createsuperuser
   ```

Open `http://your-host:8000` for a local or private-network deployment.
For public use, put the service behind a TLS reverse proxy or your hosting
platform's HTTPS ingress. Forward the original `Host` and
`X-Forwarded-Proto: https` headers. Then set these in `.env`:

```dotenv
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.example
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SECURE_COOKIES=true
```

Do not expose port 8000 directly to the public internet when relying on the
proxy for HTTPS. Restrict network access to the proxy and app host.

## Updating the deployment

Back up the database and media volumes, then rebuild and restart:

```sh
docker compose exec web python manage.py dumpdata --natural-foreign --natural-primary > synthlab-backup.json
docker compose down
docker compose up --build -d
```

The entrypoint applies Django migrations on startup. The named volumes remain
in place when containers are rebuilt. To make a full backup, also archive the
Docker volumes `synthlab_synthlab_data` and `synthlab_synthlab_media`; the JSON
export does not contain uploaded CSV files.

## Useful commands

```sh
docker compose ps
docker compose logs -f web
docker compose exec web python manage.py check --deploy
docker compose down
```

`docker compose down -v` deletes the persistent database and dataset volumes;
avoid it unless you intend to erase application data.
