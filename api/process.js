const fs = require("fs/promises");
const os = require("os");
const path = require("path");
const { execFile } = require("child_process");
const { promisify } = require("util");

const execFileAsync = promisify(execFile);

function parseUploadLimitMb(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 30;
}

function parsePositiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

const MAX_OBJ_UPLOAD_MB = parseUploadLimitMb(process.env.MAX_OBJ_UPLOAD_MB);
const MAX_OBJ_UPLOAD_BYTES = MAX_OBJ_UPLOAD_MB * 1024 * 1024;
const PIPELINE_TIMEOUT_MS = parsePositiveInteger(process.env.PIPELINE_TIMEOUT_MS, 1_200_000);

async function runPipelineWithPython(objPath, sourceUnit, workDir) {
  const scriptPath = path.join(__dirname, "..", "pipeline", "web_package_runner.py");
  const candidates = [process.env.PYTHON_EXECUTABLE, "python3", "python"].filter(Boolean);
  let lastError = null;

  for (const pythonCmd of candidates) {
    try {
      const { stdout } = await execFileAsync(
        pythonCmd,
        [
          scriptPath,
          "--obj-path",
          objPath,
          "--source-unit",
          sourceUnit,
          "--work-dir",
          workDir,
        ],
        { timeout: PIPELINE_TIMEOUT_MS, cwd: path.join(__dirname, "..", "pipeline") }
      );

      const parsed = JSON.parse(stdout.trim().split("\n").pop());
      return parsed;
    } catch (error) {
      if (error.killed || error.signal) {
        lastError = new Error(
          `Pipeline timed out after ${Math.round(PIPELINE_TIMEOUT_MS / 1000)} seconds.`
        );
      } else {
        const detail = error.stderr || error.stdout || error.message;
        lastError = new Error(String(detail).slice(0, 1600));
      }
    }
  }

  throw new Error(`Python pipeline failed: ${lastError?.message || "No python runtime found"}`);
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  let workDir = "";
  try {
    const { filename, content, sourceUnit = "mm" } = req.body || {};
    if (!filename || typeof filename !== "string") {
      return res.status(400).json({ error: "Missing filename" });
    }
    if (!content || typeof content !== "string") {
      return res.status(400).json({ error: "Missing file content" });
    }
    if (Buffer.byteLength(content, "utf8") > MAX_OBJ_UPLOAD_BYTES) {
      return res.status(413).json({
        error: `OBJ file is too large. Maximum size is ${MAX_OBJ_UPLOAD_MB} MB.`,
      });
    }
    if (!filename.toLowerCase().endsWith(".obj")) {
      return res.status(400).json({ error: "Only .obj files are supported" });
    }
    if (!["mm", "cm", "m", "in"].includes(sourceUnit)) {
      return res.status(400).json({ error: "sourceUnit must be mm, cm, m, or in" });
    }

    workDir = await fs.mkdtemp(path.join(os.tmpdir(), "obj-package-"));
    const objPath = path.join(workDir, filename);
    await fs.writeFile(objPath, content, "utf8");

    const pipelineResult = await runPipelineWithPython(objPath, sourceUnit, workDir);
    const zipBuffer = await fs.readFile(pipelineResult.zip_path);

    return res.status(200).json({
      filename: `${pipelineResult.base_name}_package.zip`,
      zipBase64: zipBuffer.toString("base64"),
    });
  } catch (error) {
    return res.status(500).json({
      error: "Unable to generate fabrication package",
      detail: error.message,
    });
  } finally {
    if (workDir) {
      await fs.rm(workDir, { recursive: true, force: true });
    }
  }
};
