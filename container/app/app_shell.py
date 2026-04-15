APP_SCRIPT = r"""
const state = {
  downloadUrl: "",
  downloadName: "",
  lastBlob: null,
};

const form = document.querySelector("#convert-form");
const modeRadios = Array.from(document.querySelectorAll('input[name="source-mode"]'));
const uploadPanel = document.querySelector("#upload-panel");
const urlPanel = document.querySelector("#url-panel");
const fileInput = document.querySelector("#pdf-file");
const urlInput = document.querySelector("#source-url");
const outputSelect = document.querySelector("#output-format");
const authInput = document.querySelector("#api-key");
const authHint = document.querySelector("#auth-hint");
const submitButton = document.querySelector("#submit-button");
const statusBox = document.querySelector("#status-box");
const statusTitle = document.querySelector("#status-title");
const statusBody = document.querySelector("#status-body");
const resultPanel = document.querySelector("#result-panel");
const resultName = document.querySelector("#result-name");
const resultMeta = document.querySelector("#result-meta");
const downloadButton = document.querySelector("#download-button");
const previewPanel = document.querySelector("#preview-panel");
const previewText = document.querySelector("#preview-text");

function getSourceMode() {
  return modeRadios.find((radio) => radio.checked)?.value || "upload";
}

function setBusy(isBusy) {
  submitButton.disabled = isBusy;
  submitButton.textContent = isBusy ? "Converting..." : "Convert Document";
  form.classList.toggle("is-busy", isBusy);
}

function setStatus(kind, title, body) {
  statusBox.dataset.state = kind;
  statusTitle.textContent = title;
  statusBody.textContent = body;
}

function clearResult() {
  if (state.downloadUrl) {
    URL.revokeObjectURL(state.downloadUrl);
  }

  state.downloadUrl = "";
  state.downloadName = "";
  state.lastBlob = null;
  resultPanel.hidden = true;
  previewPanel.hidden = true;
  previewText.textContent = "";
}

function showActivePanel() {
  const sourceMode = getSourceMode();
  const isUpload = sourceMode === "upload";

  uploadPanel.hidden = !isUpload;
  urlPanel.hidden = isUpload;
  fileInput.disabled = !isUpload;
  urlInput.disabled = isUpload;
}

function normalizeMarkdownFilename(filename) {
  if (!filename) {
    return "document.md";
  }

  if (filename.toLowerCase().endsWith(".pdf")) {
    return filename.slice(0, -4) + ".md";
  }

  if (filename.toLowerCase().endsWith(".md")) {
    return filename;
  }

  return filename + ".md";
}

function parseContentDisposition(value) {
  if (!value) {
    return "";
  }

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1]);
  }

  const plainMatch = value.match(/filename="?([^";]+)"?/i);
  return plainMatch ? plainMatch[1] : "";
}

function triggerDownload(blob, filename) {
  if (state.downloadUrl) {
    URL.revokeObjectURL(state.downloadUrl);
  }

  state.lastBlob = blob;
  state.downloadName = filename;
  state.downloadUrl = URL.createObjectURL(blob);
  downloadButton.hidden = false;

  const anchor = document.createElement("a");
  anchor.href = state.downloadUrl;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}

function formatBytes(byteLength) {
  if (!Number.isFinite(byteLength) || byteLength <= 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB"];
  let value = byteLength;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  return value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1) + " " + units[unitIndex];
}

function renderSuccess(details) {
  resultPanel.hidden = false;
  resultName.textContent = details.filename;
  resultMeta.textContent = details.meta;

  if (details.preview) {
    previewPanel.hidden = false;
    previewText.textContent = details.preview;
  } else {
    previewPanel.hidden = true;
    previewText.textContent = "";
  }
}

function getAuthHeaders() {
  const apiKey = authInput.value.trim();
  if (!apiKey) {
    return {};
  }

  localStorage.setItem("docling-api-key", apiKey);
  return {
    Authorization: "Bearer " + apiKey,
  };
}

function getRequestConfig() {
  const sourceMode = getSourceMode();
  const outputFormat = outputSelect.value;
  const isZip = outputFormat === "zip";
  const authHeaders = getAuthHeaders();

  if (sourceMode === "upload") {
    const file = fileInput.files?.[0];

    if (!file) {
      throw new Error("Choose a PDF file before submitting.");
    }

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      throw new Error("The selected file must be a PDF.");
    }

    const body = new FormData();
    body.append("file", file);

    return {
      outputFormat,
      sourceLabel: file.name,
      fetchUrl: isZip ? "/v1/convert?response_format=zip" : "/v1/convert",
      fetchOptions: {
        method: "POST",
        headers: authHeaders,
        body,
      },
    };
  }

  const sourceUrl = urlInput.value.trim();

  if (!sourceUrl) {
    throw new Error("Enter a PDF URL before submitting.");
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(sourceUrl);
  } catch {
    throw new Error("The PDF URL is not valid.");
  }

  if (!["http:", "https:"].includes(parsedUrl.protocol)) {
    throw new Error("The PDF URL must start with http:// or https://.");
  }

  const payload = { source_url: sourceUrl };
  if (isZip) {
    payload.response_format = "zip";
  }

  return {
    outputFormat,
    sourceLabel: sourceUrl,
    fetchUrl: "/v1/convert",
    fetchOptions: {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
      },
      body: JSON.stringify(payload),
    },
  };
}

async function readError(response) {
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    try {
      const data = await response.json();
      return data.detail || data.error || JSON.stringify(data);
    } catch {
      return "The server returned an unreadable JSON error.";
    }
  }

  const text = await response.text();
  return text || "The server returned an empty error response.";
}

async function handleSubmit(event) {
  event.preventDefault();
  clearResult();

  let requestConfig;
  try {
    requestConfig = getRequestConfig();
  } catch (error) {
    setStatus("error", "Check the form", error.message);
    return;
  }

  setBusy(true);
  setStatus(
    "working",
    "Converting document",
    "Uploading the request and waiting for Docling. Large PDFs and first-run model downloads can take a few minutes."
  );

  try {
    const response = await fetch(requestConfig.fetchUrl, requestConfig.fetchOptions);

    if (!response.ok) {
      const errorDetail = await readError(response);
      throw new Error(errorDetail);
    }

    if (requestConfig.outputFormat === "zip") {
      const blob = await response.blob();
      const serverFilename = parseContentDisposition(response.headers.get("content-disposition"));
      const fallbackBase = requestConfig.sourceLabel.split("/").pop() || "document";
      const fallbackName = fallbackBase.toLowerCase().endsWith(".pdf")
        ? fallbackBase.slice(0, -4) + ".zip"
        : fallbackBase + ".zip";
      const filename = serverFilename || fallbackName;

      triggerDownload(blob, filename);
      setStatus("success", "ZIP ready", "The archive was generated and downloaded.");
      renderSuccess({
        filename,
        meta: formatBytes(blob.size) + " archive",
        preview: "",
      });
      return;
    }

    const data = await response.json();
    if (typeof data.markdown !== "string") {
      throw new Error("The server response did not include markdown text.");
    }

    const filename = normalizeMarkdownFilename(data.filename);
    const blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
    triggerDownload(blob, filename);

    setStatus("success", "Markdown ready", "The Markdown file was generated and downloaded.");
    renderSuccess({
      filename,
      meta: formatBytes(blob.size) + " Markdown with embedded images when available",
      preview: data.markdown.slice(0, 1400),
    });
  } catch (error) {
    setStatus(
      "error",
      "Conversion failed",
      error instanceof Error ? error.message : String(error)
    );
  } finally {
    setBusy(false);
  }
}

downloadButton.addEventListener("click", () => {
  if (!state.downloadUrl || !state.downloadName) {
    return;
  }

  const anchor = document.createElement("a");
  anchor.href = state.downloadUrl;
  anchor.download = state.downloadName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
});

modeRadios.forEach((radio) => {
  radio.addEventListener("change", () => {
    showActivePanel();
    clearResult();
    setStatus("idle", "Ready", "Choose a PDF upload or paste a PDF URL, then select Markdown or ZIP output.");
  });
});

authInput.addEventListener("input", () => {
  if (authInput.value.trim()) {
    authHint.textContent = "The API key will be sent as an Authorization bearer token.";
  } else {
    localStorage.removeItem("docling-api-key");
    authHint.textContent = authInput.dataset.emptyHint;
  }
});

const storedApiKey = localStorage.getItem("docling-api-key");
if (storedApiKey) {
  authInput.value = storedApiKey;
  authHint.textContent = "Using the saved API key from this browser.";
}

form.addEventListener("submit", handleSubmit);
showActivePanel();
setStatus("idle", "Ready", "Choose a PDF upload or paste a PDF URL, then select Markdown or ZIP output.");
"""


def render_auth_notice(auth_enabled: bool) -> str:
    if not auth_enabled:
        return """
      <div class=\"notice notice-open\">
        <strong>Open mode.</strong>
        <span>This deployment currently accepts same-origin requests without an API key.</span>
      </div>
    """

    return """
      <div class=\"notice notice-auth\">
        <strong>API key required.</strong>
        <span>Paste a valid API key below. The browser will send it as a Bearer token to the same-origin API.</span>
      </div>
    """


HTML_TEMPLATE = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Docling Convert Studio</title>
    <meta
      name=\"description\"
      content=\"Upload a PDF or submit a PDF URL, then download Markdown with embedded base64 images or a ZIP package.\"
    />
    <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
    <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
    <link
      href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Noto+Sans+TC:wght@400;500;700&display=swap\"
      rel=\"stylesheet\"
    />
    <style>
      :root {
        color-scheme: light;
        --bg: #f3efe5;
        --ink: #10212b;
        --muted: #52616b;
        --panel: rgba(255, 252, 246, 0.88);
        --panel-strong: rgba(255, 250, 241, 0.96);
        --line: rgba(16, 33, 43, 0.12);
        --accent: #c84b31;
        --accent-deep: #8d2d1c;
        --success: #1b7f5a;
        --shadow: 0 24px 80px rgba(54, 35, 18, 0.18);
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        font-family: \"Space Grotesk\", \"Noto Sans TC\", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(200, 75, 49, 0.24), transparent 32%),
          radial-gradient(circle at 90% 10%, rgba(16, 33, 43, 0.18), transparent 22%),
          linear-gradient(180deg, #f7f1e4 0%, #ece4d1 100%);
        min-height: 100vh;
      }

      main {
        width: min(1160px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 48px 0 64px;
      }

      .hero {
        display: grid;
        grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
        gap: 24px;
        align-items: stretch;
      }

      .hero-copy,
      .hero-panel,
      .status,
      .result,
      .preview {
        background: var(--panel);
        backdrop-filter: blur(18px);
        border: 1px solid var(--line);
        border-radius: 28px;
        box-shadow: var(--shadow);
      }

      .hero-copy {
        padding: 34px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }

      .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        width: fit-content;
        padding: 8px 14px;
        border-radius: 999px;
        background: rgba(16, 33, 43, 0.06);
        color: var(--muted);
        font-size: 13px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      h1 {
        margin: 18px 0 14px;
        font-size: clamp(2.3rem, 4vw, 4.8rem);
        line-height: 0.95;
        letter-spacing: -0.05em;
      }

      .hero-copy p {
        margin: 0;
        font-size: 1.05rem;
        line-height: 1.75;
        color: var(--muted);
        max-width: 58ch;
      }

      .hero-grid {
        margin-top: 26px;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
      }

      .fact {
        padding: 16px;
        border-radius: 20px;
        background: var(--panel-strong);
        border: 1px solid var(--line);
      }

      .fact strong {
        display: block;
        margin-bottom: 6px;
        font-size: 1.15rem;
      }

      .fact span {
        color: var(--muted);
        font-size: 0.92rem;
        line-height: 1.6;
      }

      .hero-panel { padding: 28px; }

      .notice {
        display: grid;
        gap: 4px;
        padding: 14px 16px;
        border-radius: 18px;
        margin-bottom: 18px;
        border: 1px solid transparent;
        font-size: 0.94rem;
        line-height: 1.6;
      }

      .notice-open {
        background: rgba(27, 127, 90, 0.09);
        border-color: rgba(27, 127, 90, 0.18);
      }

      .notice-auth {
        background: rgba(160, 35, 52, 0.1);
        border-color: rgba(160, 35, 52, 0.2);
      }

      form { display: grid; gap: 18px; }

      .segmented {
        display: inline-grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        padding: 6px;
        border-radius: 20px;
        background: rgba(16, 33, 43, 0.06);
      }

      .segmented label {
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 16px;
        cursor: pointer;
        font-weight: 500;
      }

      .segmented input {
        position: absolute;
        opacity: 0;
        pointer-events: none;
      }

      .segmented input:checked + span {
        background: var(--panel-strong);
        color: var(--ink);
        box-shadow: inset 0 0 0 1px rgba(16, 33, 43, 0.08), 0 12px 30px rgba(16, 33, 43, 0.08);
      }

      .segmented span {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        padding: 14px 16px;
        border-radius: 16px;
        color: var(--muted);
        transition: 160ms ease;
      }

      .field {
        display: grid;
        gap: 10px;
      }

      .field label,
      .group-title {
        font-weight: 700;
        font-size: 0.95rem;
      }

      .field-note {
        color: var(--muted);
        font-size: 0.88rem;
        line-height: 1.6;
      }

      input[type=\"url\"],
      input[type=\"password\"],
      select,
      input[type=\"file\"] {
        width: 100%;
        padding: 15px 16px;
        border-radius: 18px;
        border: 1px solid rgba(16, 33, 43, 0.12);
        background: rgba(255, 255, 255, 0.82);
        font: inherit;
        color: var(--ink);
      }

      input[type=\"file\"] { padding: 12px 14px; }

      .button-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        flex-wrap: wrap;
      }

      button { border: 0; font: inherit; }

      .primary-button,
      .secondary-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 15px 20px;
        border-radius: 18px;
        font-weight: 700;
        cursor: pointer;
      }

      .primary-button {
        min-width: 220px;
        color: white;
        background: linear-gradient(135deg, var(--accent) 0%, var(--accent-deep) 100%);
        box-shadow: 0 16px 34px rgba(141, 45, 28, 0.28);
      }

      .secondary-button {
        background: rgba(16, 33, 43, 0.08);
        color: var(--ink);
      }

      .helper-chip {
        padding: 10px 12px;
        border-radius: 999px;
        background: rgba(16, 33, 43, 0.06);
        color: var(--muted);
        font-size: 0.85rem;
      }

      .status, .result, .preview {
        margin-top: 20px;
        padding: 22px 24px;
      }

      .status[data-state=\"working\"] {
        border-color: rgba(145, 95, 0, 0.2);
        background: rgba(255, 248, 233, 0.94);
      }

      .status[data-state=\"success\"] {
        border-color: rgba(27, 127, 90, 0.18);
        background: rgba(242, 255, 250, 0.92);
      }

      .status[data-state=\"error\"] {
        border-color: rgba(160, 35, 52, 0.18);
        background: rgba(255, 242, 245, 0.94);
      }

      .status h2, .result h2, .preview h2 {
        margin: 0 0 8px;
        font-size: 1rem;
      }

      .status p, .result p, .preview p, .preview pre {
        margin: 0;
        color: var(--muted);
        line-height: 1.7;
      }

      .result-header {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: center;
        flex-wrap: wrap;
      }

      .result-header strong {
        display: block;
        margin-bottom: 4px;
        font-size: 1.08rem;
      }

      .preview pre {
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 280px;
        overflow: auto;
        padding-top: 8px;
      }

      @media (max-width: 940px) {
        .hero, .hero-grid { grid-template-columns: 1fr; }
      }

      @media (max-width: 640px) {
        main {
          width: min(100vw - 20px, 100%);
          padding-top: 18px;
        }

        .hero-copy, .hero-panel, .status, .result, .preview {
          border-radius: 24px;
          padding-left: 18px;
          padding-right: 18px;
        }

        h1 { font-size: 2.4rem; }
        .button-row { align-items: stretch; }
        .primary-button, .secondary-button { width: 100%; }
      }
    </style>
  </head>
  <body>
    <main>
      <section class=\"hero\">
        <div class=\"hero-copy\">
          <div>
            <div class=\"eyebrow\">Docling Convert Studio</div>
            <h1>From PDF to clean Markdown or ZIP, behind your own tunnel.</h1>
            <p>
              Upload a PDF or submit a PDF URL, then download either a Markdown file with embedded base64 images
              or a ZIP package with extracted images. This page is served directly by the local FastAPI service behind
              Nginx and Cloudflare Tunnel.
            </p>
          </div>
          <div class=\"hero-grid\">
            <div class=\"fact\">
              <strong>Two inputs</strong>
              <span>Upload a local PDF or paste a remote PDF URL.</span>
            </div>
            <div class=\"fact\">
              <strong>Two outputs</strong>
              <span>Download <code>.md</code> with embedded images or a <code>.zip</code> package.</span>
            </div>
            <div class=\"fact\">
              <strong>Same origin</strong>
              <span>The page and <code>/v1/convert</code> are served by the same local stack.</span>
            </div>
          </div>
        </div>

        <div class=\"hero-panel\">
          __AUTH_NOTICE__
          <form id=\"convert-form\" novalidate>
            <div class=\"field\">
              <label for=\"api-key\">API key</label>
              <input id=\"api-key\" name=\"api-key\" type=\"password\" placeholder=\"Optional when API_KEYS is empty\" data-empty-hint=\"Leave this empty only if the deployment runs with API_KEYS unset.\" />
              <div class=\"field-note\" id=\"auth-hint\">Leave this empty only if the deployment runs with API_KEYS unset.</div>
            </div>

            <div class=\"field\">
              <span class=\"group-title\">Input source</span>
              <div class=\"segmented\" role=\"radiogroup\" aria-label=\"Input source mode\">
                <label>
                  <input type=\"radio\" name=\"source-mode\" value=\"upload\" checked />
                  <span>Upload PDF</span>
                </label>
                <label>
                  <input type=\"radio\" name=\"source-mode\" value=\"url\" />
                  <span>Paste URL</span>
                </label>
              </div>
            </div>

            <div class=\"field\" id=\"upload-panel\">
              <label for=\"pdf-file\">PDF file</label>
              <input id=\"pdf-file\" name=\"file\" type=\"file\" accept=\"application/pdf,.pdf\" />
              <div class=\"field-note\">Uploads follow the current gateway limits. Large files can take several minutes to finish.</div>
            </div>

            <div class=\"field\" id=\"url-panel\" hidden>
              <label for=\"source-url\">PDF URL</label>
              <input id=\"source-url\" name=\"source-url\" type=\"url\" placeholder=\"https://example.com/paper.pdf\" />
              <div class=\"field-note\">Use a direct, publicly reachable PDF URL. The backend will fetch and convert it server-side.</div>
            </div>

            <div class=\"field\">
              <label for=\"output-format\">Download format</label>
              <select id=\"output-format\" name=\"output-format\">
                <option value=\"md\">Markdown with embedded base64 images</option>
                <option value=\"zip\">ZIP package with extracted images</option>
              </select>
            </div>

            <div class=\"button-row\">
              <button class=\"primary-button\" id=\"submit-button\" type=\"submit\">Convert Document</button>
              <div class=\"helper-chip\">Tunnel-friendly same-origin UI</div>
            </div>
          </form>
        </div>
      </section>

      <section class=\"status\" id=\"status-box\" data-state=\"idle\" aria-live=\"polite\">
        <h2 id=\"status-title\"></h2>
        <p id=\"status-body\"></p>
      </section>

      <section class=\"result\" id=\"result-panel\" hidden>
        <div class=\"result-header\">
          <div>
            <h2>Latest result</h2>
            <strong id=\"result-name\"></strong>
            <p id=\"result-meta\"></p>
          </div>
          <button class=\"secondary-button\" id=\"download-button\" type=\"button\" hidden>Download again</button>
        </div>
      </section>

      <section class=\"preview\" id=\"preview-panel\" hidden>
        <h2>Markdown preview</h2>
        <pre id=\"preview-text\"></pre>
      </section>
    </main>
    <script>__APP_SCRIPT__</script>
  </body>
</html>
"""


def render_app_html(auth_enabled: bool) -> str:
    return (
        HTML_TEMPLATE
        .replace("__AUTH_NOTICE__", render_auth_notice(auth_enabled))
        .replace("__APP_SCRIPT__", APP_SCRIPT)
    )
