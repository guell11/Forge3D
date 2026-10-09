# FaithC — Faithful Contouring & Geometry Refinement

FaithC is an optional geometry reconstruction stage for an existing GLB. It
uses the upstream FCT encoder and decoder through FaithC and Atom3d. It is not
an image-to-3D model and does not create UVs, textures, or normal maps.

The source GLB remains the job's primary output. Forge3D stores FaithC output
as a separate geometry-only GLB and stores a structural audit beside it. The
primary output keeps its original UV and PBR data, even when FaithC is
unavailable, times out, is cancelled, or produces an invalid artifact.

## Install in an isolated environment

FaithC builds native CUDA extensions and must use the same PyTorch build during
installation and execution. Keep it outside Forge3D's API virtual environment.
Upstream requires Python 3.10+ and PyTorch 2.5+; the commands below use the
upstream-documented PyTorch 2.5.1/CUDA 12.4 combination, which includes T4's
compute capability 7.5.

From the repository root on Linux:

```bash
python3 -m venv .venv-faithc
.venv-faithc/bin/python -m pip install --upgrade pip setuptools wheel packaging ninja
.venv-faithc/bin/python -m pip install torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124
export TORCH_CUDA_ARCH_LIST=7.5
.venv-faithc/bin/python -m pip install --no-build-isolation torch-scatter==2.1.2 -f https://data.pyg.org/whl/torch-2.5.1+cu124.html
.venv-faithc/bin/python -m pip install --no-build-isolation -r backend/requirements-faithc.txt
```

Install build tools before any `--no-build-isolation` command. Install the
matching prebuilt `torch-scatter` wheel after PyTorch and before the
requirements file, so native extensions use the same PyTorch 2.5.1/CUDA 12.4
build. The requirements file then installs Atom3d and FaithC from their
upstream repositories. The CUDA toolkit and a C++ compiler must be available
to build their extensions. For another PyTorch/CUDA combination, install the
matching PyTorch and `torch-scatter` wheels first and update the
`--find-links` version in `backend/requirements-faithc.txt` to the matching
upstream PyG wheel page.

Set these variables in `backend/.env` or the process environment, then restart
the API:

```dotenv
FAITHC_ENABLED=1
FAITHC_PYTHON=/absolute/path/to/open3d/.venv-faithc/bin/python
FAITHC_WORKER=/absolute/path/to/open3d/scripts/faithc_worker.py
FAITHC_TIMEOUT_SECONDS=900
FAITHC_PROBE_TIMEOUT_SECONDS=90
```

`FAITHC_ENABLED` defaults to `0`. Forge3D does not download FaithC sources,
PyTorch, or CUDA packages automatically. `GET /api/capabilities` never starts
Python, imports Torch, allocates CUDA, or competes with TRELLIS. It reports
`configured`, `available`, and `probe_state`. With a valid opt-in environment,
the initial state is `configured=true`, `available=false`,
`probe_state=not-calibrated`; the UI may enqueue FaithC and explain that CUDA
will be checked inside the serial GPU queue. The job confirms VRAM release,
then runs a bounded, cancellable worker probe that imports FaithC/Atom3d and
checks a CUDA device. Successful probes are cached for the API process
lifetime. Failed probes remain visible as `probe_state=failed` but are retried
by the next queued FaithC job; restart the API after changing runtime paths or
installing packages.

## Request a geometry artifact

The REST contract uses `options.faithc` and `options.faithc_resolution`:

```json
{
  "options": {
    "ultrashape": "off",
    "faithc": "geometry",
    "faithc_resolution": 256
  }
}
```

Accepted values are `faithc: off | geometry` and
`faithc_resolution: 128 | 256 | 512`. FaithC defaults to `off`; 256 is the
recommended starting resolution for an NVIDIA T4. Higher resolution consumes
more GPU memory. The published throughput figures are from an H100 and are
not estimates for a T4.

Check `configured` and `probe_state` in `GET /api/capabilities`; an
uncalibrated but configured runtime is eligible for a queued probe. In a
completed job, `GET /api/jobs/{id}` lists the geometry GLB and its JSON audit
under `artifacts`; `/api/jobs/{id}/download` continues to return the primary
PBR GLB. A failed FaithC run records a warning and leaves that primary file
unchanged. FaithC cancellation terminates its worker process, and the configured
timeout bounds the run.

## Geometry and limits

The worker loads scene-node transforms into world-space vertices, applies one
uniform temporary scale for the FCT grid, then restores the original center and
scale before export. This keeps vertex placement and numeric units unchanged;
the output is a flattened geometry mesh. FaithC output has no promise of UV or
PBR preservation, so Forge3D never replaces the source GLB with it.

FaithC encodes mesh surface intersections as Faithful Contour Tokens and
decodes them into a new mesh. It does not smooth the source, synthesize missing
detail, repair materials, or run a learned refinement model. Resolution is a
reconstruction grid setting, not a texture size or a triangle target. The
existing triangle target applies to the primary GLB; inspect the separate
FaithC artifact's audit for its actual mesh counts.

Upstream [FaithC](https://github.com/Luo-Yihao/FaithC) is Apache-2.0.
FaithC depends on [Atom3d](https://github.com/Luo-Yihao/Atom3d), which is
MIT-licensed. Read both upstream licenses before redistributing their code or
extensions.
