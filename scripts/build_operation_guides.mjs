import fs from "fs";
import path from "path";
import { execSync } from "child_process";

const repoRoot = process.cwd();
const docsDir = path.join(repoRoot, "docs", "operations");
const outDir = path.join(docsDir, "print");

const guides = [
  {
    source: path.join(docsDir, "EMPLOYEE_OPERATING_SUMMARY.md"),
    title: "BMM Operating Summary",
    subtitle: "Staff Reference Guide",
    output: "EMPLOYEE_OPERATING_SUMMARY",
  },
  {
    source: path.join(docsDir, "CASHIER_QUICK_REFERENCE.md"),
    title: "BMM Cashier Quick Reference",
    subtitle: "Cashier Shift Guide",
    output: "CASHIER_QUICK_REFERENCE",
  },
  {
    source: path.join(docsDir, "VENDOR_OPERATING_GUIDE.md"),
    title: "BMM Vendor Operating Guide",
    subtitle: "Vendor Reference Guide",
    output: "VENDOR_OPERATING_GUIDE",
  },
];

fs.mkdirSync(outDir, { recursive: true });

function escapeHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inlineCode(text) {
  return text.replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const html = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    if (/^### /.test(trimmed)) {
      html.push(`<h3>${inlineCode(escapeHtml(trimmed.slice(4)))}</h3>`);
      i += 1;
      continue;
    }

    if (/^## /.test(trimmed)) {
      html.push(`<h2>${inlineCode(escapeHtml(trimmed.slice(3)))}</h2>`);
      i += 1;
      continue;
    }

    if (/^# /.test(trimmed)) {
      html.push(`<h1>${inlineCode(escapeHtml(trimmed.slice(2)))}</h1>`);
      i += 1;
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      html.push(
        `<ol>${items
          .map((item) => `<li>${inlineCode(escapeHtml(item))}</li>`)
          .join("")}</ol>`,
      );
      continue;
    }

    if (/^- /.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^- /.test(lines[i].trim())) {
        items.push(lines[i].trim().slice(2));
        i += 1;
      }
      html.push(
        `<ul>${items
          .map((item) => `<li>${inlineCode(escapeHtml(item))}</li>`)
          .join("")}</ul>`,
      );
      continue;
    }

    const paragraph = [trimmed];
    i += 1;
    while (i < lines.length) {
      const next = lines[i].trim();
      if (!next) {
        break;
      }
      if (/^(#|##|###)\s+/.test(next) || /^\d+\.\s+/.test(next) || /^- /.test(next)) {
        break;
      }
      paragraph.push(next);
      i += 1;
    }
    html.push(`<p>${inlineCode(escapeHtml(paragraph.join(" ")))}</p>`);
  }

  return html.join("\n");
}

function renderPlainText(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const out = [];

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      out.push("");
      continue;
    }

    if (/^### /.test(trimmed)) {
      out.push(trimmed.slice(4).replace(/`/g, ""));
      out.push("");
      continue;
    }

    if (/^## /.test(trimmed)) {
      out.push(trimmed.slice(3).replace(/`/g, "").toUpperCase());
      out.push("");
      continue;
    }

    if (/^# /.test(trimmed)) {
      out.push(trimmed.slice(2).replace(/`/g, "").toUpperCase());
      out.push("");
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      out.push(trimmed.replace(/`/g, ""));
      continue;
    }

    if (/^- /.test(trimmed)) {
      out.push(`- ${trimmed.slice(2).replace(/`/g, "")}`);
      continue;
    }

    out.push(trimmed.replace(/`/g, ""));
  }

  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

function buildHtml({ title, subtitle, body }) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>
    :root {
      --ink: #1f1a17;
      --muted: #6d6259;
      --paper: #fffdf8;
      --line: #d9c9b1;
      --accent: #9b6b2f;
      --accent-soft: #f5eadb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background: linear-gradient(180deg, #f5ecdf 0%, var(--paper) 140px);
      line-height: 1.55;
    }
    .page {
      max-width: 860px;
      margin: 0 auto;
      padding: 48px 32px 64px;
    }
    .hero {
      border: 1px solid var(--line);
      background: rgba(255, 253, 248, 0.96);
      padding: 28px 30px 24px;
      border-radius: 18px;
      margin-bottom: 28px;
      box-shadow: 0 12px 40px rgba(31, 26, 23, 0.08);
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font: 600 11px/1.4 Arial, sans-serif;
      color: var(--accent);
      margin-bottom: 12px;
    }
    h1 {
      margin: 0;
      font-size: 34px;
      line-height: 1.12;
      font-weight: 600;
    }
    .subtitle {
      margin-top: 10px;
      font: 14px/1.5 Arial, sans-serif;
      color: var(--muted);
    }
    h2 {
      margin: 30px 0 10px;
      font-size: 22px;
      border-top: 1px solid var(--line);
      padding-top: 18px;
    }
    h3 {
      margin: 22px 0 8px;
      font-size: 17px;
    }
    p, li {
      font-size: 15px;
    }
    ul, ol {
      margin: 10px 0 16px 22px;
      padding: 0;
    }
    li {
      margin: 0 0 8px;
    }
    code {
      font-family: "SFMono-Regular", Menlo, monospace;
      font-size: 0.92em;
      background: var(--accent-soft);
      padding: 0.14em 0.34em;
      border-radius: 6px;
    }
    .footer {
      margin-top: 34px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
      font: 12px/1.5 Arial, sans-serif;
      color: var(--muted);
    }
    @media print {
      body {
        background: #fff;
      }
      .page {
        max-width: none;
        padding: 0.35in 0.45in 0.45in;
      }
      .hero {
        box-shadow: none;
        border-radius: 0;
      }
      a {
        color: inherit;
        text-decoration: none;
      }
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="eyebrow">Bowenstreet Market Management</div>
      <h1>${escapeHtml(title)}</h1>
      <div class="subtitle">${escapeHtml(subtitle)}</div>
    </section>
    ${body}
    <div class="footer">Prepared from the current BMM-POS feature set for quick employee reference.</div>
  </main>
</body>
</html>`;
}

function tryBuildPdf(textPath, pdfPath) {
  try {
    execSync(
      `cupsfilter -i text/plain -m application/pdf "${textPath}" > "${pdfPath}"`,
      { stdio: "ignore", shell: "/bin/zsh" },
    );
    return fs.existsSync(pdfPath) && fs.statSync(pdfPath).size > 0;
  } catch (error) {
    return false;
  }
}

const manifest = [];

for (const guide of guides) {
  const markdown = fs.readFileSync(guide.source, "utf8");
  const body = renderMarkdown(markdown);
  const plainText = renderPlainText(markdown);
  const html = buildHtml({ title: guide.title, subtitle: guide.subtitle, body });
  const htmlPath = path.join(outDir, `${guide.output}.html`);
  const txtPath = path.join(outDir, `${guide.output}.txt`);
  const pdfPath = path.join(outDir, `${guide.output}.pdf`);

  fs.writeFileSync(htmlPath, html, "utf8");
  fs.writeFileSync(txtPath, plainText, "utf8");
  const pdfBuilt = tryBuildPdf(txtPath, pdfPath);
  manifest.push({
    name: guide.output,
    html: path.relative(repoRoot, htmlPath),
    text: path.relative(repoRoot, txtPath),
    pdf: pdfBuilt ? path.relative(repoRoot, pdfPath) : null,
  });
}

fs.writeFileSync(
  path.join(outDir, "manifest.json"),
  JSON.stringify(manifest, null, 2),
  "utf8",
);

console.log(JSON.stringify(manifest, null, 2));
