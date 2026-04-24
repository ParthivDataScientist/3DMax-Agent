/**
 * 3DMax Agent — Local Development Server
 *
 * Provides:
 *   GET  /          → serves index.html
 *   GET  /static    → serves styles.css, app.js, etc.
 *   POST /api/process → runs the Python fabrication pipeline
 *
 * Usage:
 *   node server.js                  (default port 3000)
 *   PORT=5000 node server.js        (custom port)
 *
 * Prerequisites:
 *   npm install express multer      (or use the setup in package.json)
 *   Python venv must be activated or PYTHON_EXECUTABLE env var must point
 *   to the venv python binary.
 */

"use strict";

const express  = require("express");
const path     = require("path");
const fs       = require("fs/promises");
const os       = require("os");
const { execFile } = require("child_process");
const { promisify } = require("util");

const execFileAsync = promisify(execFile);

const app  = express();
const PORT = process.env.PORT || 3000;

// ── Body parsing (JSON, up to 100 MB for large OBJ content strings) ──
app.use(express.json({ limit: "100mb" }));

// ── Static files (serve HTML, CSS, JS from public folder) ────────────
app.use(express.static(path.join(__dirname, "public")));

// ── Helper: find a working Python interpreter ────────────────────────
async function findPython() {
  const venvPath = path.join(__dirname, ".venv", "Scripts", "python.exe");
  const candidates = [
    process.env.PYTHON_EXECUTABLE,
    venvPath,
    path.join(__dirname, ".venv", "bin", "python3"), // Unix
    "python3",
    "python",
  ].filter(Boolean);

  console.log("Searching for Python interpreter...");
  for (const cmd of candidates) {
    try {
      // Use full path for venv to ensure it's picked up
      const fullCmd = path.isAbsolute(cmd) ? cmd : cmd; 
      await execFileAsync(fullCmd, ["--version"], { timeout: 3000 });
      console.log(`  [✓] Found working Python: ${fullCmd}`);
      return fullCmd;
    } catch (err) {
      console.log(`  [x] Candidate failed: ${cmd} (${err.message.split('\n')[0]})`);
    }
  }
  throw new Error(
    "No Python interpreter found. " +
    "Please ensure the virtual environment (.venv) is created and populated."
  );
}

// ── POST /api/process ────────────────────────────────────────────────
app.post("/api/process", async (req, res) => {
  let workDir = "";

  try {
    const { filename, content, sourceUnit = "mm" } = req.body || {};

    // ── Input validation ──
    if (!filename || typeof filename !== "string") {
      return res.status(400).json({ error: "Missing or invalid filename." });
    }
    if (!content || typeof content !== "string") {
      return res.status(400).json({ error: "Missing file content." });
    }
    if (!filename.toLowerCase().endsWith(".obj")) {
      return res.status(400).json({ error: "Only Wavefront .obj files are supported." });
    }
    if (!["mm", "cm", "m", "in"].includes(sourceUnit)) {
      return res.status(400).json({ error: "sourceUnit must be one of: mm, cm, m, in." });
    }

    // ── Write OBJ to a temp directory ──
    workDir = await fs.mkdtemp(path.join(os.tmpdir(), "obj-agent-"));
    const objPath = path.join(workDir, filename);
    await fs.writeFile(objPath, content, "utf8");

    // ── Resolve Python and run the pipeline ──
    const pythonCmd  = await findPython();
    const scriptPath = path.join(__dirname, "pipeline", "web_package_runner.py");

    console.log(`[${new Date().toISOString()}] Processing: ${filename} (unit=${sourceUnit})`);
    console.log(`  Python: ${pythonCmd}`);
    console.log(`  Work dir: ${workDir}`);

    const { stdout, stderr } = await execFileAsync(
      pythonCmd,
      [
        scriptPath,
        "--obj-path",   objPath,
        "--source-unit", sourceUnit,
        "--work-dir",   workDir,
      ],
      {
        timeout: 180_000, // 3 minutes max
        cwd: path.join(__dirname, "pipeline"),
      }
    );

    if (stderr) {
      // Surface Python warnings to server log but don't fail unless
      // stdout parse also fails.
      console.warn("[Python stderr]", stderr.slice(0, 800));
    }

    // The script prints one JSON line as its last output
    const lastLine    = stdout.trim().split(/\r?\n/).pop();
    const pipeResult  = JSON.parse(lastLine);

    // ── Read the generated zip ──
    const zipBuffer = await fs.readFile(pipeResult.zip_path);
    const zipBase64 = zipBuffer.toString("base64");

    // Optional: try to read summary metadata from analysis JSON
    let componentCount = "—";
    let partGroupCount = "—";
    let objectTypes    = [];

    try {
      const analysisDir = path.join(
        workDir, "output", pipeResult.base_name, "analysis"
      );
      const analysisFile = path.join(
        analysisDir, `${pipeResult.base_name}_analysis.json`
      );
      const raw = await fs.readFile(analysisFile, "utf8");
      const analysis = JSON.parse(raw);

      componentCount = (analysis.components ?? []).length;
      const partGroups = analysis.fabrication?.part_groups ?? [];
      partGroupCount = partGroups.length;
      objectTypes = [...new Set(partGroups.map((g) => g.object_type).filter(Boolean))];
    } catch {
      // Non-critical — result still includes the zip
    }

    console.log(`[${new Date().toISOString()}] Done: ${pipeResult.base_name}_package.zip (${Math.round(zipBuffer.length / 1024)} KB)`);

    return res.status(200).json({
      filename:       `${pipeResult.base_name}_package.zip`,
      zipBase64,
      componentCount,
      partGroupCount,
      objectTypes,
    });

  } catch (err) {
    console.error("[Error]", err.message);
    return res.status(500).json({
      error:  "Unable to generate fabrication package.",
      detail: err.message,
    });
  } finally {
    // Always clean up temp directory
    if (workDir) {
      fs.rm(workDir, { recursive: true, force: true }).catch(() => {});
    }
  }
});

// ── Health check ─────────────────────────────────────────────────────
app.get("/api/health", (_req, res) => {
  res.json({ status: "ok", ts: new Date().toISOString() });
});

// ── 404 fallback → SPA ───────────────────────────────────────────────
app.use((_req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

// ── Start ─────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log("─────────────────────────────────────────────");
  console.log("  3DMax Agent — Local Dev Server");
  console.log(`  http://localhost:${PORT}`);
  console.log("─────────────────────────────────────────────");
  console.log("  POST /api/process  → fabrication pipeline");
  console.log("  GET  /api/health   → health check");
  console.log("  Ctrl+C to stop");
  console.log("─────────────────────────────────────────────");
});
