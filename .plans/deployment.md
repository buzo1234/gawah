# Deployment plan

Status: agreed on 22 November; the code is on the `deploy` branch (`tools/deploy/README.md` has the steps). Nothing is created in AWS until the user's go. Replaces running on the laptop behind a `cloudflared` quick tunnel, whose address changes on every start (so Meta's webhook has to be re-pasted each time) and which depends on the laptop staying awake.

## The account

- AWS Workshop Studio event account (`WSParticipantRole`), `us-west-2`. Temporary: likely deleted when the event ends, so everything here lives as long as the hackathon. The keys in `.env` are temporary too (session token).
- Allowed, by AWS's permission simulator (read-only; organisation-wide limits may still apply): `ec2:RunInstances` (t3.small and t3.medium dry-run passed), security groups, Elastic IP, `iam:CreateRole`, `iam:PassRole`, instance profiles, `iam:CreateOpenIDConnectProvider`, `secretsmanager:CreateSecret` and `GetSecretValue`, `ssm:SendCommand`, ECR.
- Already in the account and not ours: an `m8g.large` instance named "CodeEditor". Do not touch.

## Shape

| Piece | Choice |
|---|---|
| Server | One EC2 `t3.medium`, Ubuntu 24.04, `us-west-2`, about $0.04 an hour on credits |
| Address | Elastic IP, so it never changes. Named `<ip>.sslip.io` (no domain: the user's choice) |
| HTTPS | Caddy in front, with an automatic Let's Encrypt certificate for `<ip>.sslip.io` |
| App | One Docker image, built on the server (no registry): Python 3.12 with `uv`, Debian's `chromium-headless-shell` (prints the agreement PDF; it shapes Devanagari correctly where Python PDF libraries do not), `fonts-noto-core` for Noto Serif Devanagari, and ffmpeg (WhatsApp voice notes arrive as ogg Opus). One process, as today: the call agents, live connections, the database. |
| Data | A Docker volume for the SQLite database, local recordings, the memory's embedding cache, and the Sentinel's reminders. Deploys never touch it. S3 stays the store for recordings and agreements. |
| Secrets | AWS Secrets Manager, one secret `gawah/prod`: `.env` plus `.env.deploy` (server-only values, such as `ACCESS_KEY`) as JSON, without the AWS keys. The app reads it at start when `GAWAH_SECRET_ID` is set (`app/secret_store.py`). The order, first wins: the environment, the secret, `.env`, so `deploy/compose.yaml` sets `PUBLIC_BASE_URL` and `DATABASE_PATH` over any laptop value. |
| AWS access from the server | An instance role, not keys: read `gawah/prod`, read and write the S3 bucket (which also holds the deploy bundles under `deploy/`), SSM agent. Nothing else. The S3 client uses the role when no keys are set. |
| Updating a secret | `tools/deploy/push-secrets.sh`: reads the local `.env`, skips the AWS keys, writes `gawah/prod`, restarts the app. |

## Making it safe to be public

Today the dashboard, the second phone, the AI-actor controls, and the development routes rely on being on the laptop. On a public server:

Built in `app/access.py`; with `ACCESS_KEY` unset (the laptop) nothing changes.

- `/dashboard` (with `/dashboard/phone`, its state and websocket), `/actor/*`, `/dev/*` and `/memory/*` need the access key: a small form asks once and sets an http-only cookie; scripts send `X-Access-Key`. Anything else without it gets 401.
- An image the second phone attached (`/dashboard/media/<32 hex>`) stays open: the model that reads it has no key, and its name is unguessable.
- The WhatsApp webhook stays public. With the access key set, an unsigned Meta post is refused, and `WHATSAPP_PROVIDER=meta` without `META_APP_SECRET` stops the server at start.
- `/dev/publish` and the second phone's posts, which used to trust only the laptop, are taken from outside only with the access key.
- Call and call-back pages stay public, reachable only through each deal's unguessable link.
- A clip link sent on WhatsApp carries a signed expiry (a day), so it opens without the key.
- SSH stays closed: administration goes through SSM.

## CI/CD (GitHub Actions)

`.github/workflows/main.yml`. The repo is private and Actions minutes are limited, so both jobs run only on a push to `main` (a merge) and by hand, never on pull requests.

- **CI before a merge, locally**: `tools/ci.sh` (`uv sync --frozen`, `uv run pytest -q`), which `.workmux.yaml`'s pre-merge hook runs. The same script is the GitHub `ci` job.
- **CD**, after `ci` passes: `tools/deploy/deploy.sh`, the same script as by hand. It uploads `git archive` of the commit to the S3 bucket under `deploy/`, then SSM `send-command` tells the server to fetch it, `docker compose up -d --build` (the image is built on the server: no ECR), keep the data volume, and wait for the app's healthcheck. Then the job checks `https://<address>/health`.
- **AWS access from GitHub**: OIDC, a role (`gawah-github-deploy`) that trusts only `repo:buzo1234/gawah:ref:refs/heads/main`: put objects under `deploy/`, send commands only to instances tagged `app=gawah`. No AWS keys stored in GitHub. Its ARN is the repository variable `AWS_DEPLOY_ROLE_ARN`.
- **Deploy freeze**: the repository variable `DEPLOY_ENABLED=false` stops deploys on a merge, for the hours around the live demo. "Run workflow" by hand still deploys.

## Build order

1. Done on the branch: the app changes (settings from Secrets Manager, the access key, signed clip links, the refusals on a public server), tested on fakes and on the offline app.
2. Done on the branch: `Dockerfile`, `deploy/compose.yaml`, `deploy/Caddyfile`. Not built yet (no Docker on the laptop).
3. Done on the branch: `tools/deploy/provision.sh` (idempotent, everything tagged `app=gawah`, rebuilds from nothing in a fresh account), `push-secrets.sh`, `deploy.sh`, `teardown.sh`. Not run against AWS yet.
4. After the user's go: provision, push secrets, first deploy by hand, set Meta's webhook to the fixed address once, one live check.
5. Set the GitHub variables; the next merge to `main` proves CI and CD.

## Open questions for the user

- When does the workshop event end? The account and everything in it go with it.
