from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .profiles import ProfileId

try:
    from dotenv import load_dotenv
except ImportError:  # Keeps direct source inspection possible before dependencies are installed.
    load_dotenv = None


if load_dotenv is not None:
    # A real process environment always wins over the local convenience file.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _path_env(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


def _project_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def _profile_env() -> ProfileId:
    value = os.getenv("ENGINE_PROFILE", ProfileId.GB8.value).strip().lower()
    try:
        return ProfileId(value)
    except ValueError:
        return ProfileId.GB8


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration.

    External generators are deliberately opt-in. A configured path or URL
    means the local installer has provisioned that tool; it never means model
    weights are bundled by the API process itself.
    """

    app_name: str = "Forge3D Local API"
    app_version: str = "0.2.0"
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("LOCAL3D_DATA_DIR", Path(__file__).resolve().parents[1] / "data")
        ).resolve()
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip()
            for origin in os.getenv(
                "LOCAL3D_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
            ).split(",")
            if origin.strip()
        )
    )
    max_upload_mb: int = field(default_factory=lambda: _int_env("LOCAL3D_MAX_UPLOAD_MB", 25))
    active_profile: ProfileId = field(default_factory=_profile_env)
    # Demo is a diagnostic adapter only. Quality pipelines never silently
    # replace an unavailable real worker with a cube/model mock.
    demo_fallback: bool = field(default_factory=lambda: _bool_env("LOCAL3D_DEMO_FALLBACK", False))
    trellis_server_url: str | None = field(
        default_factory=lambda: os.getenv("TRELLIS_SERVER_URL", "").strip().rstrip("/") or None
    )
    trellis_server_timeout_seconds: int = field(
        default_factory=lambda: _int_env("TRELLIS_SERVER_TIMEOUT_SECONDS", 900)
    )
    trellis_cpp_command: str | None = field(
        default_factory=lambda: os.getenv("TRELLIS_CPP_COMMAND", "").strip() or None
    )
    trellis_command_timeout_seconds: int = field(
        default_factory=lambda: _int_env("TRELLIS_CPP_TIMEOUT_SECONDS", 900)
    )
    trellis_calibration_seconds: int | None = field(
        default_factory=lambda: max(0, _int_env("TRELLIS_CALIBRATION_SECONDS", 180)) or None
    )
    # Managed trellis-cli configuration. The installed runtime is discovered
    # from TRELLIS_SERVER_BIN when a dedicated CLI path is not supplied.
    trellis_cli_bin: Path | None = field(
        default_factory=lambda: _path_env("TRELLIS_CLI_BIN")
    )
    trellis_cli_models_dir: Path | None = field(
        default_factory=lambda: _path_env("TRELLIS_CLI_MODELS_DIR")
    )
    trellis_cli_gpu_index: int = field(
        default_factory=lambda: _int_env("TRELLIS_CLI_GPU_INDEX", 0)
    )
    trellis_cli_require_gpu: bool = field(
        default_factory=lambda: _bool_env("TRELLIS_CLI_REQUIRE_GPU", True)
    )
    # UltraShape is invoked only through our structured one-shot worker.  The
    # API never accepts an arbitrary command template for a GPU model process.
    # The installer records these paths after validating its isolated venv.
    ultrashape_home: Path | None = field(
        default_factory=lambda: _path_env("ULTRASHAPE_HOME")
    )
    ultrashape_python: Path | None = field(
        default_factory=lambda: _path_env("ULTRASHAPE_PYTHON")
    )
    ultrashape_checkpoint: Path | None = field(
        default_factory=lambda: _path_env("ULTRASHAPE_CKPT")
    )
    ultrashape_worker: Path | None = field(
        default_factory=lambda: _path_env("ULTRASHAPE_WORKER")
    )
    ultrashape_probe_path: Path | None = field(
        default_factory=lambda: _path_env("ULTRASHAPE_PROBE_PATH")
    )
    ultrashape_install_status: Path | None = field(
        default_factory=lambda: _path_env("ULTRASHAPE_INSTALL_STATUS")
    )
    ultrashape_enabled: bool = field(
        default_factory=lambda: _bool_env("ULTRASHAPE_ENABLED", True)
    )
    ultrashape_timeout_seconds: int = field(
        default_factory=lambda: _int_env("ULTRASHAPE_TIMEOUT_SECONDS", 900)
    )
    ultrashape_calibration_seconds: int | None = field(
        default_factory=lambda: max(0, _int_env("ULTRASHAPE_CALIBRATION_SECONDS", 0)) or None
    )
    # FaithC runs in a separate Python process because its Torch/CUDA extension
    # must match the environment used to build it. It is opt-in and has no
    # model checkpoint.
    faithc_enabled: bool = field(default_factory=lambda: _bool_env("FAITHC_ENABLED", False))
    faithc_python: Path | None = field(default_factory=lambda: _path_env("FAITHC_PYTHON"))
    faithc_worker: Path | None = field(default_factory=lambda: _path_env("FAITHC_WORKER"))
    faithc_timeout_seconds: int = field(default_factory=lambda: _int_env("FAITHC_TIMEOUT_SECONDS", 900))
    faithc_probe_timeout_seconds: int = field(default_factory=lambda: _int_env("FAITHC_PROBE_TIMEOUT_SECONDS", 90))
    # A TRELLIS CLI invocation exits after each job. A long-lived HTTP server
    # must expose a local release endpoint before the backend can honestly
    # start an UltraShape worker on the same GPU.
    trellis_release_url: str | None = field(
        default_factory=lambda: os.getenv("TRELLIS_RELEASE_URL", "").strip().rstrip("/") or None
    )
    trellis_managed_pid_file: Path | None = field(
        default_factory=lambda: _path_env("TRELLIS_MANAGED_PID_FILE") or _project_path("runtime", "trellis-server.pid.json")
    )
    trellis_release_script: Path | None = field(
        default_factory=lambda: _path_env("TRELLIS_RELEASE_SCRIPT") or _project_path("scripts", "release-trellis.ps1")
    )
    trellis_server_bin: Path | None = field(
        default_factory=lambda: _path_env("TRELLIS_SERVER_BIN")
    )
    trellis_models_dir: Path | None = field(
        default_factory=lambda: _path_env("TRELLIS_MODELS_DIR")
    )
    trellis_server_port: int = field(
        default_factory=lambda: _int_env("TRELLIS_SERVER_PORT", 8091)
    )
    trellis_default_resolution: int = field(
        default_factory=lambda: _int_env("TRELLIS_DEFAULT_RESOLUTION", 512)
    )
    trellis_default_atlas: int = field(
        default_factory=lambda: _int_env("TRELLIS_DEFAULT_ATLAS", 1024)
    )
    trellis_autostart: bool = field(
        default_factory=lambda: _bool_env("TRELLIS_AUTOSTART", True)
    )
    # Optional structured worker for mesh operations. These are paths, not an
    # arbitrary shell command: the child process receives only fixed flags.
    mesh_operations_python: Path | None = field(
        default_factory=lambda: _path_env("MESH_OPERATIONS_PYTHON")
    )
    mesh_operations_worker: Path | None = field(
        default_factory=lambda: _path_env("MESH_OPERATIONS_WORKER")
    )
    mesh_operations_timeout_seconds: int = field(
        default_factory=lambda: _int_env("MESH_OPERATIONS_TIMEOUT_SECONDS", 900)
    )
    engine_profile_path: Path | None = field(
        default_factory=lambda: _path_env("ENGINE_PROFILE_PATH")
    )
    official_trellis2_command: str | None = field(
        default_factory=lambda: os.getenv("TRELLIS2_OFFICIAL_COMMAND", "").strip() or None
    )

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def resolved_trellis_cli_bin(self) -> Path | None:
        if self.trellis_cli_bin:
            return self.trellis_cli_bin
        if self.trellis_server_bin:
            suffix = ".exe" if self.trellis_server_bin.suffix.lower() == ".exe" else ""
            return self.trellis_server_bin.parent / f"trellis-cli{suffix}"
        return None

    @property
    def resolved_trellis_cli_models_dir(self) -> Path | None:
        return self.trellis_cli_models_dir or self.trellis_models_dir

    def trellis_models_dir_for_variant(self, variant: str | None) -> Path | None:
        """Resolve an installer-recorded Q4/Q8 set without changing models per job.

        The browser may select a quality only when its own directory exists.
        A server launched with one models directory is never silently treated as
        if it had switched quantization for a different job.
        """

        base = self.resolved_trellis_cli_models_dir
        if not base:
            return None
        if not variant or base.name.lower() == variant.lower():
            return base if base.is_dir() else None
        candidate = base.parent / variant
        return candidate if candidate.is_dir() else None


def get_settings() -> Settings:
    return Settings()
