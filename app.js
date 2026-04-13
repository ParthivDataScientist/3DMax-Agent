const fileInput = document.getElementById("fileInput");
const fileMeta = document.getElementById("fileMeta");
const processBtn = document.getElementById("processBtn");
const statusEl = document.getElementById("status");
const dropzone = document.getElementById("dropzone");

let selectedFile = null;

const setStatus = (text, isError = false) => {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#ff9d9d" : "";
};

const setFile = (file) => {
  if (!file || !file.name.toLowerCase().endsWith(".obj")) {
    selectedFile = null;
    fileMeta.textContent = "Please choose a valid .obj file";
    processBtn.disabled = true;
    return;
  }

  selectedFile = file;
  const sizeKb = Math.max(1, Math.round(file.size / 1024));
  fileMeta.textContent = `Selected: ${file.name} (${sizeKb} KB)`;
  processBtn.disabled = false;
  setStatus("");
};

fileInput.addEventListener("change", () => setFile(fileInput.files?.[0]));

dropzone.addEventListener("click", () => {
  fileInput.click();
});

dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropzone.classList.add("drag");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("drag");
});

dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("drag");
  setFile(event.dataTransfer?.files?.[0]);
});

processBtn.addEventListener("click", async () => {
  if (!selectedFile) {
    return;
  }

  processBtn.disabled = true;
  setStatus("Processing your OBJ...");

  try {
    const fileText = await selectedFile.text();
    const response = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: selectedFile.name,
        content: fileText,
      }),
    });

    let data;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const rawText = await response.text();
      throw new Error(
        `Backend route not found or invalid response (${response.status}). ${rawText.slice(0, 90)}`
      );
    }

    if (!response.ok) {
      throw new Error(data.error || "Processing failed");
    }

    const blob = new Blob([data.content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = data.filename || `processed_${selectedFile.name}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    setStatus("Done. Processed file downloaded. Nothing is stored on the server.");
  } catch (error) {
    setStatus(error.message || "Something went wrong.", true);
  } finally {
    processBtn.disabled = false;
  }
});
