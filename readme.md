# Forge3D

Forge3D is a local-first image-to-3D application with a React interface and a FastAPI backend. The backend stores uploads and job records, validates requests, and sends generation and model operations through one serial GPU queue.

![Forge3D interface](https://github.com/user-attachments/assets/b6b8da8f-8068-4902-aa2f-d436e7b66d51)

## What it does

- Accepts PNG, JPEG, WEBP, and BMP image uploads.
- Queues image-to-3D generation and model operations through the Forge3D API.
- Supports GLB and OBJ exports.
- Reports job state, progress, output metadata, and validation results.
- Provides a local asset gallery and a Three.js model viewer.
- Supports optional TRELLIS and UltraShape workers when installed and available.
- Supports FaithC as an opt-in geometry-only GLB artifact. FaithC is disabled by default, requires its own configured worker, and does not replace the main textured output.
- Offers an optional MCP STDIO bridge for Codex and OpenCode. The bridge calls the existing API; it does not execute GPU work itself.

Available generation features depend on the selected profile, installed workers, and hardware. The diagnostic demo adapter is not an automatic replacement for an unavailable generation worker.

## Run

Use the setup instructions for your operating system in [Installation](docs/INSTALLATION.md). The application includes launcher scripts for configured environments; model weights and external workers are managed separately from the API package.

## MCP clients

Install and configure the optional bridge using [MCP setup](docs/MCP.md). A local API uses loopback HTTP. A remote API requires HTTPS and a bearer token forwarded to an API gateway or reverse proxy that validates it. Forge3D's REST API does not currently validate bearer tokens itself.

## Data and network use

In a local setup, uploads, job records, and generated files are stored by the local Forge3D API. If a client connects to a remote API or tunnel, images, job data, and downloads travel over that network connection and may be stored on the remote API host. The application does not promise end-to-end privacy or provide built-in remote API authentication.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [Manual](docs/MANUAL.md)
- [Research and limitations](docs/RESEARCH.md)
- [MCP bridge and client configuration](docs/MCP.md)
- [Backend API notes](backend/README.md)
