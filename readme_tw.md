# Docling Cloudflare API

這個專案目前採用的推薦架構如下：

1. `Docling API` 執行在你自己的本機或內網伺服器上。
2. `Nginx` 作為本地反向代理。
3. `cloudflared` 透過 `Cloudflare Tunnel` 將本地服務暴露到公網。
4. 使用者透過 `docling.itr-lab.cloud` 存取服務，但實際的文件解析仍在你的本地基礎設施上執行。

這種方式更適合 `docling` 這類依賴完整 Python 執行環境與較重系統函式庫的服務，也能避開直接把運算層部署到 Cloudflare 的限制。

## 架構

```text
Client
  -> Cloudflare Edge
  -> Cloudflare Tunnel
  -> Nginx gateway
  -> FastAPI + Docling
```

## 提供的介面

### `GET /health`

檢查容器服務是否可用。

### `POST /v1/convert`

支援兩種請求方式。

預設情況下，API 會回傳 JSON：

```json
{
  "filename": "paper.pdf",
  "markdown": "# ..."
}
```

現在 JSON 模式預設會把圖片直接以 base64 `data:image/...` 的形式內嵌在 Markdown 裡。

如果你希望下載打包好的檔案，請改用 `response_format=zip`。API 會回傳一個 ZIP，內容包含：

1. 一個 Markdown 檔
2. 一個 `images/` 目錄，裡面是抽出的 `.jpg` 圖片

ZIP 裡的 Markdown 會直接引用這些本地圖片檔。

#### 方式 1：提供 PDF URL

請求標頭：

```http
Content-Type: application/json
Authorization: Bearer <your-api-key>
```

請求內容：

```json
{
  "source_url": "https://arxiv.org/pdf/2408.09869"
}
```

#### 方式 2：上傳 PDF 檔案

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./Beyond RAG for Agent Memory- Retrieval by Decoupling and Aggregation.pdf"
```

如果你呼叫的是本地 gateway，而且 `.env` 裡的 `API_KEYS=` 是空的，就可以省略授權標頭：

```bash
curl -X POST "http://127.0.0.1:18080/v1/convert" \
  -F "file=@./Beyond RAG for Agent Memory- Retrieval by Decoupling and Aggregation.pdf"
```

預設回傳格式：

```json
{
  "filename": "paper.pdf",
  "markdown": "# ..."
}
```

如果要直接下載 ZIP 檔案：

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert?response_format=zip" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./paper.pdf" \
  -o paper.zip
```

如果你想把回傳的 Markdown 直接寫成檔案，建議先把完整 JSON 存成暫存檔，再用 `jq` 抽出 `.markdown`。這樣就算請求中途被中斷，也不會把目標檔案留成空檔：

```bash
curl -fsS -X POST "http://127.0.0.1:18080/v1/convert" \
  -F "file=@/home/justin/docling_file/input/2604.pdf" \
  -o /tmp/2604_response.json

jq -er '.markdown' /tmp/2604_response.json \
  > /home/justin/docling_file/input/2604.md
```

如果檔案本來就在掛載的 `input/` 目錄裡，你也可以不直接上傳檔案內容，而是傳宿主機路徑：

```bash
curl -fsS -X POST "http://127.0.0.1:18080/v1/convert" \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "/home/justin/docling_file/input/2604.pdf"
  }'
```

## 本地部署

前提條件：

1. 已安裝 Docker 與 Docker Compose。
2. 有一個 Cloudflare 帳號。
3. `itr-lab.cloud` 已交由 Cloudflare 管理。
4. 可以在本機或伺服器上執行 `cloudflared`。

### 1. 設定環境變數

複製環境變數範本：

```bash
cp .env.example .env
```

至少要修改以下欄位：

```dotenv
API_KEYS=<你的隨機 API Key>
GATEWAY_PORT=18080
HOST_INPUT_PREFIX=/absolute/path/to/your/project/input
CONTAINER_INPUT_DIR=/data/input
CLOUDFLARE_TUNNEL_TOKEN=<Cloudflare Tunnel token>
```

建議 `API_KEYS` 使用高熵隨機字串，例如：

```bash
openssl rand -hex 32
```

### 2. 啟動本地 API 與 Gateway

```bash
docker compose -f docker-compose.local.yml up -d --build
```

如果先使用 CPU 模式，上面這條命令就足夠。

如果要使用 GPU 模式，請改用：

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --build
```

啟動後：

1. Docling API 會在 `127.0.0.1:8000`
2. 本地 Nginx gateway 會在 `127.0.0.1:${GATEWAY_PORT}`，預設是 `127.0.0.1:18080`

你可以先做本地驗證：

```bash
curl http://127.0.0.1:18080/health
```

### 3. 處理本地 PDF 檔案

目前的 Compose 設定會將宿主機的 `./input` 目錄以唯讀方式掛載到容器內的 `/data/input`。

因此你有兩種方式：

1. 直接上傳檔案
2. 傳入宿主機 `input/` 目錄中的絕對路徑，讓服務自動映射到容器內路徑

例如以下請求：

```json
{
  "source_url": "/home/justin/docling_file/input/A-RAG- Scaling Agentic Retrieval-Augmented.pdf"
}
```

會自動映射成：

```text
/data/input/A-RAG- Scaling Agentic Retrieval-Augmented.pdf
```

如果你換了機器或更改專案路徑，只要修改 `.env` 裡這兩個值：

```dotenv
HOST_INPUT_PREFIX=...
CONTAINER_INPUT_DIR=/data/input
```

## 啟用 GPU

此專案已補上可選的 GPU 支援，前提是宿主機的 Docker 可以正常存取 NVIDIA GPU。

你的機器已經符合最關鍵條件，因為以下命令可以成功執行：

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

這代表：

1. NVIDIA 驅動正常
2. NVIDIA Container Toolkit 可用
3. Docker 容器可以存取 GPU

### GPU 啟動方式

在 `.env` 中設定：

```dotenv
DOCLING_GPU_ENABLED=true
```

然後使用 GPU override 啟動：

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml down
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --build
```

### GPU 模式會變更什麼

在 GPU 模式下，服務會：

1. 使用 [Dockerfile.gpu](Dockerfile.gpu) 安裝支援 CUDA 的 PyTorch
2. 為 `docling-api` 容器加入 `gpus: all`
3. 在 [container/app/main.py](container/app/main.py) 中啟用 `AcceleratorDevice.CUDA`
4. 將 OCR backend 切換為 `RapidOCR + torch`

### 驗證 GPU 是否啟用

先查看容器日誌。CPU 模式通常會看到：

```text
Using CPU device
```

切換到 GPU 模式後，應該會看到與 CUDA 相關的輸出，而不是一直使用 CPU。

你也可以直接在容器內驗證：

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml exec -T docling-api python - <<'PY'
import torch
print('cuda_available=', torch.cuda.is_available())
print('device_count=', torch.cuda.device_count())
PY
```

### 補充說明

GPU 加速不一定會讓每一份 PDF 都明顯變快，特別是在以下情況：

1. 文件頁數很少
2. 第一次執行仍在下載模型
3. OCR 不是主要瓶頸

對於較長文件、批次工作與較重的 OCR 或版面分析任務，GPU 一般會更有幫助。

## 透過 Cloudflare 對外開放服務

### 1. 建立 Tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create docling-local
```

然後將 `docling.itr-lab.cloud` 路由到這個 tunnel：

```bash
cloudflared tunnel route dns docling-local docling.itr-lab.cloud
```

### 2. 取得 Tunnel Token

從 Cloudflare Zero Trust 或 Tunnel 頁面取得 tunnel token。

把它寫入 `.env`：

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=...
```

### 3. 啟動 `cloudflared`

如果你希望透過 Docker Compose 啟動 `cloudflared`：

```bash
docker compose -f docker-compose.local.yml --profile tunnel up -d
```

如果你想單獨執行 `cloudflared`：

```bash
cloudflared tunnel run --token <YOUR_TUNNEL_TOKEN>
```

### 使用本地設定的 Tunnel

如果 Cloudflare Dashboard 顯示：

```text
docling-local cannot be managed from the Zero Trust dashboard as it is a locally configured tunnel.
```

這不是錯誤，也不會阻止 tunnel 使用。

它只表示目前的 `docling-local` tunnel 是透過本機 `cloudflared` 設定建立的，而不是 Dashboard 託管模式。

在這種情況下，你有兩個選擇：

1. 繼續使用本地設定的 tunnel
2. 建立新的 Dashboard 託管 tunnel，並切換成 token 啟動方式

如果你的重點是先把服務跑通，繼續使用本地 tunnel 會比較簡單。

本專案已經提供本地 tunnel 的 Compose 檔與設定檔：

- [docker-compose.tunnel-local.yml](docker-compose.tunnel-local.yml)
- [cloudflared/config.yml](cloudflared/config.yml)

啟動方式：

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  up -d cloudflared
```

如果你使用這個方式，就不需要 `.env` 中的 `CLOUDFLARE_TUNNEL_TOKEN`。

注意事項：

1. [cloudflared/config.yml](cloudflared/config.yml) 中的 `credentials-file` 必須指向真實存在的憑證檔
2. 如果 `/home/justin/.cloudflared` 中產生的檔名不是 `docling-local.json`，請改成實際的檔名

你可以先查看目錄：

```bash
ls -l /home/justin/.cloudflared
```

通常 tunnel 憑證檔會是 UUID，例如：

```text
12345678-1234-1234-1234-123456789abc.json
```

如果是這種情況，請在 [cloudflared/config.yml](cloudflared/config.yml) 中使用實際的 UUID 檔名。

### 4. 可選：加入 Cloudflare Access 進行邊緣層驗證

建議把 `docling.itr-lab.cloud` 設定成 Cloudflare Access 的 self-hosted application。

這樣可以在 Cloudflare 邊緣多一層保護，例如：

1. 只允許特定 email 網域的使用者
2. 只允許帶有 Service Token 的請求
3. 只允許特定來源 IP 的請求

同時仍然保留應用層的 `API_KEYS` 驗證，這樣即使請求進到 origin，也還是需要 API key。

## API Keys

本地部署不再依賴 Wrangler secret，而是直接從環境變數讀取：

```dotenv
API_KEYS=team-a-key,team-b-key
```

你可以設定一個或多個 key，多個 key 以逗號分隔。

例如：

```text
team-a-key,team-b-key
```

客戶端可以使用：

```http
Authorization: Bearer <your-api-key>
```

或者：

```http
X-API-Key: <your-api-key>
```

## CORS

本地部署會從環境變數讀取 `CORS_ALLOW_ORIGIN`。

例如：

```dotenv
CORS_ALLOW_ORIGIN=https://app.itr-lab.cloud,https://admin.itr-lab.cloud
```

## 正式上線操作流程

以下流程適用於目前已經驗證可行的架構：本地 `Docling API` + `Nginx` + `Cloudflare Tunnel`。

### 1. 準備環境變數

確認 `.env` 至少包含：

```dotenv
API_KEYS=<你的正式 API Key>
GATEWAY_PORT=18080
HOST_INPUT_PREFIX=/absolute/path/to/your/project/input
CONTAINER_INPUT_DIR=/data/input
DOCLING_GPU_ENABLED=true
```

如果你使用的是本地設定 tunnel 模式，請確認 [cloudflared/config.yml](cloudflared/config.yml) 中這些值正確：

```yaml
tunnel: <你的 tunnel UUID>
origincert: /root/.cloudflared/cert.pem
credentials-file: /root/.cloudflared/<你的 tunnel UUID>.json
```

### 2. 啟動本地服務

CPU 模式：

```bash
docker compose -f docker-compose.local.yml up -d --build
```

GPU 模式：

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml up -d --build
```

### 3. 啟動 Cloudflare Tunnel

如果你使用本地 tunnel 設定：

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  up -d cloudflared
```

### 4. 本地驗證

確認本地 gateway 回應正常：

```bash
curl http://127.0.0.1:18080/health
```

預期結果：

```json
{"status":"ok"}
```

### 5. 公網驗證

在 tunnel 連上後，確認公網網域正常：

```bash
curl https://docling.itr-lab.cloud/health
```

預期結果：

```json
{"status":"ok"}
```

### 6. 對外開放前的最後檢查

1. `API_KEYS` 已改為正式等級的隨機密鑰
2. `docling.itr-lab.cloud` 已正確路由到 tunnel
3. 本地的 `8000` 與 gateway port 只綁定在 `127.0.0.1`
4. 若需要額外保護，已啟用 Cloudflare Access
5. 至少成功測試過一次真實 PDF 轉換請求

## 重啟命令

### 只重啟 Docling API 與 Gateway

CPU 模式：

```bash
docker compose -f docker-compose.local.yml restart docling-api gateway
```

GPU 模式：

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml restart docling-api gateway
```

### 只重啟 Cloudflare Tunnel

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  restart cloudflared
```

### 重新建置並啟動整套服務

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  up -d --build
```

### 查看執行狀態

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  ps
```

### 查看日誌

Docling API：

```bash
docker compose -f docker-compose.local.yml -f docker-compose.gpu.yml logs -f docling-api
```

Gateway：

```bash
docker compose -f docker-compose.local.yml logs -f gateway
```

Tunnel：

```bash
docker compose \
  -f docker-compose.local.yml \
  -f docker-compose.gpu.yml \
  -f docker-compose.tunnel-local.yml \
  logs -f cloudflared
```

## 外部呼叫範例

以下範例適合直接提供給第三方呼叫端。

### curl：傳入 PDF URL

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-api-key>" \
  -d '{
    "source_url": "https://arxiv.org/pdf/2408.09869"
  }'
```

### curl：上傳本地 PDF

```bash
curl -fsS -X POST "https://docling.itr-lab.cloud/v1/convert" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./paper.pdf" \
  -o /tmp/paper_response.json

jq -er '.markdown' /tmp/paper_response.json > paper.md
```

### curl：直接下載 ZIP 檔案

```bash
curl -X POST "https://docling.itr-lab.cloud/v1/convert?response_format=zip" \
  -H "Authorization: Bearer <your-api-key>" \
  -F "file=@./paper.pdf" \
  -o paper.zip
```

### Python：傳入 PDF URL

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

### Python：上傳本地 PDF

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

### Python：將 Markdown 儲存成檔案

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

## 生產建議

### 1. 不要開放伺服器入站埠

`cloudflared` 使用的是出站連線模式。你的伺服器不需要直接對公網開放 `8000` 或 `8080`。

### 2. 同時使用 Cloudflare Access 與 API Keys

同時使用邊緣層與應用層驗證，會比只依賴單一機制更安全。

### 3. 大檔案優先傳 URL，不要優先直接上傳

如果 PDF 很大，建議先上傳到 R2 或其他物件儲存，再把可存取的 URL 傳給 `/v1/convert`。這會比透過 Worker 或 tunnel 邊緣路徑傳大檔更穩定。

### 4. 流量成長後改成非同步處理

如果之後併發量提高，建議改成：

1. API 接收請求
2. 檔案存到物件儲存
3. 任務寫入佇列
4. 後端 worker 非同步處理轉換
5. 結果寫回 R2 或 D1

目前版本刻意保持為最小可用的同步 API，先以跑通部署為主。

## 關鍵檔案

- `container/app/main.py`：FastAPI + Docling 轉換邏輯
- `Dockerfile`：本地 Docling 服務映像檔
- `Dockerfile.gpu`：啟用 GPU 的 Docling 服務映像檔
- `docker-compose.local.yml`：本地 API、Nginx，以及 token 模式 `cloudflared` profile 的編排
- `docker-compose.gpu.yml`：Docling API 容器的 GPU override 設定
- `deploy/nginx/default.conf`：本地反向代理設定
- `cloudflared/config.yml.example`：命名 tunnel 的設定範例
- `.env.example`：本地執行所需的環境變數範本

## 已知限制

1. 第一次冷啟動與初次下載模型會比後續請求慢
2. 目前回傳只有 Markdown，尚未提供更豐富的結構化 JSON 輸出
3. 目前設計是單機同步處理，適合先將服務跑起來，但不適合高併發、多租戶的正式生產場景
