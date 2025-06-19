const fs = require("fs");

function escapeContent(content) {
  return content.replace(/`/g, "\\`");
}

const index = escapeContent(fs.readFileSync("index.html", "utf8"));
const guide = escapeContent(fs.readFileSync("guide/index.html", "utf8"));
const install = escapeContent(fs.readFileSync("install.sh", "utf8"));
const beta = escapeContent(fs.readFileSync("beta.sh", "utf8"));

let worker = fs.readFileSync("worker.js", "utf8");
worker = worker
  .replace("`__INDEX_HTML__`", "`" + index + "`")
  .replace("`__GUIDE_HTML__`", "`" + guide + "`")
  .replace("`__INSTALL_SH__`", "`" + install + "`")
  .replace("`__BETA_SH__`", "`" + beta + "`");

fs.writeFileSync("dist/worker.js", worker);