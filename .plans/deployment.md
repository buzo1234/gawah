# Deployment plan

Status: proposed on 22 November, waiting on the user's go. Replaces running on the laptop behind a `cloudflared` quick tunnel, whose address changes on every start (so Meta's webhook has to be re-pasted each time) and which depends on the laptop staying awake.

## The account

- AWS Workshop Studio event account (`WSParticipantRole`), `us-west-2`. Temporary: likely deleted when the event ends, so everything here lives as long as the hackathon. The keys in `.env` are temporary too (session token).
- Allowed, by AWS's permission simulator (read-only; organisation-wide limits may still apply): `ec2:RunInstances` (t3.small and t3.medium dry-run passed), security groups, Elastic IP, `iam:CreateRole`, `iam:PassRole`, instance profiles, `iam:CreateOpenIDConnectProvider`, `secretsmanager:CreateSecret` and `GetSecretValue`, `ssm:SendCommand`, ECR.
- Already in the account and not ours: an `m8g.large` instance named "CodeEditor". Do not touch.

## Shape

| Piece | Choice |
|---|---|
| Server | One EC2 `t3.medium`, Ubuntu 24.04, `us-west-2`, about $0.04 an hour on credits |
| Address | Elastic IP, so it never changes |
| HTTPS | Caddy in front, with an automatic Let's Encrypt certificate for `<ip>.sslip.io` (free, no domain). A real domain if the user has one. |
| App | One Docker image: Python 3.12 with `uv`, Chromium (prints the agreement PDF; it shapes Devanagari correctly where Python PDF libraries do not), ffmpeg. One process, as today: the call agents, live connections, the database. |
| Data | A Docker volume for the SQLite database, local recordings, the memory's embedding cache, and the Sentinel's reminders. Deploys never touch it. S3 stays the store for recordings and agreements. |
| Secrets | AWS Secrets Manager, one secret `gawah/prod` holding today's `.env` without the AWS keys. The container loads it at start. |
| AWS access from the server | An instance role, not keys: read `gawah/prod`, read and write the S3 bucket, SSM agent. Nothing else. |
| Updating a secret | `tools/deploy/push-secrets.sh`: reads the local `.env`, skips the AWS keys, writes `gawah/prod`, restarts the app. |

## Making it safe to be public

Today the dashboard, the second phone, the AI-actor controls, and the development routes rely on being on the laptop. On a public server:

- The dashboard, `/dashboard/phone`, `/actor/*`, and `/dev/*` need an access key (one value in the secret, asked once by the browser and kept in a cookie).
- The WhatsApp webhook stays public, with Meta's signature checked on every post (`META_APP_SECRET` must be set).
- Call and call-back pages stay public, reachable only through each deal's unguessable link.
- The memory's clip route serves only to the dashboard (access key) or through short-lived signed links (WhatsApp).
- SSH stays closed: administration goes through SSM.

## CI/CD (GitHub Actions)

- **CI**, on every pull request and push: `uv sync`, `uv run pytest -q` (the tests use fakes; no secrets needed). A failed run blocks the merge.
- **CD**, on a push to `main` after CI passes, and on a manual "Deploy now" button:
  1. Build the image, push to ECR.
  2. SSM `send-command` to the server: pull the image, restart, keep the data volume.
  3. Check `/health` over HTTPS and the services check; fail the job if either fails.
- **AWS access from GitHub**: OIDC, a role that trusts only `buzo1234/gawah` on `main`. No AWS keys stored in GitHub.
- **Deploy freeze**: a repository variable (`DEPLOY_ENABLED=false`) stops automatic deploys, for the hours around the live demo. The manual button still works.

## Build order

1. App changes: the access key on the private routes; loading settings from Secrets Manager when `GAWAH_SECRET_ID` is set; a production mode with the development routes off unless the access key is given.
2. Docker image and Compose file (app and Caddy), run once locally against the offline app.
3. `tools/deploy/provision.sh` (idempotent, AWS CLI): security group (80 and 443 only), Elastic IP, instance role and profile, the secret, ECR repository, the instance with Docker and the SSM agent.
4. First deploy by hand; set Meta's webhook to the fixed address once; one live check.
5. GitHub Actions: CI, then CD with OIDC; a deploy through a pull request to prove it.

## Open questions for the user

- When does the workshop event end? The account and everything in it go with it.
- A domain of their own, or is `<ip>.sslip.io` fine?
