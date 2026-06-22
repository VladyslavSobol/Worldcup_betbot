# Deploy to Google Cloud VM

This guide deploys the Telegram betting bot to an existing Google Cloud VM using Docker Compose.

VM external IP: `207.175.20.145`

Important:

- Do not commit `.env`.
- Do not upload `.env` to GitHub.
- Create `.env` manually on the server.
- Stop the local bot before starting the VM bot, so the same Telegram token is not used by two running bots.

## 1. Prepare GitHub

From the project folder on Windows:

```powershell
cd C:\Users\vlads\Documents\Codex\2026-06-22\new-chat\outputs\worldcup-betting-bot
```

If the project is not a Git repository yet:

```powershell
git init
git branch -M main
```

Check that `.env` is ignored:

```powershell
git status --short --ignored
git check-ignore -v .env
```

Expected: `git check-ignore -v .env` prints the `.gitignore` rule for `.env`.

Add and commit the deploy-ready files:

```powershell
git add .
git status --short
git commit -m "Prepare Docker Compose deployment"
```

Before pushing, confirm `.env` is not staged:

```powershell
git diff --cached --name-only
```

The output must not contain `.env`.

Create an empty GitHub repository, then connect and push:

```powershell
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

## 2. Stop the local bot on Windows

Run this from the local project folder before starting the bot on the VM:

```powershell
docker compose down
```

## 3. SSH into the VM

Use your Google Cloud SSH method, for example:

```bash
gcloud compute ssh YOUR_VM_NAME --zone YOUR_VM_ZONE
```

Or connect directly if SSH keys are configured:

```bash
ssh YOUR_VM_USER@207.175.20.145
```

## 4. Clone the repository on the VM

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
```

## 5. Create `.env` manually on the VM

Create the production `.env` file directly on the server:

```bash
nano .env
```

Paste the real values into `.env`, save, and exit.

Do not commit this file. Do not upload it to GitHub.

## 6. Start the bot on the VM

```bash
docker compose up -d --build
```

## 7. Verify the deployment

Check containers:

```bash
docker compose ps
```

Expected: `bot` and `db` are `Up`.

Check bot logs:

```bash
docker compose logs --tail=100 bot
```

Then open Telegram and send:

```text
/start
```

## 8. View logs

```bash
docker compose logs -f bot
```

## 9. Restart the bot

```bash
docker compose restart bot
```

## 10. Update code on the server

From the repository folder on the VM:

```bash
git pull
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 bot
```

## Checklist before starting on the server

- Local bot on the Windows PC is stopped with `docker compose down`.
- `.env` is created manually on the server.
- `.env` is not in GitHub.
- Google VM is running.
- Docker works on the VM.
- `docker compose ps` shows `bot` and `db` as `Up`.
- Telegram bot responds to `/start`.
