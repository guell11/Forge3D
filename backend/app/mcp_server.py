from __future__ import annotations

import ipaddress
import logging
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from .schemas import CreateJobRequest, GenerationOptions, OPERATION_KINDS, OperationRequest

_JOB_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_UPLOAD_BYTES = 512 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_ALLOWED_OPERATION_KINDS = {kind.value for kind in OPERATION_KINDS}
_IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
_SERVER_INSTRUCTIONS = (
    "Forge3D tools call the configured REST API. Generation and operations are queued by Forge3D; "
    "never claim a model exists until get_job or wait_job reports completion. Do not automatically retry a "
    "mutating POST after an ambiguous timeout; inspect current API/job state first. Uploads read only the caller-provided "
    "local image path. Downloads write only to the caller-provided path and refuse overwrite. Use describe_api "
    "for the API contract and capabilities for current availability. Tool annotations describe side effects; "
    "they are not authorization to perform an action."
)


class Forge3DError(RuntimeError):
    """A safe, user-facing error from configuration, HTTP, or local file handling."""


class Forge3DApi:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        raw_url = (base_url if base_url is not None else os.getenv("FORGE3D_API_URL", "http://127.0.0.1:8000")).strip()
        raw_token = (token if token is not None else os.getenv("FORGE3D_API_TOKEN", "")).strip()
        if not raw_url or any(character.isspace() for character in raw_url):
            raise Forge3DError("FORGE3D_API_URL must be a valid absolute HTTP(S) URL.")

        try:
            parsed = urlsplit(raw_url)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise Forge3DError("FORGE3D_API_URL must be a valid absolute HTTP(S) URL.") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise Forge3DError("FORGE3D_API_URL must be an absolute HTTP(S) URL without credentials, query, or fragment.")

        self.is_loopback = self._is_loopback(hostname)
        if parsed.scheme.lower() != "https" and not self.is_loopback:
            raise Forge3DError("FORGE3D_API_URL must use HTTPS unless it points to a loopback address.")
        if not self.is_loopback and not raw_token:
            raise Forge3DError(
                "FORGE3D_API_TOKEN is required for a remote API. Configure the API or trusted proxy to validate this bearer token."
            )
        if "\r" in raw_token or "\n" in raw_token or raw_token.lower().startswith("bearer "):
            raise Forge3DError("Set FORGE3D_API_TOKEN to the raw token value, without a Bearer prefix.")

        path = parsed.path.rstrip("/")
        self.base_url = f"{parsed.scheme.lower()}://{parsed.netloc}{path}"
        self.transport = transport
        self.headers = {"Accept": "application/json"}
        if raw_token:
            self.headers["Authorization"] = f"Bearer {raw_token}"
        if not self.is_loopback:
            self.headers["ngrok-skip-browser-warning"] = "1"

    @staticmethod
    def _is_loopback(hostname: str) -> bool:
        normalized = hostname.rstrip(".").lower()
        if normalized in {"localhost", "localhost.localdomain"}:
            return True
        try:
            return ipaddress.ip_address(normalized.split("%", 1)[0]).is_loopback
        except ValueError:
            return False

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers=self.headers,
            timeout=httpx.Timeout(connect=10, read=30, write=120, pool=10),
            follow_redirects=False,
            transport=self.transport,
        )

    @staticmethod
    def _check_response(response: httpx.Response) -> None:
        if 300 <= response.status_code < 400:
            raise Forge3DError(
                f"Forge3D API returned HTTP {response.status_code}; redirects are blocked so bearer credentials stay on the configured host."
            )
        if response.is_error:
            detail: Any = None
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = payload.get("detail")
                else:
                    detail = payload
            except ValueError:
                detail = response.text
            message = str(detail or response.reason_phrase).strip()[:1000]
            raise Forge3DError(f"Forge3D API returned HTTP {response.status_code}: {message}")

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise Forge3DError("Forge3D API returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise Forge3DError("Forge3D API returned an unexpected response shape.")
        return payload

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
        files: dict[str, tuple[str, Any, str]] | None = None,
    ) -> dict[str, Any]:
        try:
            with self._client() as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=payload,
                    files=files,
                )
        except httpx.TimeoutException as exc:
            raise Forge3DError("Forge3D API request timed out.") from exc
        except httpx.RequestError as exc:
            raise Forge3DError(f"Could not reach Forge3D API at {self.base_url}.") from exc
        self._check_response(response)
        return self._json_object(response)

    def download(self, path: str, destination: Path) -> int:
        if destination.exists():
            raise Forge3DError("Destination already exists; choose a new path.")

        created = False
        try:
            with self._client() as client:
                with client.stream("GET", f"{self.base_url}{path}") as response:
                    self._check_response(response)
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            announced_size = int(content_length)
                        except ValueError as exc:
                            raise Forge3DError("Forge3D API returned an invalid Content-Length.") from exc
                        if announced_size < 0 or announced_size > _MAX_DOWNLOAD_BYTES:
                            raise Forge3DError("Model download exceeds the 1 GiB limit.")

                    destination.parent.mkdir(parents=True, exist_ok=True)
                    total = 0
                    with destination.open("xb") as output:
                        created = True
                        for chunk in response.iter_bytes(_DOWNLOAD_CHUNK_BYTES):
                            total += len(chunk)
                            if total > _MAX_DOWNLOAD_BYTES:
                                raise Forge3DError("Model download exceeds the 1 GiB limit.")
                            output.write(chunk)
            return total
        except Forge3DError:
            if created:
                destination.unlink(missing_ok=True)
            raise
        except httpx.TimeoutException as exc:
            if created:
                destination.unlink(missing_ok=True)
            raise Forge3DError("Model download timed out.") from exc
        except httpx.RequestError as exc:
            if created:
                destination.unlink(missing_ok=True)
            raise Forge3DError(f"Could not download model from Forge3D API at {self.base_url}.") from exc
        except FileExistsError as exc:
            raise Forge3DError("Destination already exists; choose a new path.") from exc
        except OSError as exc:
            if created:
                destination.unlink(missing_ok=True)
            raise Forge3DError(f"Could not write model to {destination}.") from exc


def _api() -> Forge3DApi:
    return Forge3DApi()


def _job_id(value: str) -> str:
    if not _JOB_ID.fullmatch(value):
        raise Forge3DError("job_id must be a 32-character lowercase hexadecimal ID.")
    return value


def _upload_id(value: str) -> str:
    if not _JOB_ID.fullmatch(value):
        raise Forge3DError("upload_id must be a 32-character lowercase hexadecimal ID.")
    return value


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "status",
        "progress",
        "stage",
        "queue_position",
        "elapsed_seconds",
        "eta_seconds",
        "eta_confidence",
        "job_kind",
        "parent_job_id",
        "profile",
        "output_format",
        "output",
        "artifacts",
        "validation",
        "error",
        "warnings",
        "updated_at",
    )
    return {field: job[field] for field in fields if field in job}


def _local_image(path_value: str) -> tuple[Path, str, int]:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", path_value.strip()):
        raise Forge3DError("upload_image accepts a local file path, not a URL.")
    try:
        path = Path(path_value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise Forge3DError("Image path must point to a local file.")
        size = path.stat().st_size
        if size < 1 or size > _MAX_UPLOAD_BYTES:
            raise Forge3DError("Image file must be between 1 byte and 512 MiB.")
        with path.open("rb") as source:
            signature = source.read(12)
    except Forge3DError:
        raise
    except (OSError, ValueError) as exc:
        raise Forge3DError("Could not read the supplied local image path.") from exc

    suffix = path.suffix.lower()
    mime = _IMAGE_MIMES.get(suffix)
    if mime is None:
        raise Forge3DError("Supported image extensions: PNG, JPG, JPEG, WEBP, BMP.")
    signature_mime = _signature_mime(signature)
    if signature_mime != mime:
        raise Forge3DError("Image extension and file content do not match a supported image type.")
    return path, mime, size


def _signature_mime(signature: bytes) -> str | None:
    if signature.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if signature.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
        return "image/webp"
    if signature.startswith(b"BM"):
        return "image/bmp"
    return None


def capabilities() -> dict[str, Any]:
    """Return API, pipeline, upload-limit, and operation capabilities."""
    api = _api()
    return {
        "api": api.request_json("GET", "/api/capabilities"),
        "operations": api.request_json("GET", "/api/operations/capabilities"),
    }


def describe_api() -> dict[str, Any]:
    """Read the relative-route manifest and the API's live Pydantic request schemas."""
    return _api().request_json("GET", "/api/agent-manifest")


def upload_image(path: str) -> dict[str, Any]:
    """Upload a validated local PNG, JPEG, WEBP, or BMP image to Forge3D."""
    local_path, mime, size = _local_image(path)
    api = _api()
    capability = api.request_json("GET", "/api/capabilities")
    limits = capability.get("limits")
    max_upload_mb = limits.get("max_upload_mb") if isinstance(limits, dict) else None
    if not isinstance(max_upload_mb, int) or max_upload_mb < 1:
        raise Forge3DError("Forge3D API did not publish a valid max_upload_mb limit.")
    api_limit = max_upload_mb * 1024 * 1024
    if size > api_limit:
        raise Forge3DError(f"Image exceeds Forge3D API upload limit of {max_upload_mb} MiB.")

    try:
        with local_path.open("rb") as image_file:
            result = api.request_json(
                "POST",
                "/api/uploads",
                files={"file": (local_path.name, image_file, mime)},
            )
    except OSError as exc:
        raise Forge3DError("Could not read the supplied local image path.") from exc
    upload = result.get("upload")
    if not isinstance(upload, dict):
        raise Forge3DError("Forge3D API response did not contain upload metadata.")
    return upload


def generate_model(
    upload_id: str,
    options: dict[str, Any] | None = None,
    adapter: str = "auto",
    output_format: Literal["glb", "obj"] = "glb",
    prompt: str | None = None,
) -> dict[str, Any]:
    """Queue a model generation job using CreateJobRequest and GenerationOptions validation."""
    upload_id = _upload_id(upload_id)
    selected_options = options or {}
    if not isinstance(selected_options, dict):
        raise Forge3DError("options must be a JSON object.")
    unknown = set(selected_options) - set(GenerationOptions.model_fields)
    if unknown:
        raise Forge3DError(f"Unsupported generation option(s): {', '.join(sorted(map(str, unknown)))}")
    try:
        request = CreateJobRequest.model_validate(
            {
                "upload_id": upload_id,
                "adapter": adapter,
                "output_format": output_format,
                "prompt": prompt,
                "options": selected_options,
            }
        )
    except ValidationError as exc:
        raise Forge3DError(f"Invalid generation request: {exc.errors(include_url=False)}") from exc
    payload = request.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    result = _api().request_json("POST", "/api/jobs", payload=payload)
    job = result.get("job")
    if not isinstance(job, dict):
        raise Forge3DError("Forge3D API response did not contain job metadata.")
    return job


def list_jobs(
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
    status: list[Literal["queued", "running", "completed", "failed", "cancelled"]] | None = None,
    favorite: bool | None = None,
) -> dict[str, Any]:
    """List compact job summaries with API pagination and optional filters; use get_job for full details."""
    if limit < 1 or limit > 200 or offset < 0:
        raise Forge3DError("limit must be 1..200 and offset must be nonnegative.")
    if search is not None and len(search) > 200:
        raise Forge3DError("search must be 200 characters or fewer.")
    params: list[tuple[str, Any]] = [("limit", limit), ("offset", offset)]
    if search is not None:
        params.append(("search", search))
    if favorite is not None:
        params.append(("favorite", str(favorite).lower()))
    for value in status or []:
        params.append(("status", value))
    result = _api().request_json("GET", "/api/jobs", params=params)
    jobs = result.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        raise Forge3DError("Forge3D API response did not contain a valid job list.")
    result["jobs"] = [_job_summary(job) for job in jobs]
    return result


def get_job(job_id: str) -> dict[str, Any]:
    """Return the complete status and result record for one job."""
    result = _api().request_json("GET", f"/api/jobs/{_job_id(job_id)}")
    job = result.get("job")
    if not isinstance(job, dict):
        raise Forge3DError("Forge3D API response did not contain job metadata.")
    return job


def wait_job(job_id: str, timeout_seconds: float = 20) -> dict[str, Any]:
    """Wait up to 25 seconds; return compact state without cancelling the job on timeout."""
    job_id = _job_id(job_id)
    if not math.isfinite(timeout_seconds) or not 0 <= timeout_seconds <= 25:
        raise Forge3DError("timeout_seconds must be between 0 and 25.")
    result = _api().request_json(
        "GET",
        f"/api/jobs/{job_id}/wait",
        params=[("timeout_seconds", timeout_seconds)],
    )
    job = result.get("job")
    terminal = result.get("terminal")
    timed_out = result.get("timed_out")
    if not isinstance(job, dict) or type(terminal) is not bool or type(timed_out) is not bool:
        raise Forge3DError("Forge3D API returned an invalid wait response.")
    if terminal == timed_out:
        raise Forge3DError("Forge3D API returned inconsistent terminal and timeout flags.")
    status = job.get("status")
    is_terminal = status in {"completed", "failed", "cancelled"}
    if is_terminal != terminal:
        raise Forge3DError("Forge3D API returned an inconsistent job status in its wait response.")
    return {"job": _job_summary(job), "terminal": terminal, "timed_out": timed_out}


def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation of a queued or running job through the Forge3D queue."""
    result = _api().request_json("POST", f"/api/jobs/{_job_id(job_id)}/cancel")
    job = result.get("job")
    if not isinstance(job, dict):
        raise Forge3DError("Forge3D API response did not contain job metadata.")
    return job


def create_operation(
    job_id: str,
    kind: Literal["split", "simplify", "remesh", "retexture", "transform"],
    target_triangles: int | None = None,
    transform: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue a schema-validated operation on a completed model through Forge3D."""
    if kind not in _ALLOWED_OPERATION_KINDS:
        raise Forge3DError(f"kind must be one of: {', '.join(sorted(_ALLOWED_OPERATION_KINDS))}.")
    try:
        operation = OperationRequest.model_validate(
            {
                "kind": kind,
                "target_triangles": target_triangles,
                "transform": transform,
                "metadata": metadata,
            }
        )
    except ValidationError as exc:
        raise Forge3DError(f"Invalid operation request: {exc.errors(include_url=False)}") from exc
    payload = operation.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    result = _api().request_json("POST", f"/api/jobs/{_job_id(job_id)}/operations", payload=payload)
    job = result.get("job")
    if not isinstance(job, dict):
        raise Forge3DError("Forge3D API response did not contain job metadata.")
    return job


def download_model(job_id: str, destination: str) -> dict[str, Any]:
    """Stream a completed model to an explicit local path without overwriting files."""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", destination.strip()):
        raise Forge3DError("destination must be a local file path, not a URL.")
    try:
        destination_path = Path(destination).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise Forge3DError("destination must be a valid local file path.") from exc
    if destination_path.exists():
        raise Forge3DError("Destination already exists; choose a new path.")
    size = _api().download(f"/api/jobs/{_job_id(job_id)}/download", destination_path)
    return {"job_id": job_id, "path": str(destination_path), "size": size}


def download_artifact(job_id: str, filename: str, destination: str) -> dict[str, Any]:
    """Download a job-registered artifact through the API without trusting job-supplied URLs."""
    job_id = _job_id(job_id)
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or "\r" in filename
        or "\n" in filename
        or Path(filename).name != filename
    ):
        raise Forge3DError("filename must be one artifact filename, without a path.")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", destination.strip()):
        raise Forge3DError("destination must be a local file path, not a URL.")
    try:
        destination_path = Path(destination).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise Forge3DError("destination must be a valid local file path.") from exc
    if destination_path.exists():
        raise Forge3DError("Destination already exists; choose a new path.")

    route_filename = quote(filename, safe="")
    route = f"/api/jobs/{job_id}/artifacts/{route_filename}/download"
    size = _api().download(route, destination_path)
    return {"job_id": job_id, "filename": filename, "path": str(destination_path), "size": size}


def create_mcp_server() -> FastMCP:
    server = FastMCP("Forge3D", instructions=_SERVER_INSTRUCTIONS)
    tools = (
        (describe_api, ToolAnnotations(readOnlyHint=True, openWorldHint=True)),
        (capabilities, ToolAnnotations(readOnlyHint=True, openWorldHint=True)),
        (upload_image, ToolAnnotations(readOnlyHint=False, openWorldHint=True)),
        (generate_model, ToolAnnotations(readOnlyHint=False, openWorldHint=True)),
        (list_jobs, ToolAnnotations(readOnlyHint=True, openWorldHint=True)),
        (get_job, ToolAnnotations(readOnlyHint=True, openWorldHint=True)),
        (wait_job, ToolAnnotations(readOnlyHint=True, openWorldHint=True)),
        (cancel_job, ToolAnnotations(readOnlyHint=False, openWorldHint=True)),
        (create_operation, ToolAnnotations(readOnlyHint=False, openWorldHint=True)),
        (download_model, ToolAnnotations(readOnlyHint=False, openWorldHint=True)),
        (download_artifact, ToolAnnotations(readOnlyHint=False, openWorldHint=True)),
    )
    for tool, annotations in tools:
        server.tool(annotations=annotations)(tool)
    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
