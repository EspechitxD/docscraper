const fs = require("fs");
const path = require("path");

const targetDir = path.join("electron", "dist");
fs.mkdirSync(targetDir, { recursive: true });
fs.copyFileSync(path.join("electron", "overlay.js"), path.join(targetDir, "overlay.js"));
