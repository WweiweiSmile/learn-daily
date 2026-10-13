/**
 * 一个够用就好的 Markdown 解析器。
 *
 * 只支持模型实际会吐出来的那几种：标题、无序/有序列表、代码块、段落、**加粗**。
 * 不引第三方渲染器是因为小程序端能用的那几个都要额外配 wxml 组件，为这点需求不值当。
 *
 * 纯函数，不碰 Taro，方便单独测。
 */

export interface Inline {
  text: string;
  bold: boolean;
}

export type Block =
  | { type: 'heading'; level: number; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'code'; text: string }
  | { type: 'paragraph'; text: string };

const CODE_FENCE = /^```/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const UNORDERED = /^[-*+]\s+(.*)$/;
const ORDERED = /^\d+[.、)]\s+(.*)$/;

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let code: string[] | null = null;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: 'paragraph', text: paragraph.join('\n') });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push({ type: 'list', ordered: list.ordered, items: list.items });
      list = null;
    }
  };
  const flushAll = () => {
    flushParagraph();
    flushList();
  };

  for (const line of source.split('\n')) {
    if (code !== null) {
      if (CODE_FENCE.test(line.trim())) {
        blocks.push({ type: 'code', text: code.join('\n') });
        code = null;
      } else {
        code.push(line);
      }
      continue;
    }

    if (CODE_FENCE.test(line.trim())) {
      flushAll();
      code = [];
      continue;
    }

    if (!line.trim()) {
      flushAll();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flushAll();
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() });
      continue;
    }

    const trimmed = line.trim();
    const unordered = UNORDERED.exec(trimmed);
    const ordered = ORDERED.exec(trimmed);
    if (unordered || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { ordered: isOrdered, items: [] };
      }
      list.items.push((ordered ?? unordered)![1].trim());
      continue;
    }

    flushList();
    paragraph.push(trimmed);
  }

  if (code !== null) blocks.push({ type: 'code', text: code.join('\n') });
  flushAll();
  return blocks;
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const pattern = /\*\*(.+?)\*\*/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) out.push({ text: text.slice(cursor, match.index), bold: false });
    out.push({ text: match[1], bold: true });
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), bold: false });
  return out.length ? out : [{ text, bold: false }];
}
