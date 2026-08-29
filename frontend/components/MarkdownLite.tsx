import { Fragment, ReactNode } from "react";

/**
 * Renders the small slice of Markdown that chat models actually emit.
 *
 * The assistant was never told to write Markdown — it does it anyway, the way
 * chat models do — and the reply was being dropped into a `whitespace-pre-wrap`
 * paragraph as raw text. So every emphasis arrived on screen as literal
 * asterisks: "**Article 34** requires ...". Telling the model to stop would
 * have flattened structure that genuinely helps a policy answer read well, so
 * the structure is rendered instead.
 *
 * Deliberately NOT a Markdown library: this needs six constructs, no HTML
 * passthrough, and no dangerouslySetInnerHTML anywhere near model output.
 * Everything below builds React nodes from plain text.
 *
 * Supported — block: headings (#..###), bullet lists (-, *, •), ordered
 * lists (1.), blank-line paragraphs. Inline: **bold**, *italic*, _italic_,
 * `code`. Anything else renders as the literal characters the model wrote.
 */

type Props = { text: string; className?: string };

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|(?<![\w*])\*[^*\n]+\*(?![\w*])|(?<![\w_])_[^_\n]+_(?![\w_]))/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const start = m.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    const tok = m[0];
    const key = `${keyPrefix}-i${i++}`;
    if (tok.startsWith("**")) {
      out.push(
        <strong key={key} className="font-semibold text-navy-950">
          {tok.slice(2, -2)}
        </strong>
      );
    } else if (tok.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-black/5 px-1 py-0.5 font-mono text-[0.92em]">
          {tok.slice(1, -1)}
        </code>
      );
    } else {
      out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    }
    last = start + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; level: number; line: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] };

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  // Models are inconsistent about blank lines between a paragraph and the
  // list that follows it, so list detection is per-line rather than relying
  // on paragraph separation.
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const prev = blocks[blocks.length - 1];

    if (!line.trim()) {
      // Blank line closes whatever is open; an empty paragraph is not kept.
      if (prev && prev.kind === "p") blocks.push({ kind: "p", lines: [] });
      continue;
    }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ kind: "h", level: heading[1].length, line: heading[2] });
      continue;
    }

    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (bullet) {
      if (prev && prev.kind === "ul") prev.items.push(bullet[1]);
      else blocks.push({ kind: "ul", items: [bullet[1]] });
      continue;
    }

    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ordered) {
      if (prev && prev.kind === "ol") prev.items.push(ordered[1]);
      else blocks.push({ kind: "ol", items: [ordered[1]] });
      continue;
    }

    if (prev && prev.kind === "p" && prev.lines.length) prev.lines.push(line);
    else blocks.push({ kind: "p", lines: [line] });
  }
  return blocks.filter((b) => b.kind !== "p" || b.lines.length > 0);
}

export default function MarkdownLite({ text, className }: Props) {
  if (!text) return null;
  const blocks = parseBlocks(text);
  if (blocks.length === 0) return null;

  return (
    <div className={className ? `${className} space-y-2` : "space-y-2"}>
      {blocks.map((b, bi) => {
        if (b.kind === "h") {
          return (
            <p key={bi} className="font-semibold text-navy-950">
              {renderInline(b.line, `b${bi}`)}
            </p>
          );
        }
        if (b.kind === "ul") {
          return (
            <ul key={bi} className="list-disc space-y-1 pl-5">
              {b.items.map((it, ii) => (
                <li key={ii}>{renderInline(it, `b${bi}-${ii}`)}</li>
              ))}
            </ul>
          );
        }
        if (b.kind === "ol") {
          return (
            <ol key={bi} className="list-decimal space-y-1 pl-5">
              {b.items.map((it, ii) => (
                <li key={ii}>{renderInline(it, `b${bi}-${ii}`)}</li>
              ))}
            </ol>
          );
        }
        return (
          <p key={bi} className="whitespace-pre-wrap">
            {b.lines.map((ln, li) => (
              <Fragment key={li}>
                {li > 0 && "\n"}
                {renderInline(ln, `b${bi}-${li}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
