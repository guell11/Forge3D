from __future__ import annotations

from pathlib import Path

import httpx

from ..config import Settings
from ..profiles import HardwareProfile, get_profile, installed_trellis_qualities, resolve_trellis_quality
from ..schemas import ExportFormat, GenerationOptions, TrellisUvMode
from .base import AdapterError, AdapterResult
from .command import Cancelled, CommandOutput, command_is_resolvable, render_command, run_command


def _effective_options(profile: HardwareProfile, options: GenerationOptions) -> tuple[int, int, bool]:
    return (
        options.seed if options.seed is not None else profile.default_seed,
        options.resolution if options.resolution is not None else profile.target_resolution,
        profile.background_removal,
    )


class TrellisServerAdapter:
    """Adapter for a separately installed local ``trellis-server`` process.

    Contract used here: ``GET /health`` and ``POST /generate`` with a multipart
    ``image`` field plus ``seed``, ``resolution``, and ``bg_removal`` form
    values. The generate response must be a binary GLB. This API does not ship,
    download, or pretend to implement that server or its model weights.
    """

    id = "trellis-server"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.trellis_server_url)

    async def _probe(self) -> tuple[bool, str | None]:
        if not self.settings.trellis_server_url:
            return False, "TRELLIS_SERVER_URL não está definido."
        try:
            timeout = httpx.Timeout(min(3.0, max(0.5, float(self.settings.trellis_server_timeout_seconds))))
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{self.settings.trellis_server_url}/health")
            if response.is_success:
                return True, None
            return False, f"Servidor respondeu HTTP {response.status_code} em /health."
        except httpx.HTTPError as exc:
            return False, f"Servidor não acessível: {type(exc).__name__}."

    async def capability(self) -> dict:
        reachable, detail = await self._probe()
        return {
            "id": self.id,
            "label": "trellis-server local",
            "kind": "local-http-adapter",
            "configured": self.configured,
            "available": self.configured and reachable,
            "reachable": reachable,
            "url": self.settings.trellis_server_url,
            "outputs": ["glb"],
            "uses_gpu": True,
            "contract": {
                "health": "GET /health",
                "generate": "POST /generate (multipart image, seed, resolution, bg_removal) -> binary GLB",
            },
            "detail": detail or "Servidor local acessível.",
        }

    async def generate(
        self,
        *,
        image_path: Path,
        output_path: Path,
        profile: HardwareProfile,
        options: GenerationOptions,
        output_format: ExportFormat,
    ) -> AdapterResult:
        if not self.settings.trellis_server_url:
            raise AdapterError("trellis-server não configurado; defina TRELLIS_SERVER_URL ou selecione demo.")
        if output_format != ExportFormat.GLB:
            raise AdapterError("trellis-server retorna GLB. Solicite output_format='glb' ou configure um conversor/exportador separado.")
        seed, resolution, remove_background = _effective_options(profile, options)
        if resolution not in {512, 1024, 1536}:
            raise AdapterError(
                "trellis-server aceita resolution 512, 1024 ou 1536. "
                "Escolha um desses valores ou deixe o perfil definir o padrão."
            )
        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            raise AdapterError("Não foi possível ler a imagem de entrada local.") from exc
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            timeout = httpx.Timeout(float(self.settings.trellis_server_timeout_seconds), connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.settings.trellis_server_url}/generate",
                    files={"image": (image_path.name, image_bytes, _content_type_for(image_path))},
                    data={
                        "seed": str(seed),
                        "resolution": str(resolution),
                        # trellis-server accepts its own mode names, not a
                        # boolean: BiRefNet is the quality background-removal
                        # mode; threshold is the lower-overhead alternative.
                        "bg_removal": "birefnet" if remove_background else "threshold",
                    },
                    headers={"Accept": "model/gltf-binary,application/octet-stream"},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500].replace("\n", " ")
            raise AdapterError(f"trellis-server respondeu HTTP {exc.response.status_code}: {body or 'sem detalhes'}") from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"Falha ao chamar trellis-server local: {type(exc).__name__}.") from exc

        content = response.content
        if len(content) < 20 or content[:4] != b"glTF":
            raise AdapterError("trellis-server não retornou um GLB binário válido (assinatura glTF ausente).")
        output_path.write_bytes(content)
        return AdapterResult(output_path=output_path, adapter_id=self.id)


class TrellisCppCliAdapter:
    """Managed ``trellis-cli`` adapter with a compatibility template fallback.

    The current trellis.cpp CLI exposes a documented executable contract. The
    primary path below always builds an argument list (never a shell string),
    which lets the API report exactly which real TRELLIS options were used and
    terminate the process on cancellation. ``TRELLIS_CPP_COMMAND`` remains a
    compatibility bridge for installations that predate the managed runtime.
    """

    id = "trellis-cli"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def managed_bin(self) -> Path | None:
        return self.settings.resolved_trellis_cli_bin

    @property
    def managed_models(self) -> Path | None:
        return self.settings.resolved_trellis_cli_models_dir

    @property
    def managed_configured(self) -> bool:
        return bool(self.managed_bin and self.managed_models and self.managed_bin.is_file() and self.managed_models.is_dir())

    def models_for_quality(self, profile: HardwareProfile, options: GenerationOptions) -> tuple[dict, Path | None]:
        quality = resolve_trellis_quality(profile, options.trellis_quality_id, self.settings.engine_profile_path)
        variant = quality.get("quant") if isinstance(quality.get("quant"), str) else None
        return quality, self.settings.trellis_models_dir_for_variant(variant)

    def quality_capabilities(self, profile: HardwareProfile) -> list[dict]:
        result: list[dict] = []
        for quality in installed_trellis_qualities(profile, self.settings.engine_profile_path):
            variant = quality.get("quant") if isinstance(quality.get("quant"), str) else None
            models = self.settings.trellis_models_dir_for_variant(variant)
            result.append(
                {
                    **quality,
                    "available": bool(self.managed_bin and self.managed_bin.is_file() and models),
                    "models_variant": variant,
                    "detail": (
                        f"Conjunto {variant or 'padrão'} localizado para trellis-cli."
                        if models
                        else f"Conjunto {variant or 'padrão'} não está disponível para o trellis-cli gerenciado."
                    ),
                }
            )
        return result

    async def capability(self) -> dict:
        legacy_configured = bool(self.settings.trellis_cpp_command)
        configured = self.managed_configured or legacy_configured
        active_profile = get_profile(self.settings.active_profile)
        return {
            "id": self.id,
            "label": "trellis-cli local gerenciado",
            "kind": "managed-local-command-adapter",
            "configured": configured,
            "available": self.managed_configured or (legacy_configured and command_is_resolvable(self.settings.trellis_cpp_command)),
            "outputs": ["glb"],
            "uses_gpu": True,
            "managed": self.managed_configured,
            "quality_variants": self.quality_capabilities(active_profile),
            "legacy_command_configured": legacy_configured,
            "arguments": [
                "--image", "--output", "--models", "--gpu", "--seed", "--res", "--atlas", "--tex-res",
                "--bg-removal", "--xatlas|--box-uv", "--max-tokens", "--band", "--decim", "--webp",
                "--gss", "--gsh", "--no-fa", "--f32",
            ],
            "detail": (
                "trellis-cli e diretório GGUF detectados; execução em processo único com cancelamento real."
                if self.managed_configured
                else "Usando o template compatível TRELLIS_CPP_COMMAND; instale TRELLIS_CLI_BIN/TRELLIS_CLI_MODELS_DIR para argumentos estruturados."
                if legacy_configured
                else "trellis-cli/modelos não encontrados; nenhum processo TRELLIS será simulado."
            ),
        }

    async def generate(
        self,
        *,
        image_path: Path,
        output_path: Path,
        profile: HardwareProfile,
        options: GenerationOptions,
        output_format: ExportFormat,
        on_output: CommandOutput | None = None,
        is_cancelled: Cancelled | None = None,
    ) -> AdapterResult:
        if output_format != ExportFormat.GLB:
            raise AdapterError("trellis-cli exporta GLB. Solicite output_format='glb'.")
        seed, resolution, bg_removal = _effective_options(profile, options)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # trellis-cli exposes two independent budgets: UV atlas size and PBR
        # decode resolution.  The decoder accepts only 512/1024; passing a 2K
        # atlas as --tex-res is invalid and used to make high tiers fail.
        requested_texture = min(options.texture_resolution or 1024, 1024)
        texture_resolution = 512 if requested_texture <= 512 else 1024
        quality, quality_models = self.models_for_quality(profile, options)
        atlas_resolution = int(quality.get("atlas") or texture_resolution)
        if self.managed_configured:
            models = quality_models
            if not models:
                variant = quality.get("quant") or "padrão"
                raise AdapterError(
                    f"A qualidade TRELLIS solicitada requer o conjunto {variant}, mas esse models-dir não está disponível para trellis-cli."
                )
            command = self._managed_command(
                image_path=image_path,
                output_path=output_path,
                seed=seed,
                resolution=resolution,
                atlas_resolution=atlas_resolution,
                texture_resolution=texture_resolution,
                options=options,
                models_dir=models,
            )
            label = "trellis-cli"
        else:
            template = self.settings.trellis_cpp_command
            if not template:
                raise AdapterError("trellis-cli não configurado; instale TRELLIS_CLI_BIN/TRELLIS_CLI_MODELS_DIR.")
            command = render_command(
                template,
                input=str(image_path),
                output=str(output_path),
                seed=seed,
                resolution=resolution,
                bg_removal=options.trellis_background_removal.value if options.trellis_background_removal.value != "auto" else str(bg_removal).lower(),
                format=output_format.value,
                mesh_quality=options.mesh_quality or "default",
                texture_resolution=texture_resolution,
                atlas=atlas_resolution,
                max_tokens=options.trellis_max_tokens or 49_152,
                uv_mode=options.trellis_uv_mode.value,
                remesh_band=options.trellis_remesh_band if options.trellis_remesh_band is not None else "",
                decimation_grid=options.trellis_decimation_grid if options.trellis_decimation_grid is not None else "",
            )
            label = "CLI compatível TRELLIS"
        logs = await run_command(
            command,
            self.settings.trellis_command_timeout_seconds,
            label,
            on_output=on_output,
            is_cancelled=is_cancelled,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AdapterError("trellis-cli terminou, mas não criou o arquivo de saída esperado.")
        if output_path.read_bytes()[:4] != b"glTF":
            raise AdapterError("trellis-cli criou um arquivo sem assinatura GLB.")
        return AdapterResult(output_path=output_path, adapter_id=self.id, logs=logs)

    def _managed_command(
        self,
        *,
        image_path: Path,
        output_path: Path,
        seed: int,
        resolution: int,
        texture_resolution: int,
        options: GenerationOptions,
        models_dir: Path,
        atlas_resolution: int | None = None,
    ) -> list[str]:
        binary = self.managed_bin
        if not binary:
            raise AdapterError("trellis-cli gerenciado sem binário ou modelos.")
        command = [
            str(binary),
            "--image", str(image_path),
            "--output", str(output_path),
            "--models", str(models_dir),
            "--gpu", str(self.settings.trellis_cli_gpu_index),
            "--seed", str(seed),
            "--res", str(resolution),
            "--atlas", str(atlas_resolution or texture_resolution),
            "--tex-res", str(texture_resolution),
            "--bg-removal", options.trellis_background_removal.value,
        ]
        command.append("--xatlas" if options.trellis_uv_mode == TrellisUvMode.XATLAS else "--box-uv")
        if options.trellis_max_tokens is not None:
            command.extend(["--max-tokens", str(options.trellis_max_tokens)])
        if options.trellis_remesh_band is not None:
            command.extend(["--band", str(options.trellis_remesh_band)])
        if options.trellis_decimation_grid is not None:
            command.extend(["--decim", str(options.trellis_decimation_grid)])
        if options.trellis_webp is not None:
            command.extend(["--webp", "on" if options.trellis_webp else "off"])
        if options.trellis_gss is not None:
            command.extend(["--gss", str(options.trellis_gss)])
        if options.trellis_gsh is not None:
            command.extend(["--gsh", str(options.trellis_gsh)])
        if options.trellis_flash_attention is False:
            command.append("--no-fa")
        if options.trellis_f32:
            command.append("--f32")
        if self.settings.trellis_cli_require_gpu:
            command.append("--require-gpu")
        return command


def _content_type_for(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(path.suffix.lower(), "application/octet-stream")
