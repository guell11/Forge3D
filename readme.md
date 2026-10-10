<div align="center">

# ⚡ FORGE3D

### YOUR IDEAS DESERVE ANOTHER DIMENSION.

**One image. One click. A whole new world in 3D.**

<<<<<<< HEAD
Turn images into 3D creations with the power of AI —
right from your own machine **or a supported cloud GPU**.
=======
Turn images into 3D creations with the power of AI —  
right from your own machine.
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

<br>

[![GitHub Stars](https://img.shields.io/github/stars/guell11/Forge3D?style=for-the-badge&logo=github&color=8B5CF6)](https://github.com/guell11/Forge3D/stargazers)
![AI Powered](https://img.shields.io/badge/AI-POWERED-8B5CF6?style=for-the-badge)
![Local First](https://img.shields.io/badge/LOCAL-FIRST-18181B?style=for-the-badge)
![3D Creation](https://img.shields.io/badge/3D-CREATION-18181B?style=for-the-badge)

<br>

<<<<<<< HEAD
<img width="1672" height="941" alt="Forge3D interface" src="https://github.com/user-attachments/assets/fc301ca1-9d9b-44cc-a560-22feb6c596b8" />

<br>

### IMAGINE IT. GENERATE IT. FORGE IT.

**Your personal AI-powered 3D creation studio.**

[🚀 **GET STARTED**](#-start-creating) · [☁️ **RUN IN THE CLOUD**](#️-run-forge3d-in-the-cloud) · [✨ **EXPLORE**](#-the-power-to-create) · [🤖 **AI AGENTS**](#-3d-creation-meets-ai-agents)

=======
<img width="1672" height="941" alt="image" src="https://github.com/user-attachments/assets/fc301ca1-9d9b-44cc-a560-22feb6c596b8" />


<br>

### IMAGINE IT. GENERATE IT. FORGE IT.

**Your personal AI-powered 3D creation studio.**

[🚀 **GET STARTED**](#-start-creating) · [✨ **EXPLORE**](#-the-power-to-create) · [🤖 **AI AGENTS**](#-3d-creation-meets-ai-agents)

>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d
</div>

---

## ✨ What if every image could become something more?

A character concept. A game prop. A product idea. Something you dreamed up at 3 AM.

**Now imagine bringing it into 3D.**

<<<<<<< HEAD
That's Forge3D: an AI-powered creative workspace that turns reference images into 3D assets you can explore, refine, and export.

No complicated creative pipeline to piece together. No endless switching between tools.
=======
That's Forge3D.

An AI-powered creative workspace that turns reference images into 3D assets you can explore, refine, and export.

No complicated creative pipeline to piece together.

No endless switching between tools.
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

Just **your imagination and the freedom to build.**

---

## ⚡ From pixels to possibilities

<div align="center">

### 🖼️ IMAGINE → ✨ GENERATE → 🔮 EXPLORE → 📦 EXPORT

**Four steps. Infinite creative directions.**

</div>

<<<<<<< HEAD
=======
<br>

>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d
| | | |
|:---:|---|---|
| 🖼️ | **Image to 3D** | Give your ideas a whole new dimension. |
| ✨ | **AI-Powered Creation** | Turn visual inspiration into 3D assets. |
| 🔮 | **Interactive Preview** | Rotate, zoom, and experience your creations. |
| 💎 | **Geometry Refinement** | Explore more refined shapes with optional AI tools. |
| 🎨 | **Textured Creations** | Bring visual character into the third dimension. |
| 📦 | **Ready to Export** | Take your assets into your favorite 3D workflows. |
| 🗂️ | **Your Creative Gallery** | Keep your creations together in one place. |
| 🤖 | **AI Agent Integration** | Make 3D generation part of your AI-powered workflow. |
| 🖥️ | **Local-First** | Create with your own hardware, on your own terms. |

---

<<<<<<< HEAD
## ☁️ Run Forge3D in the cloud

**No powerful GPU at home? Use a hosted NVIDIA GPU.** Both notebooks install the Linux runtime, fetch quantized models, build the interface, ask for your ngrok authtoken (hidden input), create a private access token, and print the Forge3D URL plus a shareable `SKILL.md` URL for your AI agent.

<div align="center">

[![OPEN IN KAGGLE](https://img.shields.io/badge/OPEN_IN-KAGGLE-20BEFF?style=for-the-badge&logo=kaggle&logoColor=white)](https://www.kaggle.com/code)
[![OPEN IN COLAB](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/guell11/Forge3D/blob/main/notebooks/Forge3D_Colab_GPU.ipynb)

[⬇️ **Download Kaggle Notebook**](notebooks/Forge3D_Kaggle_T4.ipynb) · [⬇️ **Download Colab Notebook**](notebooks/Forge3D_Colab_GPU.ipynb) · [📖 **Cloud setup guide**](docs/KAGGLE.md)

</div>

**Kaggle:** select **GPU T4** and enable Internet, import [`Forge3D_Kaggle_T4.ipynb`](notebooks/Forge3D_Kaggle_T4.ipynb), then **Run All**. The Kaggle button opens Kaggle; import the notebook file there.

**Colab:** click **Open in Colab**, choose a **NVIDIA GPU runtime** in *Runtime → Change runtime type*, then **Run all**. Colab GPU availability varies by account and session. The GitHub Colab shortcut works after this notebook is committed to the repository's `main` branch.

**Google TPU v5e-1 / v5e-8:** **not supported for 3D generation at present.** The integrated `trellis.cpp` engine uses NVIDIA CUDA binaries; PyTorch/XLA or JAX alone cannot run it on a TPU. The notebooks intentionally check for a supported GPU and stop with an explanation rather than consuming a TPU session without generating a model. Native TPU inference would require a separate model port, supported kernels and measured quality/performance; it is not a switch on the existing runtime.

**Access:** after startup the notebook prints your HTTPS Forge3D URL and `https://YOUR-TUNNEL/agent/SKILL.md`. The skill is authenticated, so an agent also needs the access token **privately**. Never publish the token or share a public notebook with its outputs. The first model download is several GiB; hosted sessions are ephemeral and may stop at any time.

---

=======
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d
## 🔥 The power to create

### One studio. More ways to imagine.

Forge3D brings together powerful AI tools to give your ideas room to evolve.

<<<<<<< HEAD
**⚡ TRELLIS**
Turn an image into a 3D creation.

**💎 UltraShape**
Take your geometry further with optional refinement.

**🔺 FaithC**
=======
**⚡ TRELLIS**  
Turn an image into a 3D creation.

**💎 UltraShape**  
Take your geometry further with optional refinement.

**🔺 FaithC**  
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d
Explore an additional geometry-focused result when enabled.

Different tools. New possibilities. One creative space.

> UltraShape and FaithC are optional features. FaithC produces a separate geometry-only asset, not a replacement for your main textured creation.

---

## 🤖 3D creation meets AI agents

### Your AI assistant just got a new superpower.

Imagine working on a game, application, or creative project and asking your AI agent to help generate the 3D assets you need.

**Forge3D makes that workflow possible.**

With optional **MCP integration**, compatible agents such as **Codex** and **OpenCode** can interact with Forge3D to submit creations, follow their progress, and retrieve results.

**Your code. Your ideas. Your 3D pipeline. Connected.**

<<<<<<< HEAD
[**🤖 Explore MCP Integration →**](docs/MCP.md) · [**Agent SKILL.md →**](skills/forge3d-kaggle/SKILL.md)
=======
[**🤖 Explore MCP Integration →**](docs/MCP.md)
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

---

## 🎮 Built for people who create

| 🎮 Game Developers | 🎨 3D Artists |
|---|---|
| Bring props, objects, and concepts into your worlds. | Explore shapes, ideas, and new creative directions. |

| 🚀 Indie Makers | 🤖 AI Builders |
|---|---|
| Turn inspiration into something you can actually explore. | Connect AI-powered 3D creation to your workflows. |

<div align="center">

### You don't need a bigger imagination.

**You need a new way to bring it to life.**

</div>

---

## 🚀 Start creating

### Your next creation starts here.

**01 — Get Forge3D**

```bash
git clone https://github.com/guell11/Forge3D.git
cd Forge3D
```

**02 — Set up your machine**

Follow the [installation guide](docs/INSTALLATION.md) to choose the right setup for your hardware.

**03 — Launch your studio**

**Windows**
<<<<<<< HEAD

=======
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d
```bat
run.bat
```

**Linux**
<<<<<<< HEAD

=======
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d
```bash
./run.sh
```

**04 — Bring your idea to life**

<<<<<<< HEAD
Open **http://127.0.0.1:5173**. Upload an image. **Forge something amazing.**
=======
Open **http://127.0.0.1:5173**.

Upload an image.

**Forge something amazing.**
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

<div align="center">

### [🚀 INSTALL FORGE3D →](docs/INSTALLATION.md)

</div>

---

## 🖥️ Your machine. Your creativity. Your rules.

<<<<<<< HEAD
Your ideas shouldn't depend on someone else's creative platform. Forge3D is built around a **local-first experience**, giving you more control over how and where you create.
=======
Your ideas shouldn't depend on someone else's creative platform.

Forge3D is built around a **local-first experience**, giving you more control over how and where you create.
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

**No mandatory cloud generation service. No subscription required for local use.**

Just your hardware, your workflow, and your next big idea.

<<<<<<< HEAD
<sub>Initial setup and model downloads may require internet access. Cloud notebooks and remote server connections are not local/private processing. Generation depends on installed workers and supported hardware.</sub>
=======
<sub>Initial setup and model downloads may require internet access. Remote server connections are not local/private processing.</sub>
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

---

## 📚 Go further

**Ready to explore everything Forge3D can do?**

<<<<<<< HEAD
[📖 User Guide](docs/MANUAL.md) · [⚙️ Installation](docs/INSTALLATION.md) · [☁️ Cloud GPUs](docs/KAGGLE.md) · [🤖 MCP Integration](docs/MCP.md) · [🔬 Research](docs/RESEARCH.md)
=======
[📖 User Guide](docs/MANUAL.md) · [⚙️ Installation](docs/INSTALLATION.md) · [🤖 MCP Integration](docs/MCP.md) · [🔬 Research](docs/RESEARCH.md)
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

---

<div align="center">

## ⭐ LIKE WHAT YOU SEE?

### Help more creators discover Forge3D.

If you believe AI-powered 3D creation should be more accessible, flexible, and fun...

**Give Forge3D a star. It makes a difference.**

<br>

<<<<<<< HEAD
[![Star Forge3D](https://img.shields.io/badge/STAR_FORGE3D-8B5CF6?style=for-the-badge&logo=github)](https://github.com/guell11/Forge3D)
[![Share Your Ideas](https://img.shields.io/badge/SHARE_YOUR_IDEAS-18181B?style=for-the-badge)](https://github.com/guell11/Forge3D/issues)
=======
[![Star Forge3D](https://img.shields.io/badge/⭐_STAR_FORGE3D-8B5CF6?style=for-the-badge)](https://github.com/guell11/Forge3D)
[![Share Your Ideas](https://img.shields.io/badge/💬_SHARE_YOUR_IDEAS-18181B?style=for-the-badge)](https://github.com/guell11/Forge3D/issues)
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d

<br>

---

### DON'T JUST IMAGINE IT.

# FORGE IT IN 3D.

<<<<<<< HEAD
**FORGE3D**
=======
**FORGE3D**  
>>>>>>> d0f09a5e43a602697b43fb57fbdd2f4ac510da3d
*From imagination to dimension.*

</div>
