# Deploying Gawah to AWS

One EC2 server in `us-west-2` at `https://<elastic ip>.sslip.io`: the app and Caddy (HTTPS from Let's Encrypt) in Docker, settings in Secrets Manager (`gawah/prod`), administration through SSM (no SSH). Everything is tagged `app=gawah`, and the scripts touch nothing else. The plan and its reasons are in `.plans/deployment.md`.

The account is a Workshop Studio event account and disappears when the event ends. These steps rebuild everything in a fresh account in about 15 minutes.

## You need

- AWS CLI v2, `uv`, `git`, `python3`, `curl`.
- AWS credentials. The scripts use the shell's credentials, or `AWS_PROFILE`, or else the `AWS_*` keys in `.env`. Workshop Studio keys expire: paste fresh ones into `.env` when a script says it has no working credentials.
- `.env` filled in as for a laptop run. If `WHATSAPP_PROVIDER=meta`, `META_APP_SECRET` must be set: the server refuses to start without it.

## 1. Provision (once per account)

```
tools/deploy/provision.sh
```

It makes the security group (80 and 443 only), the Elastic IP, the instance role, GitHub's OIDC provider and the deploy role (it trusts only `buzo1234/gawah` on `main`), the secret, and the `t3.medium` instance. Running it again only adds what is missing. At the end it prints the address, the Meta webhook URL, and the GitHub variables.

The secret is `.env` plus `.env.deploy` (git-ignored, values for the server only), without the AWS keys, `PUBLIC_BASE_URL` and `DATABASE_PATH` (the server sets those). The first run makes the dashboard's access key and keeps it in `.env.deploy` as `ACCESS_KEY`. Put `ACTOR_ROUTES=1` in `.env.deploy` only if you want the AI actor ("AI plays this person") on the server; without it the actor's routes do not exist there. With it, they answer only with the access key. Do not put `ACCESS_KEY` in `.env`: the laptop would then ask for it too, and the replayer would be refused.

## 2. Settings, whenever `.env` changes

```
tools/deploy/push-secrets.sh
```

It writes `gawah/prod` and restarts the app so it reads them. Nothing is printed but the names.

## 3. GitHub variables (once)

Repository > Settings > Secrets and variables > Actions > Variables, or with `gh`:

```
gh variable set AWS_DEPLOY_ROLE_ARN --body "<printed by provision.sh>"
gh variable set DEPLOY_ENABLED --body true
```

No secrets go into GitHub. CI runs only on a push to `main` and by hand ("Run workflow"), never on pull requests. Before a merge, run `tools/ci.sh` locally (workmux's pre-merge hook does).

## 4. First deploy

```
tools/deploy/deploy.sh
```

It deploys the committed `HEAD`: a `git archive` to `s3://<S3_BUCKET>/deploy/`, then SSM tells the server to build the image and restart (the first build takes about 5 minutes; later ones reuse the cached layers). The data volume (database, recordings, memory cache, Sentinel reminders) is kept across deploys. It ends by checking `https://<address>/health`.

Then open `https://<address>/dashboard` and enter the access key from `.env.deploy`. The browser keeps it for 30 days.

## 5. Webhooks (once, the address never changes)

- **Meta**: App > WhatsApp > Configuration > Callback URL `https://<address>/whatsapp/webhook`, verify token `META_VERIFY_TOKEN` from `.env`. Subscribe to `messages`.
- **Twilio** (if used): the sandbox's "When a message comes in" URL is the same address.

Check one real message end to end after this.

## 6. After that

A merge to `main` runs CI, then deploys. By hand: `tools/deploy/deploy.sh` (or `tools/deploy/deploy.sh <commit>` to roll back).

Logs: `aws ssm start-session --target <instance>` (needs AWS's Session Manager plugin), then `cd /opt/gawah/app && sudo docker compose -p gawah -f deploy/compose.yaml --env-file /opt/gawah/host.env logs -f app`.

## 7. Freeze before the demo

```
gh variable set DEPLOY_ENABLED --body false
```

A merge then runs CI but does not deploy. "Run workflow" by hand and `deploy.sh` still deploy. Set it back to `true` after the demo.

## 8. Teardown

```
tools/deploy/teardown.sh
```

It lists everything tagged `app=gawah`, asks you to type `gawah`, then removes it: the instance (and its database and local recordings), the Elastic IP, the security group, both roles, the instance profile, the OIDC provider if it made it, and the secret (at once, no recovery window). The S3 bucket is not touched; it prints how to remove the deploy bundles.
