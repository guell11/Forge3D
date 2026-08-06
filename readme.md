<div align="center">

# Forge3D

### Local AI 3D Generation Engine

**Image → 3D Mesh → UltraShape → UV → PBR Textures → GLB**

A modern browser-based local 3D generation engine powered by **TRELLIS** and **UltraShape**, designed to run entirely on consumer GPUs.

<img src="assets/banner.png" width="100%">

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi)
![Three.js](https://img.shields.io/badge/Three.js-000000?logo=three.js)
![License](https://img.shields.io/badge/License-MIT-success)

</div>

---

# Overview

**Forge3D** is a complete local AI pipeline that transforms a single image into a production-ready textured 3D model.

Built for creators, game developers, artists, designers and researchers, the entire workflow runs **100% locally**, ensuring every image, model and generated asset remains on your own machine.

Forge3D combines **TRELLIS** with **UltraShape** to produce cleaner geometry, optimized meshes, automatic UV generation and high-quality PBR assets through a single modern interface.

- 🖼️ Image → 3D Mesh
- 🔺 UltraShape Geometry Optimization
- 🎨 Automatic UV Generation
- 🌈 PBR Texture Generation
- 📦 GLB Export
- 💾 Fully Offline
- ⚡ Optimized for Consumer GPUs

The backend intelligently manages GPU resources using a serialized job queue for stable and predictable execution.

---

# Features

## 🎨 Modern Workspace

A professional dark interface inspired by modern 3D software.

Features include:

- Local asset gallery
- Drag & Drop uploads
- Generation history
- Real-time progress tracking
- GPU monitoring
- Integrated Three.js viewer
- Instant GLB preview
- Local asset management

---

# ⚙️ AI Pipeline

Forge3D is powered by a single optimized pipeline built around **TRELLIS** and **UltraShape**.

### TRELLIS + UltraShape

The default generation workflow provides:

✔ High-quality mesh generation

✔ Geometry refinement

✔ Automatic optimization

✔ Quad remeshing

✔ UV generation

✔ PBR texture generation

✔ GLB export

UltraShape performs an additional optimization pass after TRELLIS, producing cleaner topology, smoother surfaces and significantly better geometry for game engines, visualization and 3D printing.

Runs locally through:

```text
GET  /health

POST /generate
```

---

# 🚀 Smart GPU Scheduler

Forge3D executes every generation through a serialized GPU pipeline.

```text
GPU Queue

┌──────────────┐
│   TRELLIS    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ UltraShape   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ UV + Texture │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ GLB Export   │
└──────────────┘
```

Benefits:

- Lower VRAM usage
- Stable generation pipeline
- Automatic mesh optimization
- Fewer CUDA Out-Of-Memory errors
- Predictable GPU scheduling

---

# Recommended Presets

| VRAM | Engine | Resolution | Recommended Use |
|------|--------|------------|-----------------|
| 6 GB | TRELLIS Q4 + UltraShape | 512 | Lightweight generation and testing |
| 8 GB | TRELLIS Q4 + UltraShape | 1024 | Everyday asset creation |
| 12 GB | TRELLIS Q8 + UltraShape | 2K Atlas | High-quality production |
| 16 GB | TRELLIS Q8 + UltraShape | 2K Atlas | Maximum quality and faster generation |

---

# Architecture

```text
                 Browser

         React + Three.js
                │
                ▼
          FastAPI Backend
                │
        GPU Job Scheduler
                │
                ▼
            TRELLIS
                │
                ▼
           UltraShape
                │
                ▼
        UV + PBR Pipeline
                │
                ▼
         GLB Validation
                │
                ▼
      Local Gallery & Export
```

---

# Installation

## Windows

Requirements

- Python 3.10+
- Node.js LTS

Open:

```text
installation/
```

Choose the installer matching your GPU.

```text
bat-low-vram-6gb.bat

bat-8gb-vram.bat

bat-12gb-vram.bat

bat-16gb-vram.bat
```

When installation finishes:

```text
run.bat
```

Open:

```text
http://127.0.0.1:5173
```

---

## Linux

Equivalent scripts are included.

```text
low-vram-6gb.sh

8gb-vram.sh

12gb-vram.sh

16gb-vram.sh
```

Run

```bash
./run.sh
```

---

# Export Pipeline

Supported outputs

- GLB
- PBR Materials
- Texture Maps

Every exported model passes validation before becoming available.

Validation includes:

- Mesh integrity
- UV verification
- Embedded textures
- Material inspection

Forge3D validates every exported asset before it appears in the local gallery.

---

# UltraShape

Every Forge3D installation includes **UltraShape** as part of the generation pipeline.

UltraShape automatically performs:

- Mesh cleanup
- Surface refinement
- Geometry optimization
- Quad remeshing
- Production-ready topology

No additional configuration is required.

---

# Storage Requirements

| Component | Approx. Size |
|------------|--------------|
| TRELLIS Q4 | ~6 GB |
| TRELLIS Q8 | ~9.5 GB |
| UltraShape | ~7.4 GB |
| Python Dependencies | Variable |
| Generated Assets | User Defined |

---

# Technology Stack

### Frontend

- React
- Vite
- Three.js

### Backend

- FastAPI
- Python

### AI

- TRELLIS
- UltraShape

### Rendering

- Three.js
- WebGL

---

# Privacy

Everything runs locally.

✔ Images

✔ Jobs

✔ Models

✔ Textures

✔ Cache

✔ Generated Assets

No cloud inference.

No telemetry.

No external uploads.

Your data never leaves your computer.

---

# Documentation

```text
docs/
├── MANUAL.md
├── RESEARCH.md
└── API.md
```

Documentation includes:

- Installation Guide
- GPU Presets
- Backend Architecture
- API Reference
- Recovery Procedures
- Technical Research
- Known Limitations

---

# Licensing

Forge3D integrates multiple open-source projects.

Each third-party repository, model checkpoint and dependency remains subject to its own license.

Please review the license of every downloaded model before using generated assets in commercial projects.

---

<div align="center">

## ⭐ Star this repository if you enjoy local AI.

**Forge3D** brings powerful AI-driven 3D generation directly to your workstation, combining state-of-the-art open-source models with a polished desktop experience, complete privacy and full local ownership of every generated asset.

</div>
