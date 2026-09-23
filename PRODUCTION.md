# Production configuration

Production website: https://openwiki.online

Set these variables in the Vercel project serving that domain, then redeploy:

```text
APPLIMIT_API_URL=https://applimit-func-97195.azurewebsites.net
NEXTAUTH_URL=https://openwiki.online
NEXT_PUBLIC_OPENWIKI_PUBLIC_URL=https://openwiki.online
```

Google's authorized frontend redirect URI must be `https://openwiki.online/api/auth/callback/google`.

`appsettings.json` contains non-secret Azure Function App settings in Azure CLI import format. Azure Functions does not load this file automatically. Apply with:

```powershell
az functionapp config appsettings set --resource-group rg-applimit-97195 --name applimit-func-97195 --settings '@appsettings.json' --output none
```

Existing cloud secrets are preserved. The backend's AUTH_BASE_URL remains the Azure origin because its own `/auth/google/callback` route differs from the frontend callback.

The ignored `.env.local`, `.env.production.local`, and `local.settings.json` files have also been configured for production use on this machine. They contain existing secrets and must not be committed. These local files do not update Vercel's dashboard settings. Azure mode writes directly to shared storage; use `OPENWIKI_STORAGE_MODE=local-first` for isolated local edits.
