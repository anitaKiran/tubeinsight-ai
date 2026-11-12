import type { ReactNode } from "react";

// A small, safe formatter for model headings, lists, bold text and code.
// React escapes all content; generated HTML is never injected into the page.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part.startsWith("`") && part.endsWith("`")
        ? <code key={index}>{part.slice(1, -1)}</code>
        : part,
  );
}

export default function AnswerText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r/g, "").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) { i += 1; continue; }
    const key = i;
    if (line.startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i += 1;
      blocks.push(<pre key={key}><code>{code.join("\n")}</code></pre>);
    } else if (/^#{1,6}\s/.test(line)) {
      blocks.push(<h3 key={key}>{inline(line.replace(/^#{1,6}\s+/, ""))}</h3>);
      i += 1;
    } else if (/^(?:[-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\d/.test(line);
      const pattern = ordered ? /^\d+[.)]\s+/ : /^[-*•]\s+/;
      const items: ReactNode[] = [];
      while (i < lines.length && pattern.test(lines[i].trim())) {
        items.push(<li key={i}>{inline(lines[i].trim().replace(pattern, ""))}</li>);
        i += 1;
      }
      blocks.push(ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
    } else {
      const paragraph: string[] = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !/^(?:#{1,6}\s|[-*•]\s|\d+[.)]\s|```)/.test(lines[i].trim())) paragraph.push(lines[i++].trim());
      blocks.push(<p key={key}>{inline(paragraph.join(" "))}</p>);
    }
  }
  return <div className="answer-text">{blocks}</div>;
}
