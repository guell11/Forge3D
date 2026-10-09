# Forge3D MCP bridge

Forge3D provides an optional MCP server over STDIO. The bridge runs beside Codex or OpenCode and calls the existing Forge3D REST API. The API remains responsible for validation, job state, operations, and the single serial GPU queue.

```text
Codex or OpenCode --STDIO--> Forge3D MCP bridge --HTTP(S)--> Forge3D REST API --> serial GPU queue
```

The bridge supports these tools:

| Tool | Action |
| --- | --- |
| `describe_api` | Read the API manifest, routes, request schemas, and published limits. |
| `capabilities` | Read pipeline, upload, and operation capabilities from the API. |
| `upload_image` | Upload a caller-provided local PNG, JPEG, WEBP, or BMP file. |
| `generate_model` | Validate a `CreateJobRequest` and queue generation. |
| `list_jobs` | List compact job summaries (20 by default) with API pagination and filters. |
| `get_job` | Read one full job record, including options, events, logs, and artifacts. |
| `wait_job` | Wait up to 25 seconds for terminal state; a timeout does not cancel the job. |
| `cancel_job` | Request cancellation through the existing queue. |
| `create_operation` | Validate an `OperationRequest` and queue an operation. |
| `download_model` | Stream a completed primary output to an explicit local path, up to 1 GiB, without overwriting a file. |
| `download_artifact` | Download a filename registered in `job.artifacts` to a local path without overwriting a file. |

No generator or GPU worker runs in the MCP process. `generate_model` and `create_operation` only submit requests to the API. `upload_image` rejects URLs and checks the local file's extension, signature, and size before upload. `download_model` requires a local destination path and removes partial files after a failed transfer. See the repository's [agent workflow guide](../AGENTS.md) for capability checks, retries, operations, and local-versus-remote storage behavior.

## Install

Run these commands from the repository's `backend` directory. The MCP dependency stays separate from the normal API requirements:

```powershell
python -m venv .venv-mcp
.venv-mcp\Scripts\python.exe -m pip install -r requirements-mcp.txt
```

On Linux or macOS, use `.venv-mcp/bin/python` in place of `.venv-mcp\Scripts\python.exe`.

Start Forge3D through the normal launcher or API setup. The default bridge URL is `http://127.0.0.1:8000`.

## Local API

Use the supplied [Codex TOML example](examples/codex-config.toml) or [OpenCode JSON example](examples/opencode.json). Replace `C:/path/to/open3d` with the absolute path to this checkout. Both configurations launch a local process with STDIO; Forge3D's HTTP URL is an API target, not an MCP endpoint.

Codex reads MCP settings from `~/.codex/config.toml`. A trusted project can also use `.codex/config.toml`. The desktop app, CLI, and IDE extension share that Codex configuration. Restart the client after changing it.

OpenCode reads `opencode.json` from project or global configuration. Its local MCP configuration uses `type: "local"`, a command array, and an optional `environment` object.

## Remote API

The same local STDIO bridge can target a remote Forge3D API such as the HTTPS ngrok origin from the [Kaggle T4 setup](KAGGLE.md). Set `FORGE3D_API_URL` to the origin only, without `/api`, query, or fragment. The bridge appends `/api/...` to this value; adding `/api` produces `/api/api/...` and returns 404. Set `FORGE3D_API_TOKEN` to the same raw value as the service's `FORGE3D_ACCESS_TOKEN`, without a `Bearer ` prefix. The [ASGI gateway in `scripts/serve_remote.py`](../scripts/serve_remote.py) checks that bearer on API and asset requests; the Kaggle notebook starts the service through this gateway. The bridge requires HTTPS and a nonempty token for non-loopback hosts, sends `Authorization: Bearer <token>`, adds `ngrok-skip-browser-warning: 1`, and refuses redirects so the bearer token never follows a redirect to another host.

The normal REST app does not validate bearer tokens itself. If it runs without the gateway or another trusted proxy, the bridge token alone does not protect it; keep that API private. The ngrok warning header skips a browser interstitial and is not authentication. Remote image uploads, job data, and downloads travel over the network and may be stored on the API host.

Use the [remote OpenCode example](examples/opencode-remote.json) as a starting point. For Codex, keep the local STDIO command from the TOML example and export both environment variables before starting the Codex process. Do not configure the Forge3D REST URL as a remote MCP URL: that URL speaks Forge3D REST, not MCP.

Set `FORGE3D_API_URL` in the MCP client's environment to the HTTPS origin. Load `FORGE3D_API_TOKEN` from a local secret manager or protected environment configuration; use the same raw value configured on the Forge3D service. Do not put the token into `FORGE3D_API_URL` or a checked-in config file.

```powershell
$env:FORGE3D_API_URL = "https://<ngrok-host>"
```

The bridge defaults to loopback if `FORGE3D_API_URL` is unset.

## Validation

The MCP test suite mocks REST responses and starts a real STDIO subprocess to complete `initialize` and `tools/list`; it does not run a generator or need a GPU:

```powershell
python -m pip install -r requirements-mcp.txt -r requirements-dev.txt
python -m pytest tests/test_mcp.py
```

## References

- [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/)
- [Official Python SDK, v1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
