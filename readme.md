<div align="center">


<img width="1983" height="793" alt="image" src="https://github.com/user-attachments/assets/ba52b0a7-54b5-443e-8d03-a9d8738250e3" />
### Local AI 3D Generation Engine

**Image → 3D Mesh → UV → PBR Textures → GLB**

A modern browser-based local 3D generation engine powered by **Stable Fast 3D** and **TRELLIS**, designed to run entirely on consumer GPUs.

<img src="assets/banner.png" width="100%">

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi)
![Three.js](https://img.shields.io/badge/Three.js-000000?logo=three.js)
![License](https://img.shields.io/badge/License-MIT-success)

</div>

---

# Overview

**Forge3D** is a complete local AI pipeline that transforms a single image into a fully textured 3D model.

Designed for creators, game developers, artists, and researchers, the entire workflow runs **locally**, keeping every asset on your own machine. No cloud rendering, no subscriptions, no hidden uploads.

Forge3D combines multiple state-of-the-art generation backends behind a single modern interface.

- 🖼️ Image → 3D Mesh
- 🎨 Automatic UV Unwrapping
- 🌈 PBR Texture Generation
- 🔺 Quad Remeshing
- 📦 GLB Export
- 💾 Fully Offline
- ⚡ Optimized for Consumer GPUs

The backend intelligently manages VRAM, ensuring only one AI model is loaded at any given time.

---

# Features

## 🎨 Modern Workspace

A professional dark interface inspired by modern 3D applications.

Features include:

- Local asset gallery
- Drag & Drop uploads
- Generation history
- Real-time progress tracking
- GPU monitoring
- Built-in Three.js viewer
- Instant GLB preview

---

## ⚙️ Dual AI Engine

Forge3D supports two independent generation pipelines.

### Stable Fast 3D (Default)

Optimized for complete production-ready assets.

✔ Mesh generation

✔ UV unwrap

✔ Texture generation

✔ Physically Based Rendering (PBR)

✔ Quad remeshing

Perfect for game assets, visualization and rapid prototyping.

---

### TRELLIS

Alternative backend specialized in high-quality geometry generation.

Recommended when:

- maximum mesh fidelity is required
- textures will be created later
- custom pipelines are used

Runs locally through:

```
GET  /health

POST /generate
```

---

# 🚀 Smart GPU Scheduler

Unlike many community implementations, Forge3D never attempts to load multiple large diffusion models simultaneously.

```
GPU Queue

┌──────────────┐
│ StableFast3D │
└──────┬───────┘
       │
   unload VRAM
       ▼
┌──────────────┐
│   TRELLIS    │
└──────────────┘
```

Benefits:

- Lower VRAM usage
- Better stability
- Fewer CUDA Out-Of-Memory errors
- Predictable GPU scheduling

---

# Recommended Presets

| VRAM | Default Engine | Resolution | Recommended Use |
|------|----------------|------------|-----------------|
| 6 GB | TRELLIS Q4 | 512 | Geometry testing |
| 8 GB | Stable Fast 3D | 1024 | Complete textured assets |
| 12 GB | Stable Fast 3D Q8 | 2K Atlas | High quality production |
| 16 GB | Stable Fast 3D + UltraShape | 1024 | Maximum quality |

---

# Architecture

```
                 Browser

         React + Three.js
                │
                ▼
          FastAPI Backend
                │
        GPU Job Scheduler
                │
      ┌─────────┴─────────┐
      │                   │
      ▼                   ▼
 Stable Fast 3D       TRELLIS
      │                   │
      └─────────┬─────────┘
                ▼
         GLB Validation
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

```
installation/
```

Choose the installer matching your GPU.

```
bat-low-vram-6gb.bat

bat-8gb-vram.bat

bat-12gb-vram.bat

bat-16gb-vram.bat
```

When installation finishes:

```
run.bat
```

Open:

```
http://127.0.0.1:5173
```

---

## Linux

Equivalent scripts are included.

```
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

Supported outputs:

- GLB
- PBR Materials
- Texture Maps

Every exported model passes validation before becoming available.

Validation includes:

- Mesh detection
- UV verification
- Embedded textures
- Material inspection

Forge3D never labels an asset as PBR unless all required components are actually present.

---

# UltraShape

The 16 GB preset optionally installs UltraShape.

UltraShape remains experimental and requires its own compatible runtime.

Installation automatically downloads:

- Repository
- Model checkpoint
- Environment

---

# Storage Requirements

| Component | Approx. Size |
|------------|--------------|
| TRELLIS Q4 | ~6 GB |
| TRELLIS Q8 | ~9.5 GB |
| UltraShape | ~7.4 GB |
| Dependencies | Variable |

---

# Technology Stack

### Frontend

- React
- Vite
- Three.js

### Backend

- FastAPI
- Python

### AI Models

- Stable Fast 3D
- TRELLIS
- UltraShape (Optional)

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

```
docs/
├── MANUAL.md
├── RESEARCH.md
└── API.md
```

Documentation includes:

- Installation
- Recovery procedures
- Backend architecture
- Adapter installation
- Technical research
- Known limitations

---

# Licensing

Stable Fast 3D is distributed under the **Stability AI Community License**.

Some checkpoints are downloaded from community mirrors.

Commercial usage may require additional licensing depending on your organization's annual revenue and the specific model being used.

Always review the licenses associated with each repository and checkpoint before distributing generated assets.

---

<div align="center">

## ⭐ Star this repository if you like local AI.

**Forge3D** brings modern AI-powered 3D generation directly to your workstation, combining powerful open-source models with a polished desktop experience and complete local privacy.

</div>
