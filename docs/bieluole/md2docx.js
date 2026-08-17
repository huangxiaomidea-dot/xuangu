/**
 * 将「别落了」开发文档 Markdown 转为排版良好的 Word 文档。
 * 支持：标题、段落、无序/有序列表、表格、代码块、引用块、行内粗体/代码/链接。
 */
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  PageBreak, Header, Footer, PageNumber, Bookmark, InternalHyperlink,
  LevelFormat, VerticalAlign,
} = require('docx');

// ── 字体与配色 ───────────────────────────────────────────────
const BODY = { ascii: 'Segoe UI', eastAsia: '微软雅黑', hAnsi: 'Segoe UI' };
const HEAD = { ascii: 'Segoe UI', eastAsia: '微软雅黑', hAnsi: 'Segoe UI' };
// 代码块 eastAsia 也用 Consolas，保证制表符画的框线按半角渲染、CJK 回退为全角
const CODE = { ascii: 'Consolas', eastAsia: 'Consolas', hAnsi: 'Consolas' };

const C_TITLE = '1F3864';
const C_H1 = '1F4E79';
const C_H2 = '2E5E8C';
const C_H3 = '404040';
const C_BODY = '262626';
const C_MUTED = '767676';
const C_CODE = 'A31515';
const C_LINK = '1F4E79';
const C_TBL_HEAD = 'E8EEF7';
const C_TBL_BORDER = 'C6D0DC';
const C_CODE_BG = 'F5F7FA';

const CONTENT_WIDTH = 9026; // A4 (11906) - 左右页边距 1440*2

const thin = (color) => ({ style: BorderStyle.SINGLE, size: 4, color });

// ── 行内解析：**粗体**、`代码`、[文本](链接) ────────────────────
function inline(text, opts = {}) {
  const base = { font: BODY, size: opts.size || 21, color: opts.color || C_BODY, bold: opts.bold || false };
  const runs = [];
  // 先剥离链接语法，只保留文本
  const src = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1');
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) runs.push(new TextRun({ ...base, text: src.slice(last, m.index) }));
    const tok = m[0];
    if (tok.startsWith('**')) {
      // 粗体内部可能仍含行内代码，递归解析
      const innerText = tok.slice(2, -2);
      if (innerText.includes('`')) {
        runs.push(...inline(innerText, { ...opts, bold: true }));
      } else {
        runs.push(new TextRun({ ...base, text: innerText, bold: true }));
      }
    } else {
      runs.push(new TextRun({
        ...base, text: tok.slice(1, -1), font: CODE,
        size: (opts.size || 21) - 2, color: C_CODE,
        shading: { type: ShadingType.CLEAR, fill: C_CODE_BG },
      }));
    }
    last = m.index + tok.length;
  }
  if (last < src.length) runs.push(new TextRun({ ...base, text: src.slice(last) }));
  return runs.length ? runs : [new TextRun({ ...base, text: '' })];
}

function slugId(i) { return `sec_${i}`; }

// ── 主转换 ──────────────────────────────────────────────────
const md = fs.readFileSync(process.argv[2], 'utf8');
const lines = md.split('\n');

// 拆出封面区 / 目录区 / 正文区
const tocStart = lines.findIndex((l) => /^##\s*目录\s*$/.test(l));
let bodyStart = tocStart;
if (tocStart >= 0) {
  for (let i = tocStart + 1; i < lines.length; i++) {
    if (/^---\s*$/.test(lines[i])) { bodyStart = i + 1; break; }
  }
}
const coverLines = lines.slice(0, tocStart >= 0 ? tocStart : 0);
const bodyLines = lines.slice(bodyStart >= 0 ? bodyStart : 0);

const children = [];
const sections = []; // { id, text } 供目录使用
let sectionSeq = 0;
let numInstance = 0;
let firstH1Done = false;

// ── 封面 ────────────────────────────────────────────────────
const titleLine = (coverLines.find((l) => l.startsWith('# ')) || '# 开发文档').slice(2).trim();
const quoteLine = (coverLines.find((l) => l.startsWith('> ')) || '').slice(2).trim();
const metaLines = coverLines.filter((l) => /^-\s+/.test(l)).map((l) => l.replace(/^-\s+/, ''));

children.push(new Paragraph({ spacing: { before: 2600 }, children: [] }));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 200 },
  children: [new TextRun({ text: titleLine, font: HEAD, size: 56, bold: true, color: C_TITLE })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 600 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C_TITLE, space: 8 } },
  children: [new TextRun({ text: 'Product & Technical Specification', font: HEAD, size: 20, color: C_MUTED, characterSpacing: 40 })],
}));
if (quoteLine) {
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 900, line: 340 },
    indent: { left: 720, right: 720 },
    children: inline(quoteLine.replace(/^一句话定位：/, ''), { size: 22, color: C_H2 }),
  }));
}
metaLines.forEach((t) => {
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 120 },
    children: inline(t, { size: 20, color: C_MUTED }),
  }));
});
children.push(new Paragraph({ children: [new PageBreak()] }));

// ── 目录占位（先收集章节，最后回填）──────────────────────────
const tocAnchorIndex = children.length;

// ── 正文解析 ────────────────────────────────────────────────
function flushTable(buf) {
  const rows = buf.filter((l) => !/^\|[\s:|-]+\|$/.test(l))
    .map((l) => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim()));
  if (!rows.length) return;
  const colCount = Math.max(...rows.map((r) => r.length));
  // 按各列最长内容分配宽度
  const weights = [];
  for (let c = 0; c < colCount; c++) {
    let w = 1;
    rows.forEach((r) => { w = Math.max(w, (r[c] || '').replace(/[^\x00-\xff]/g, 'xx').length); });
    weights.push(Math.min(w, 60));
  }
  const total = weights.reduce((a, b) => a + b, 0);
  let widths = weights.map((w) => Math.max(700, Math.round((w / total) * CONTENT_WIDTH)));
  const drift = CONTENT_WIDTH - widths.reduce((a, b) => a + b, 0);
  widths[widths.length - 1] += drift;

  const trs = rows.map((cells, ri) => new TableRow({
    tableHeader: ri === 0,
    children: Array.from({ length: colCount }, (_, ci) => new TableCell({
      width: { size: widths[ci], type: WidthType.DXA },
      shading: ri === 0 ? { type: ShadingType.CLEAR, fill: C_TBL_HEAD } : undefined,
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({
        spacing: { before: 0, after: 0, line: 280 },
        children: inline(cells[ci] || '', { size: 19, bold: ri === 0, color: ri === 0 ? C_H1 : C_BODY }),
      })],
    })),
  }));

  children.push(new Table({
    columnWidths: widths,
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    borders: {
      top: thin(C_TBL_BORDER), bottom: thin(C_TBL_BORDER),
      left: thin(C_TBL_BORDER), right: thin(C_TBL_BORDER),
      insideHorizontal: thin(C_TBL_BORDER), insideVertical: thin(C_TBL_BORDER),
    },
    rows: trs,
  }));
  children.push(new Paragraph({ spacing: { after: 160 }, children: [] }));
}

function flushCode(buf) {
  buf.forEach((l, i) => {
    children.push(new Paragraph({
      spacing: { before: i === 0 ? 60 : 0, after: i === buf.length - 1 ? 200 : 0, line: 250 },
      indent: { left: 200 },
      shading: { type: ShadingType.CLEAR, fill: C_CODE_BG },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: 'C6D0DC', space: 6 } },
      children: [new TextRun({ text: l || ' ', font: CODE, size: 17, color: '1F2933' })],
    }));
  });
}

let i = 0;
while (i < bodyLines.length) {
  const line = bodyLines[i];

  // 代码块
  if (/^```/.test(line)) {
    const buf = [];
    i++;
    while (i < bodyLines.length && !/^```/.test(bodyLines[i])) { buf.push(bodyLines[i]); i++; }
    i++;
    flushCode(buf);
    continue;
  }

  // 表格
  if (/^\|.*\|\s*$/.test(line) && i + 1 < bodyLines.length && /^\|[\s:|-]+\|\s*$/.test(bodyLines[i + 1])) {
    const buf = [];
    while (i < bodyLines.length && /^\|.*\|\s*$/.test(bodyLines[i])) { buf.push(bodyLines[i]); i++; }
    flushTable(buf);
    continue;
  }

  // 标题
  const h = line.match(/^(#{1,4})\s+(.*)$/);
  if (h) {
    const level = h[1].length;
    const text = h[2].replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').trim();
    if (level === 2) {
      sectionSeq++;
      sections.push({ id: slugId(sectionSeq), text });
      children.push(new Paragraph({
        heading: HeadingLevel.HEADING_1,
        pageBreakBefore: firstH1Done,
        spacing: { before: firstH1Done ? 0 : 240, after: 240 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: C_H1, space: 6 } },
        children: [new Bookmark({
          id: slugId(sectionSeq),
          children: [new TextRun({ text, font: HEAD, size: 32, bold: true, color: C_H1 })],
        })],
      }));
      firstH1Done = true;
    } else if (level === 3) {
      children.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 320, after: 160 },
        children: [new TextRun({ text, font: HEAD, size: 25, bold: true, color: C_H2 })],
      }));
    } else {
      children.push(new Paragraph({
        heading: HeadingLevel.HEADING_3,
        spacing: { before: 240, after: 120 },
        children: [new TextRun({ text, font: HEAD, size: 22, bold: true, color: C_H3 })],
      }));
    }
    i++;
    continue;
  }

  // 引用块
  if (/^>\s?/.test(line)) {
    const buf = [];
    while (i < bodyLines.length && /^>\s?/.test(bodyLines[i])) { buf.push(bodyLines[i].replace(/^>\s?/, '')); i++; }
    buf.filter((t) => t.trim()).forEach((t, k, arr) => {
      children.push(new Paragraph({
        spacing: { before: k === 0 ? 120 : 0, after: k === arr.length - 1 ? 200 : 0, line: 320 },
        indent: { left: 240 },
        shading: { type: ShadingType.CLEAR, fill: 'FBF7EC' },
        border: { left: { style: BorderStyle.SINGLE, size: 16, color: 'D9A441', space: 8 } },
        children: inline(t, { size: 20, color: '5C4A22' }),
      }));
    });
    continue;
  }

  // 无序列表
  if (/^(\s*)-\s+(.*)$/.test(line)) {
    while (i < bodyLines.length && /^(\s*)-\s+(.*)$/.test(bodyLines[i])) {
      const m = bodyLines[i].match(/^(\s*)-\s+(.*)$/);
      const lvl = Math.min(1, Math.floor(m[1].length / 2));
      children.push(new Paragraph({
        numbering: { reference: 'bullets', level: lvl },
        spacing: { before: 0, after: 60, line: 320 },
        children: inline(m[2]),
      }));
      i++;
    }
    children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
    continue;
  }

  // 有序列表
  if (/^\s*\d+\.\s+/.test(line)) {
    numInstance++;
    while (i < bodyLines.length && /^\s*\d+\.\s+/.test(bodyLines[i])) {
      const m = bodyLines[i].match(/^\s*\d+\.\s+(.*)$/);
      children.push(new Paragraph({
        numbering: { reference: 'numbers', level: 0, instance: numInstance },
        spacing: { before: 0, after: 60, line: 320 },
        children: inline(m[1]),
      }));
      i++;
    }
    children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
    continue;
  }

  // 分隔线：忽略（章节已分页）
  if (/^---+\s*$/.test(line)) { i++; continue; }

  // 空行
  if (!line.trim()) { i++; continue; }

  // 普通段落
  children.push(new Paragraph({
    spacing: { before: 0, after: 160, line: 330 },
    children: inline(line.trim()),
  }));
  i++;
}

// ── 回填目录 ────────────────────────────────────────────────
const toc = [
  new Paragraph({
    spacing: { after: 300 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: C_H1, space: 6 } },
    children: [new TextRun({ text: '目  录', font: HEAD, size: 32, bold: true, color: C_H1 })],
  }),
  ...sections.map((s) => new Paragraph({
    spacing: { after: 130, line: 300 },
    indent: { left: 200 },
    children: [new InternalHyperlink({
      anchor: s.id,
      children: [new TextRun({ text: s.text, font: BODY, size: 21, color: C_LINK })],
    })],
  })),
  new Paragraph({ children: [new PageBreak()] }),
];
children.splice(tocAnchorIndex, 0, ...toc);

// ── 组装文档 ────────────────────────────────────────────────
const doc = new Document({
  creator: '别落了产品团队',
  title: titleLine,
  description: '「别落了」微信小程序开发文档',
  styles: { default: { document: { run: { font: BODY, size: 21, color: C_BODY } } } },
  numbering: {
    config: [
      {
        reference: 'bullets',
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 420, hanging: 220 } } } },
          { level: 1, format: LevelFormat.BULLET, text: '◦', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 840, hanging: 220 } } } },
        ],
      },
      {
        reference: 'numbers',
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 460, hanging: 260 } } } },
        ],
      },
    ],
  },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          spacing: { after: 60 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: 'D9D9D9', space: 4 } },
          children: [new TextRun({ text: '「别落了」微信小程序开发文档', font: BODY, size: 16, color: C_MUTED })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: '第 ', font: BODY, size: 16, color: C_MUTED }),
            new TextRun({ children: [PageNumber.CURRENT], font: BODY, size: 16, color: C_MUTED }),
            new TextRun({ text: ' 页 / 共 ', font: BODY, size: 16, color: C_MUTED }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], font: BODY, size: 16, color: C_MUTED }),
            new TextRun({ text: ' 页', font: BODY, size: 16, color: C_MUTED }),
          ],
        })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[3], buf);
  console.log(`已生成 ${process.argv[3]}  章节数=${sections.length}  段落/表格数=${children.length}`);
});
