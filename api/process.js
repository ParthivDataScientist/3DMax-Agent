function analyzeObj(content) {
  const lines = content.split(/\r?\n/);
  let vertices = 0;
  let faces = 0;

  for (const line of lines) {
    if (line.startsWith("v ")) vertices += 1;
    if (line.startsWith("f ")) faces += 1;
  }

  return { vertices, faces };
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const { filename, content } = req.body || {};
    if (!filename || typeof filename !== "string") {
      return res.status(400).json({ error: "Missing filename" });
    }
    if (!content || typeof content !== "string") {
      return res.status(400).json({ error: "Missing file content" });
    }
    if (!filename.toLowerCase().endsWith(".obj")) {
      return res.status(400).json({ error: "Only .obj files are supported" });
    }

    const stats = analyzeObj(content);
    const header = [
      "# Processed by Vercel Preview OBJ Processor",
      `# Source file: ${filename}`,
      `# Vertices: ${stats.vertices}`,
      `# Faces: ${stats.faces}`,
      "",
    ].join("\n");

    const outputName = filename.replace(/\.obj$/i, "") + "_processed.obj";
    const outputContent = `${header}${content}`;

    return res.status(200).json({
      filename: outputName,
      content: outputContent,
      stats,
    });
  } catch (error) {
    return res.status(500).json({
      error: "Unable to process OBJ file",
      detail: error.message,
    });
  }
};
