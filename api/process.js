const fs = require("fs/promises");
const os = require("os");
const path = require("path");
const { execFile } = require("child_process");
const { promisify } = require("util");

const execFileAsync = promisify(execFile);

async function runPipelineWithPython(objPath, sourceUnit, workDir) {
  const scriptPath = path.join(process.cwd(), "web_package_runner.py");
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
        { timeout: 120000 }
      );

      const parsed = JSON.parse(stdout.trim().split("\n").pop());
      return parsed;
    } catch (error) {
      lastError = error;
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
    if (!filename.toLowerCase().endsWith(".obj")) {
      return res.status(400).json({ error: "Only .obj files are supported" });
    }
    if (!["mm", "cm", "m"].includes(sourceUnit)) {
      return res.status(400).json({ error: "sourceUnit must be mm, cm, or m" });
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
