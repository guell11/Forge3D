from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from enum import Enum


class ProfileId(str, Enum):
    GB6 = "6gb"
    GB8 = "8gb"
    GB12 = "12gb"
    GB16 = "16gb"


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    id: ProfileId
    label: str
    vram_gb: int
    target_resolution: int
    max_texture_resolution: int
    max_atlas_resolution: int
    default_seed: int
    background_removal: bool
    description: str
    notes: tuple[str, ...]

    def to_api(self) -> dict:
        result = asdict(self)
        result["id"] = self.id.value
        result["notes"] = list(self.notes)
        # This is intentionally false for every shipped profile.  Upstream
        # TRELLIS.2 needs substantially more memory than the target 6–16 GB tier.
        result["official_trellis2_supported"] = False
        result["recommended_backends"] = ["trellis-server", "trellis-cpp-cli", "demo"]
        result["trellis_qualities"] = trellis_qualities_for(self)
        return result


PROFILES: dict[ProfileId, HardwareProfile] = {
    ProfileId.GB6: HardwareProfile(
        id=ProfileId.GB6,
        label="Baixa VRAM — 6 GB",
        vram_gb=6,
        target_resolution=512,
        max_texture_resolution=1024,
        max_atlas_resolution=1024,
        default_seed=42,
        background_removal=True,
        description="Perfil conservador para GPUs de 6 GB; use um servidor/CLI compatível ou o modo demo.",
        notes=(
            "Processa um trabalho por vez para evitar picos de VRAM.",
            "O TRELLIS.2 oficial não é suportado neste perfil.",
        ),
    ),
    ProfileId.GB8: HardwareProfile(
        id=ProfileId.GB8,
        label="RTX 4060 / 8 GB",
        vram_gb=8,
        target_resolution=512,
        max_texture_resolution=1024,
        max_atlas_resolution=1024,
        default_seed=42,
        background_removal=True,
        description="Perfil balanceado para uma RTX 4060 8 GB com backend local compatível.",
        notes=(
            "Recomendado: trellis-server/trellis.cpp configurado localmente.",
            "O TRELLIS.2 oficial não é suportado em 8 GB; upstream requer Linux e cerca de 24 GB ou mais.",
        ),
    ),
    ProfileId.GB12: HardwareProfile(
        id=ProfileId.GB12,
        label="Equilibrado — 12 GB",
        vram_gb=12,
        target_resolution=1024,
        max_texture_resolution=1024,
        max_atlas_resolution=2048,
        default_seed=42,
        background_removal=True,
        description="Mais detalhe para GPUs de 12 GB, mantendo a fila serial.",
        notes=(
            "Até 1024 px quando o tier instalado estiver aprovado.",
            "O TRELLIS.2 oficial continua fora do escopo deste perfil.",
        ),
    ),
    ProfileId.GB16: HardwareProfile(
        id=ProfileId.GB16,
        label="Qualidade — 16 GB",
        vram_gb=16,
        target_resolution=1536,
        max_texture_resolution=1024,
        max_atlas_resolution=2048,
        default_seed=42,
        background_removal=True,
        description="Maior orçamento de qualidade para um backend compatível; ainda serializado para estabilidade.",
        notes=(
            "A disponibilidade real depende do backend local instalado.",
            "O TRELLIS.2 oficial não é declarado como compatível: a referência upstream pede pelo menos ~24 GB no Linux.",
        ),
    ),
}


def get_profile(profile_id: ProfileId | str) -> HardwareProfile:
    try:
        return PROFILES[ProfileId(profile_id)]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Perfil de VRAM desconhecido: {profile_id}") from exc


def all_profiles() -> list[dict]:
    return [profile.to_api() for profile in PROFILES.values()]


def trellis_qualities_for(profile: HardwareProfile) -> list[dict]:
    """Return only settings the installed profile can safely select.

    These are trellis.cpp rendering/topology budgets, not GGUF aliases or
    invented quantization choices. The installed GGUF package is reported by
    the runtime capability probe separately.
    """

    base = {
        "id": f"profile-{profile.id.value}",
        "label": f"Perfil instalado — {profile.target_resolution}px / atlas {profile.max_atlas_resolution}px",
        "resolution": profile.target_resolution,
        "atlas": profile.max_atlas_resolution,
        "texture_resolution": profile.max_texture_resolution,
        "default": True,
    }
    return [base]


def installed_trellis_qualities(profile: HardwareProfile, profile_path: Path | None = None) -> list[dict]:
    """Read the installer-approved tier registry when it matches the profile."""

    path = profile_path or Path(__file__).resolve().parents[2] / "runtime" / "engine-profile.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        trellis = payload.get("trellis") if isinstance(payload, dict) else None
        raw = trellis.get("qualities") if isinstance(trellis, dict) else None
        model_sets = trellis.get("model_sets") if isinstance(trellis, dict) else None
        default_quant = trellis.get("default_quant") if isinstance(trellis, dict) else None
        allowed_quants = {item for item in model_sets if isinstance(item, str)} if isinstance(model_sets, list) else set()
        if payload.get("profile") != profile.id.value or not isinstance(raw, list):
            raise ValueError("perfil incompatível")
        qualities: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            quality_id = item.get("id")
            resolution = item.get("resolution")
            atlas = item.get("atlas")
            texture_resolution = item.get("texture_resolution", min(atlas, 1024) if isinstance(atlas, int) else None)
            quant = item.get("quant") if isinstance(item.get("quant"), str) else default_quant
            if (
                not isinstance(quality_id, str)
                or not quality_id.replace("_", "").replace("-", "").isalnum()
                or not isinstance(resolution, int)
                or resolution not in {512, 1024, 1536}
                or not isinstance(atlas, int)
                or atlas < 256
                or resolution > profile.target_resolution
                or atlas > profile.max_atlas_resolution
                or texture_resolution > profile.max_texture_resolution
                or not isinstance(texture_resolution, int)
                or texture_resolution not in {512, 1024}
                or (allowed_quants and quant not in allowed_quants)
            ):
                continue
            qualities.append(
                {
                    "id": quality_id,
                    "label": item.get("label") if isinstance(item.get("label"), str) else quality_id,
                    "description": item.get("description") if isinstance(item.get("description"), str) else None,
                    "resolution": resolution,
                    "atlas": atlas,
                    "texture_resolution": texture_resolution,
                    "quant": quant if isinstance(quant, str) else None,
                    "default": not qualities,
                }
            )
        if qualities:
            return qualities
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return trellis_qualities_for(profile)


def resolve_trellis_quality(profile: HardwareProfile, quality_id: str | None, profile_path: Path | None = None) -> dict:
    qualities = installed_trellis_qualities(profile, profile_path)
    if quality_id is None:
        return qualities[0]
    for quality in qualities:
        if quality["id"] == quality_id:
            return quality
    raise ValueError("A qualidade TRELLIS solicitada não está disponível no perfil instalado.")
