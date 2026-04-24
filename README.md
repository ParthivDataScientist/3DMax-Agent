# ⬡ 3DMax Agent — Fabrication Audit Pipeline

**3DMax Agent** is a production-grade geometry intelligence engine that transforms raw 3D meshes into manufacturing-ready fabrication packages. It automates the extraction of measurements, structural classification, and technical drawing generation for furniture, booths, and architectural models.

![3DMax Agent UI](file:///C:/Users/MU_ICT_025/.gemini/antigravity/brain/946472d7-3adf-49cd-85b1-f044d8eb8161/hero_header_top_1776145990988.png)

## 🚀 Key Features

*   **Premium Web Workspace**: A high-fidelity, glassmorphic UI for managing audits and tracking pipeline progress in real-time.
*   **Intelligent Geometry Pipeline**: Automatic segmentation, shape classification (`box`, `cylinder`, `panel`, etc.), and dimension extraction from Wavefront `.obj` files.
*   **Auto-Fabrication Drawings**: Instant generation of orthographic assembly sheets, elevations, and part-detail drawings in **PNG**, **PDF**, and **DXF** formats.
*   **Dynamic BOM Generation**: Automated Bill of Materials with material assignment and part grouping.
*   **One-Click Packaging**: Downloads all generated artifacts in a structured ZIP archive ready for the machine shop.

## 🏗️ Technical Architecture

The project utilizes a hybrid Node.js and Python stack to deliver high-performance geometry analysis with a modern web experience:

*   **Frontend**: Vanilla JS + Modern CSS (Glassmorphism, animated particles, CSS variables).
*   **Backend**: Node.js (Express) with robust subprocess management and virtual environment integration.
*   **Pipeline**: Python 3.x using `trimesh` for geometry analysis, `ezdxf` for CAD generation, and `matplotlib` for technical sheets.

## 🛠️ Getting Started

### Prerequisites

*   **Node.js** (v18+)
*   **Python** (v3.10+)

### Setup

1.  **Install Node dependencies**:
    ```bash
    npm install
    ```

2.  **Initialize Python Virtual Environment**:
    ```bash
    python -m venv .venv
    .\.venv\Scripts\activate  # Windows
    pip install -r requirements.txt
    ```

3.  **Run the Development Server**:
    ```bash
    npm run dev
    ```
    Access the workspace at `http://localhost:3000`.

## 📁 Package Structure

Every fabrication run generates a structured output directory bundled into a ZIP:

| Directory | Content | Formats |
| :--- | :--- | :--- |
| `analysis/` | Deep geometry payload and classification data. | `.json` |
| `bom/` | Bill of materials and part group signatures. | `.csv`, `.json` |
| `assembly/` | Orthographic assembly drawings with title blocks. | `.png`, `.pdf`, `.dxf` |
| `elevations/` | Top, Front, and Side elevation views. | `.png`, `.pdf`, `.dxf` |
| `parts/` | Detailed part sheets with centerline marks. | `.png`, `.pdf`, `.dxf` |

## ⚖️ Standards

All generated drawings adhere to **ISO/ASME** drafting standards, including:
*   Precise centerline and datum alignment.
*   Standard tolerance blocks.
*   Mathematically accurate dimensions based on object-aligned geometry.

---
*Developed for the Advanced Agentic Coding Workspace.*
