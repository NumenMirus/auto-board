// Tiny markdown renderer used by the /docs pages. No external dep — the docs
// are first-party (FOOTPRINTS.md, PROJECT_JSON.md) and known-shaped, so we
// support the subset we actually write: headings, paragraphs, unordered and
// ordered lists, fenced code blocks, inline code, GFM tables, blockquotes,
// horizontal rules, links, and bold/italic. Output is an HTML string ready to
// drop into {@html}. Always escape user-controlled data — none of the doc
// inputs are user-controlled, but the renderer treats backtick content as
// opaque and never interprets HTML inside it.

const ESCAPE_RE = /[&<>"']/g;
const ESCAPE_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
};

function isTableSeparator(line: string): boolean {
  // GFM separator: optional leading pipe, then cells of :?-+:? separated by
  // `|`, then optional trailing pipe. `-`, `:-`, `-:`, `:-:` all count.
  return /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/.test(line);
}

// Apply inline formatting: bold, italic, code, links. Order matters — backtick
// runs must be claimed before bold/italic scanning so `**foo**` inside inline
// code stays literal.
function renderInline(line: string): string {
  let out = '';
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === '`') {
      const end = line.indexOf('`', i + 1);
      if (end !== -1) {
        const code = line.slice(i + 1, end).replace(ESCAPE_RE, (c) => ESCAPE_MAP[c]);
        out += `<code>${code}</code>`;
        i = end + 1;
        continue;
      }
    }
    if (ch === '[') {
      const close = line.indexOf(']', i + 1);
      if (close !== -1 && line[close + 1] === '(') {
        const urlEnd = line.indexOf(')', close + 2);
        if (urlEnd !== -1) {
          const text = line.slice(i + 1, close);
          const url = line.slice(close + 2, urlEnd);
          out += `<a href="${url.replace(ESCAPE_RE, (c) => ESCAPE_MAP[c])}">${renderInline(text)}</a>`;
          i = urlEnd + 1;
          continue;
        }
      }
    }
    if (ch === '*' && line[i + 1] === '*') {
      const end = line.indexOf('**', i + 2);
      if (end !== -1) {
        out += `<strong>${renderInline(line.slice(i + 2, end))}</strong>`;
        i = end + 2;
        continue;
      }
    }
    if (ch === '*') {
      const end = line.indexOf('*', i + 1);
      if (end !== -1 && end > i + 1) {
        out += `<em>${renderInline(line.slice(i + 1, end))}</em>`;
        i = end + 1;
        continue;
      }
    }
    out += ch.replace(ESCAPE_RE, (c) => ESCAPE_MAP[c]);
    i += 1;
  }
  return out;
}

export function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim();
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith('```')) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // skip closing fence
      const cls = lang ? ` class="lang-${lang.replace(ESCAPE_RE, (c) => ESCAPE_MAP[c])}"` : '';
      out.push(
        `<pre${cls}><code>${buf.join('\n').replace(ESCAPE_RE, (c) => ESCAPE_MAP[c])}</code></pre>`
      );
      continue;
    }

    // Heading
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      out.push(`<h${level}>${renderInline(h[2])}</h${level}>`);
      i += 1;
      continue;
    }

    // Horizontal rule
    if (/^\s*---+\s*$/.test(line)) {
      out.push('<hr />');
      i += 1;
      continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith('> ')) {
        buf.push(lines[i].slice(2));
        i += 1;
      }
      out.push(`<blockquote>${renderMarkdown(buf.join('\n'))}</blockquote>`);
      continue;
    }

    // Table — header line followed by a separator line.
    if (line.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      let headerRow = line.trim();
      if (headerRow.startsWith('|')) headerRow = headerRow.slice(1);
      if (headerRow.endsWith('|')) headerRow = headerRow.slice(0, -1);
      const headerCells = headerRow.split('|').map((c) => c.trim());
      i += 2; // skip header + separator
      const bodyRows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        let row = lines[i].trim();
        if (row.startsWith('|')) row = row.slice(1);
        if (row.endsWith('|')) row = row.slice(0, -1);
        bodyRows.push(row.split('|').map((c) => c.trim()));
        i += 1;
      }
      const thead = headerCells.map((c) => `<th>${renderInline(c)}</th>`).join('');
      const tbody = bodyRows
        .map((row) => `<tr>${row.map((c) => `<td>${renderInline(c)}</td>`).join('')}</tr>`)
        .join('');
      out.push(`<table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`);
      continue;
    }

    // Unordered list
    if (/^\s*[-*]\s+/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*[-*]\s+/, ''));
        i += 1;
      }
      out.push(`<ul>${buf.map((l) => `<li>${renderInline(l)}</li>`).join('')}</ul>`);
      continue;
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*\d+\.\s+/, ''));
        i += 1;
      }
      out.push(`<ol>${buf.map((l) => `<li>${renderInline(l)}</li>`).join('')}</ol>`);
      continue;
    }

    // Blank line — paragraph break.
    if (line.trim() === '') {
      i += 1;
      continue;
    }

    // Paragraph — consume contiguous non-blank, non-special lines.
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].startsWith('```') &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !lines[i].startsWith('> ') &&
      !/^\s*---+\s*$/.test(lines[i]) &&
      !(lines[i].includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1]))
    ) {
      buf.push(lines[i]);
      i += 1;
    }
    if (buf.length) out.push(`<p>${renderInline(buf.join(' '))}</p>`);
  }

  return out.join('\n');
}