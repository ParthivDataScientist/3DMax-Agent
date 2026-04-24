/* ─────────────────────────────────────────────
   3DMax Agent — Frontend Logic
   • Animated background canvas
   • Drag-and-drop OBJ upload
   • Pipeline stage tracker
   • ZIP download via base64 response
───────────────────────────────────────────── */

"use strict";

// ── DOM refs ──────────────────────────────────
const fileInput        = document.getElementById("fileInput");
const dropzone         = document.getElementById("dropzone");
const dropzoneIdle     = document.getElementById("dropzoneIdle");
const dropzoneReady    = document.getElementById("dropzoneReady");
const selectedFileName = document.getElementById("selectedFileName");
const selectedFileSize = document.getElementById("selectedFileSize");
const sourceUnitEl     = document.getElementById("sourceUnit");
const processBtn       = document.getElementById("processBtn");
const statusMsg        = document.getElementById("statusMsg");
const pipelineTracker  = document.getElementById("pipelineTracker");
const resultCard       = document.getElementById("resultCard");
const downloadAgainBtn = document.getElementById("downloadAgainBtn");

// Result fields
const rModel      = document.getElementById("rModel");
const rComponents = document.getElementById("rComponents");
const rParts      = document.getElementById("rParts");
const rZipSize    = document.getElementById("rZipSize");
const rFolders    = document.getElementById("rFolders");
const rSheets     = document.getElementById("rSheets");
const rObjectTypes = document.getElementById("rObjectTypes");

// ── State ─────────────────────────────────────
let selectedFile   = null;
let lastZipBlob    = null;
let lastZipName    = null;

// ── Background canvas (floating particles) ────
(function initCanvas() {
  const canvas = document.getElementById("bgCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const particles = [];
  const COUNT = 55;

  function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener("resize", resize);

  const palette = [
    "rgba(91,143,255,",
    "rgba(192,132,252,",
    "rgba(251,146,60,",
  ];

  for (let i = 0; i < COUNT; i++) {
    const color = palette[Math.floor(Math.random() * palette.length)];
    particles.push({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      r: Math.random() * 2 + 0.6,
      dx: (Math.random() - 0.5) * 0.4,
      dy: (Math.random() - 0.5) * 0.4,
      alpha: Math.random() * 0.5 + 0.15,
      color,
    });
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of particles) {
      p.x += p.dx;
      p.y += p.dy;
      if (p.x < 0) p.x = canvas.width;
      if (p.x > canvas.width) p.x = 0;
      if (p.y < 0) p.y = canvas.height;
      if (p.y > canvas.height) p.y = 0;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color + p.alpha + ")";
      ctx.fill();
    }
    requestAnimationFrame(draw);
  }
  draw();
})();

// ── File handling ─────────────────────────────
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return Math.round(bytes / 1024) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

function setFile(file) {
  if (!file || !file.name.toLowerCase().endsWith(".obj")) {
    selectedFile = null;
    dropzoneIdle.hidden = false;
    dropzoneReady.hidden = true;
    processBtn.disabled = true;
    setStatus("");
    return;
  }

  selectedFile = file;
  selectedFileName.textContent = file.name;
  selectedFileSize.textContent = formatBytes(file.size);
  dropzoneIdle.hidden = true;
  dropzoneReady.hidden = false;
  processBtn.disabled = false;
  setStatus("");
  resetTracker();
}

fileInput.addEventListener("change", () => setFile(fileInput.files?.[0]));

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("drag");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag");
  setFile(e.dataTransfer?.files?.[0]);
});

// ── Status helper ─────────────────────────────
function setStatus(text, type = "") {
  statusMsg.textContent = text;
  statusMsg.className = "status-msg" + (type ? ` ${type}` : "");
}

// ── Pipeline tracker ──────────────────────────
const STEPS = ["upload", "analyze", "fabricate", "package"];
const STEP_LABELS = {
  upload:    { idle: "Idle", ready: "Ready", active: "Uploading…", done: "Done", error: "Error" },
  analyze:   { idle: "Idle", active: "Running…", done: "Done", error: "Error" },
  fabricate: { idle: "Idle", active: "Generating…", done: "Done", error: "Error" },
  package:   { idle: "Idle", active: "Packaging…", done: "Done", error: "Error" },
};

function setStepState(step, state) {
  const el = pipelineTracker.querySelector(`[data-step="${step}"]`);
  if (!el) return;
  el.dataset.state = state;
  const badge = el.querySelector(".step-badge");
  if (badge) badge.textContent = STEP_LABELS[step]?.[state] || state;
}

function resetTracker() {
  for (const step of STEPS) setStepState(step, "idle");
  // Mark upload as ready once a file is picked
  if (selectedFile) setStepState("upload", "ready");
}

// ── Process logic ─────────────────────────────
processBtn.addEventListener("click", async () => {
  if (!selectedFile) return;

  // Update UI to loading state
  processBtn.disabled = true;
  processBtn.classList.add("loading");
  setStatus("Sending file to pipeline…", "info");
  resultCard.hidden = true;
  downloadAgainBtn.hidden = true;

  // Tracker: step 1 done → step 2 active
  setStepState("upload", "done");
  setStepState("analyze", "active");

  let responseData = null;

  try {
    const fileText = await selectedFile.text();

    const response = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename:   selectedFile.name,
        content:    fileText,
        sourceUnit: sourceUnitEl.value,
      }),
    });

    // Tracker: analysis done → fabrication active
    setStepState("analyze", "done");
    setStepState("fabricate", "active");

    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      const raw = await response.text();
      throw new Error(
        `Unexpected response (${response.status}): ${raw.slice(0, 120)}`
      );
    }

    responseData = await response.json();

    if (!response.ok) {
      throw new Error(responseData.error || responseData.detail || "Processing failed");
    }

    // Tracker: fabrication done → packaging active → done
    setStepState("fabricate", "done");
    setStepState("package", "active");

    // Decode and trigger download
    setStatus("Finalizing package...", "info");
    
    let blob;
    try {
      // Modern way to convert base64 to blob efficiently
      const b64Response = await fetch(`data:application/zip;base64,${responseData.zipBase64}`);
      blob = await b64Response.blob();
    } catch (b64Err) {
      console.warn("Fast blob conversion failed, falling back to manual loop", b64Err);
      const binaryString = atob(responseData.zipBase64);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      blob = new Blob([bytes], { type: "application/zip" });
    }

    lastZipBlob = blob;
    lastZipName = responseData.filename || `${selectedFile.name.replace(/\.obj$/i, "")}_package.zip`;
    
    // Trigger download
    triggerDownload(lastZipBlob, lastZipName);

    // Tracker: packaging done
    setStepState("package", "done");

    // Show result card
    showResults(responseData, blob.size);

    const downloadUrl = URL.createObjectURL(blob);
    setStatus(`✓ Success! Auto-download started. `, "success");
    
    // Add a manual link just in case
    const manualLink = document.createElement("a");
    manualLink.href = downloadUrl;
    manualLink.download = lastZipName;
    manualLink.textContent = "Click here if it didn't start.";
    manualLink.style.textDecoration = "underline";
    manualLink.style.marginLeft = "8px";
    statusMsg.appendChild(manualLink);

  } catch (err) {
    // Mark any in-progress step as error
    for (const step of STEPS) {
      const el = pipelineTracker.querySelector(`[data-step="${step}"]`);
      if (el && el.dataset.state === "active") setStepState(step, "error");
    }
    setStatus(err.message || "Something went wrong.", "error");
  } finally {
    processBtn.disabled = false;
    processBtn.classList.remove("loading");
  }
});

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function showResults(data, zipByteLen) {
  // Populate stats
  rModel.textContent      = selectedFile?.name || "—";
  rComponents.textContent = data.componentCount ?? data.components ?? "—";
  rParts.textContent      = data.partGroupCount ?? data.partGroups ?? "—";
  rZipSize.textContent    = formatBytes(zipByteLen);
  rFolders.textContent    = "analysis / bom / assembly / elevations / parts";
  rSheets.textContent     = "PDF · CSV · JSON";

  // Object type tags
  const types = data.objectTypes || [];
  rObjectTypes.innerHTML = "";
  if (types.length === 0) {
    rObjectTypes.innerHTML = '<span class="tag">No detail returned</span>';
  } else {
    types.forEach((t) => {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = t;
      rObjectTypes.appendChild(span);
    });
  }

  resultCard.hidden = false;
  downloadAgainBtn.hidden = false;
  resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ── "Download again" button ────────────────────
downloadAgainBtn.addEventListener("click", () => {
  if (lastZipBlob && lastZipName) {
    triggerDownload(lastZipBlob, lastZipName);
  }
});
