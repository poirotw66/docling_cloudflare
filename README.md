# Docling Cloudflare API

This project now uses the following recommended architecture:

1. The `Docling API` runs on your own local machine or private server.
2. `Nginx` acts as the local reverse proxy.
3. `cloudflared` exposes the local service to the public internet through `Cloudflare Tunnel`.
4. Users access the service through `docling.itr-lab.cloud`, while the actual document parsing still runs on your local infrastructure.

This approach is a better fit for `docling`, which depends on a full Python runtime and heavier system libraries, and it avoids the limitations of running the compute layer directly on Cloudflare.

## Architecture

```text
Client
  -> Cloudflare Edge
  -> Cloudflare Tunnel
  -> Nginx gateway
  -> FastAPI + Docling
```

## Available Endpoints

### `GET /`

Serves the built-in browser UI for one-off conversions. The page supports:

1. Uploading a PDF file
2. Submitting a PDF URL
3. Downloading Markdown with embedded base64 images
4. Downloading a ZIP package with extracted images
5. Entering an API key when the deployment keeps `API_KEYS` enabled

### `GET /health`

Checks whether the container service is available.

### `POST /v1/convert`

Two request styles are supported.

By default, the API returns JSON:

```json
{
  "filename": "paper.pdf",
  "markdown": "# ..."
}
```

By default, JSON mode now embeds images directly into the Markdown as base64 `data:image/...` URIs.

If you want a downloadable package instead, set `response_format=zip`. The API will return a ZIP archive containing:

1. One Markdown file
2. An `images/` directory with extracted `.jpg` images

The Markdown inside the ZIP references those local image files.

#### Option 1: Provide a PDF URL

Headers:

```http
Content-Type: application/json
Authorization: Bearer <your-api-key>
```

Request body:

```json
{
  "source_url": "https://arxiv.org/pdf/2408.09869"
}
```

#### Option 2: Upload a PDF file

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./Beyond RAG for Agent Memory- Retrieval by Decoupling and Aggregation.pdf"
```

If you are calling the local gateway and `API_KEYS=` is empty in `.env`, you can omit the auth header:

```bash
curl -X POST "http://127.0.0.1:18080/v1/convert" \
  -F "file=@./Beyond RAG for Agent Memory- Retrieval by Decoupling and Aggregation.pdf"
```

Default response format:

```json
{
  "filename": "paper.pdf",
  "markdown": "# ..."
}
```

Download a ZIP package instead:

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert?response_format=zip" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./paper.pdf" \
  -o paper.zip
```

If you want to save the returned Markdown directly to a file, this pattern is safer than piping straight into a target file because it avoids leaving an empty output file behind when the request is interrupted:

```bash
curl -fsS -X POST "http://127.0.0.1:18080/v1/convert" \
  -F "file=@/home/justin/docling_file/input/2604.pdf" \
  -o /tmp/2604_response.json

jq -er '.markdown' /tmp/2604_response.json \
  > /home/justin/docling_file/input/2604.md
```

You can also convert a host file path from the mounted `input/` directory without uploading the file body:

```bash
curl -fsS -X POST "http://127.0.0.1:18080/v1/convert" \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "/home/justin/docling_file/input/2604.pdf"
  }'
```

## Local Deployment

Prerequisites:

1. You have Docker and Docker Compose installed.
2. You have a Cloudflare account.
3. `itr-lab.cloud` is managed by Cloudflare.
4. You can run `cloudflared` on your local machine or server.

### 1. Configure Environment Variables

Copy the environment template:

```bash
cp .env.example .env
```

At minimum, update these values:

```dotenv
API_KEYS=<your-random-api-key>
GATEWAY_PORT=18080
HOST_INPUT_PREFIX=/absolute/path/to/your/project/input
CONTAINER_INPUT_DIR=/data/input
CLOUDFLARE_TUNNEL_TOKEN=<Cloudflare Tunnel token>
```

Use a high-entropy string for `API_KEYS`, for example:

```bash
openssl rand -hex 32
```

If you want to disable application-layer API key auth for local testing, you can leave it empty:

```dotenv
API_KEYS=
```

When you change `API_KEYS`, you must recreate the `docling-api` container before the change takes effect.

### 2. Start the Local API and Gateway

```bash
docker compose -f docker-compose.local.yml up -d --build
```

If you want to start with CPU mode, the command above is enough.

If you want GPU mode, use:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --build
```

If you are switching an existing CPU container back to GPU mode, do not restart with `docker-compose.local.yml` alone. Recreate the service with the GPU override, otherwise Docker will start the container without GPU device requests and Docling will fall back to CPU:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --force-recreate docling-api gateway
```

After startup:

1. The Docling API is available at `127.0.0.1:8000`
2. The local Nginx gateway is available at `127.0.0.1:${GATEWAY_PORT}`, which defaults to `127.0.0.1:18080`

You can verify locally first:

```bash
curl http://127.0.0.1:18080/health
```

Open the browser UI locally at:

```text
http://127.0.0.1:18080/
```

If `API_KEYS` is enabled, paste a valid key into the `API key` field before converting.

### 3. Handle Local PDF Files

The current Compose configuration mounts the host `./input` directory read-only into the container at `/data/input`.

That means you have two options:

1. Upload a file directly
2. Pass an absolute path from the host `input/` directory, and let the service map it to the container path automatically

For example, this request:

```json
{
  "source_url": "/home/justin/docling_file/input/A-RAG- Scaling Agentic Retrieval-Augmented.pdf"
}
```

Will be mapped automatically to:

```text
/data/input/A-RAG- Scaling Agentic Retrieval-Augmented.pdf
```

If you move to another machine or change the project path, only update these values in `.env`:

```dotenv
HOST_INPUT_PREFIX=...
CONTAINER_INPUT_DIR=/data/input
```

## Enable GPU

This project already includes optional GPU support, as long as Docker on the host can access the NVIDIA GPU.

Your machine already meets the key requirement because this command runs successfully:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

This confirms:

1. The NVIDIA driver is working
2. NVIDIA Container Toolkit is available
3. Docker containers can access the GPU

### GPU Startup

Set the following in `.env`:

```dotenv
DOCLING_GPU_ENABLED=true
```

Then start the stack with the GPU override:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml down
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --build
```

If the service is already running and you only want to switch it from CPU mode to GPU mode, this recreate command is usually enough:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --force-recreate docling-api gateway
```

### What GPU Mode Changes

In GPU mode, the service will:

1. Use [Dockerfile.gpu](Dockerfile.gpu) to install CUDA-enabled PyTorch
2. Add `gpus: all` to the `docling-api` container
3. Enable `AcceleratorDevice.CUDA` in [container/app/main.py](container/app/main.py)
4. Switch the OCR backend to `RapidOCR + torch`

### Verify GPU Is Active

Check the container logs first. In CPU mode, you typically see:

```text
Using CPU device
```

After switching to GPU mode, you should see CUDA-related output instead of always using CPU.

You can also verify directly inside the container:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml exec -T docling-api python - <<'PY'
import torch
print('cuda_available=', torch.cuda.is_available())
print('device_count=', torch.cuda.device_count())
PY
```

If `torch.cuda.is_available()` is `False` even though your host GPU works, the most common cause is that the container was started without the GPU override file. You can confirm that the running container has a GPU request with:

```bash
docker inspect docling_file-docling-api-1 --format '{{json .HostConfig.DeviceRequests}}'
```

In GPU mode this should not be `null`.

### Notes

GPU acceleration does not necessarily make every PDF obviously faster, especially when:

1. The document has very few pages
2. The first run is still downloading models
3. OCR is not the main bottleneck

For longer documents, batch workloads, and heavier OCR/layout tasks, GPU support is generally more useful.

## Expose the Service Through Cloudflare

### 1. Create a Tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create docling-local
```

Then route `docling.itr-lab.cloud` to that tunnel:

```bash
cloudflared tunnel route dns docling-local docling.itr-lab.cloud
```

### 2. Get the Tunnel Token

Retrieve the tunnel token from the Cloudflare Zero Trust or Tunnel page.

Write it into `.env`:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=...
```

### 3. Start `cloudflared`

If you want `cloudflared` to be started by Docker Compose:

```bash
docker compose -f docker-compose.local.yml --profile tunnel up -d
```

If you want to run `cloudflared` separately:

```bash
cloudflared tunnel run --token <YOUR_TUNNEL_TOKEN>
```

### Using a Locally Configured Tunnel

If Cloudflare Dashboard shows:

```text
docling-local cannot be managed from the Zero Trust dashboard as it is a locally configured tunnel.
```

This is not an error and does not block tunnel usage.

It only means your current `docling-local` tunnel was created through the local `cloudflared` configuration rather than the dashboard-managed mode.

In that case, you have two options:

1. Keep using the locally configured tunnel
2. Create a new dashboard-managed tunnel and switch to token-based startup

If your priority is to get the service working quickly, keeping the local tunnel is the simpler option.

This project already includes the local tunnel Compose file and config:

- [docker-compose.tunnel-local.yml](docker-compose.tunnel-local.yml)
- [cloudflared/config.yml](cloudflared/config.yml)

Start it with:

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  up -d cloudflared
```

If you use this path, you do not need `CLOUDFLARE_TUNNEL_TOKEN` from `.env`.

Notes:

1. The `credentials-file` in [cloudflared/config.yml](cloudflared/config.yml) must point to a real credentials file
2. If the generated file under `/home/justin/.cloudflared` is not named `docling-local.json`, update the config to match the actual filename

You can check the directory with:

```bash
ls -l /home/justin/.cloudflared
```

Usually the credentials file is a UUID, such as:

```text
12345678-1234-1234-1234-123456789abc.json
```

If so, use the real UUID-based filename in [cloudflared/config.yml](cloudflared/config.yml).

### 4. Optional: Add Cloudflare Access for Edge Authentication

It is recommended to configure `docling.itr-lab.cloud` as a Cloudflare Access self-hosted application.

This gives you an additional protection layer at the Cloudflare edge, for example:

1. Only allow users from approved email domains
2. Only allow requests with a Service Token
3. Only allow requests from specific source IPs

Keep `API_KEYS` enabled at the application layer as well, so requests still require an API key even if they reach the origin.

## API Keys

The local deployment no longer depends on Wrangler secrets. It reads keys directly from environment variables:

```dotenv
API_KEYS=team-a-key,team-b-key
```

You can provide one or more keys, separated by commas.

Example:

```text
team-a-key,team-b-key
```

If `API_KEYS` is empty, the API accepts requests without `Authorization` or `X-API-Key`. This is convenient for local testing, but it should not be used for an internet-exposed deployment.

Clients can send either:

```http
Authorization: Bearer <your-api-key>
```

Or:

```http
X-API-Key: <your-api-key>
```

## CORS

The local deployment reads `CORS_ALLOW_ORIGIN` from environment variables.

For example:

```dotenv
CORS_ALLOW_ORIGIN=https://app.itr-lab.cloud,https://admin.itr-lab.cloud
```

## Production Rollout Steps

The following checklist fits the architecture that is already working in this project: local `Docling API` + `Nginx` + `Cloudflare Tunnel`.

### 1. Prepare Environment Variables

Make sure `.env` contains at least:

```dotenv
API_KEYS=<your-production-api-key>
GATEWAY_PORT=18080
HOST_INPUT_PREFIX=/absolute/path/to/your/project/input
CONTAINER_INPUT_DIR=/data/input
DOCLING_GPU_ENABLED=true
```

If you are using the locally configured tunnel mode, make sure these values are correct in [cloudflared/config.yml](cloudflared/config.yml):

```yaml
tunnel: <your-tunnel-uuid>
origincert: /root/.cloudflared/cert.pem
credentials-file: /root/.cloudflared/<your-tunnel-uuid>.json
```

### 2. Start Local Services

CPU mode:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

GPU mode:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --build
```

### 3. Start Cloudflare Tunnel

If you are using the local tunnel configuration:

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  up -d cloudflared
```

### 4. Validate Locally

Check that the local gateway responds correctly:

```bash
curl http://127.0.0.1:18080/health
```

Expected result:

```json
{"status":"ok"}
```

### 5. Validate Public Access

After the tunnel is connected, verify the public hostname:

```bash
curl https://docling.itr-lab.cloud/health
```

Expected result:

```json
{"status":"ok"}
```

### 6. Final Checks Before Opening to External Users

1. `API_KEYS` has been replaced with a production-grade random secret
2. `docling.itr-lab.cloud` correctly routes to the tunnel
3. Local ports `8000` and the gateway port are only bound to `127.0.0.1`
4. Cloudflare Access is enabled if you want an additional edge protection layer
5. At least one real PDF conversion request has been tested successfully

## Restart Commands

### Restart Only the Docling API and Gateway

CPU mode:

```bash
docker compose -f docker-compose.local.yml restart docling-api gateway
```

GPU mode:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml restart docling-api gateway
```

### Restart Only Cloudflare Tunnel

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  restart cloudflared
```

### Rebuild and Start the Full Stack

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  up -d --build
```

### Check Running Status

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  ps
```

### View Logs

Docling API:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml logs -f docling-api
```

Gateway:

```bash
docker compose -f docker-compose.local.yml logs -f gateway
```

Tunnel:

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  logs -f cloudflared
```

## External Client Examples

The following examples are suitable for third-party callers.

If you only need a manual conversion flow, you can also use the built-in browser UI at `/` instead of calling the API directly.

### curl: Send a PDF URL

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-api-key>" \
  -d '{
    "source_url": "https://arxiv.org/pdf/2408.09869"
  }'
```

### curl: Upload a Local PDF

```bash
curl -fsS -X POST "https://docling.itr-lab.cloud/v1/convert" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./paper.pdf" \
  -o /tmp/paper_response.json

jq -er '.markdown' /tmp/paper_response.json > paper.md
```

### curl: Download the ZIP Package

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert?response_format=zip" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./paper.pdf" \
  -o paper.zip
```

### Python: Send a PDF URL

```python
import requests

api_key = "<your-api-key>"
url = "https://docling.itr-lab.cloud/v1/convert"

response = requests.post(
    url,
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "source_url": "https://arxiv.org/pdf/2408.09869",
    },
    timeout=300,
)
response.raise_for_status()

data = response.json()
print(data["filename"])
print(data["markdown"][:500])
```

### Python: Upload a Local PDF

```python
import requests

api_key = "<your-api-key>"
url = "https://docling.itr-lab.cloud/v1/convert"

with open("paper.pdf", "rb") as file_obj:
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
        },
        files={
            "file": ("paper.pdf", file_obj, "application/pdf"),
        },
        timeout=300,
    )

response.raise_for_status()
data = response.json()

print(data["filename"])
print(data["markdown"][:500])
```

### Python: Save Markdown to a File

```python
import requests

api_key = "<your-api-key>"
url = "https://docling.itr-lab.cloud/v1/convert"

with open("paper.pdf", "rb") as file_obj:
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": ("paper.pdf", file_obj, "application/pdf")},
        timeout=300,
    )

response.raise_for_status()
data = response.json()

with open("paper.md", "w", encoding="utf-8") as markdown_file:
    markdown_file.write(data["markdown"])

print("saved:", "paper.md")
```

## Production Recommendations

### 1. Do Not Open Inbound Server Ports

`cloudflared` uses outbound connections. Your server does not need to expose ports `8000` or `8080` directly to the public internet.

### 2. Use Both Cloudflare Access and API Keys

Use both edge-level and application-level authentication. That is safer than relying on only one mechanism.

### 3. Prefer URLs Over Large File Uploads

If your PDFs are large, it is better to upload them to R2 or another object store first, then pass the accessible URL to `/v1/convert`. That is more stable than routing large uploads through the tunnel path.

### 4. Move to Async Processing When Traffic Grows

If concurrency increases later, the recommended direction is:

1. The API accepts the request
2. The file is stored in object storage
3. A job is written to a queue
4. A backend worker processes the conversion asynchronously
5. The result is written back to R2 or D1

The current version is intentionally a minimal synchronous API so you can get a working deployment first.

## Key Files

- `container/app/main.py`: FastAPI + Docling conversion logic
- `container/app/app_shell.py`: built-in browser UI served directly by FastAPI
- `Dockerfile`: local Docling service image
- `Dockerfile.gpu`: GPU-enabled Docling service image
- `docker-compose.local.yml`: local API, Nginx, and token-based `cloudflared` profile orchestration
- `docker-compose.gpu.yml`: GPU override for the Docling API container
- `deploy/nginx/default.conf`: local reverse proxy configuration
- `cloudflared/config.yml.example`: example config for a named tunnel
- `.env.example`: environment variable template for local runtime

## Known Limitations

1. The first cold start and initial model downloads are slower than later requests
2. The current response is Markdown only and does not yet provide richer structured JSON output
3. The current design is a single-machine synchronous processing setup, suitable for getting the service running, but not for high-concurrency multi-tenant production workloads
