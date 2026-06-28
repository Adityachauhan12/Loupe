import { diffLines, outputToText, type DiffLine } from "@/lib/textdiff";
import { cn } from "@/lib/utils";

/** Side-by-side line diff. Left=original, right=new/branched. Changed lines are
 *  tinted red (left) / green (right); a CSS grid keeps the two columns aligned
 *  row-for-row even when lines wrap. */
export function TextDiff({
  original,
  modified,
  originalLabel = "Original",
  modifiedLabel = "New",
}: {
  original: Record<string, unknown> | string | null | undefined;
  modified: Record<string, unknown> | string | null | undefined;
  originalLabel?: string;
  modifiedLabel?: string;
}) {
  const a = typeof original === "string" ? original : outputToText(original);
  const b = typeof modified === "string" ? modified : outputToText(modified);
  const { left, right, changes } = diffLines(a, b);

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface-2/60 font-mono text-xs">
      {/* Column headers */}
      <div className="grid grid-cols-2 border-b border-line text-[10px] font-semibold uppercase tracking-[0.12em]">
        <div className="border-r border-line px-3 py-1.5 text-faint">
          {originalLabel}
        </div>
        <div className="flex items-center justify-between px-3 py-1.5 text-faint">
          <span>{modifiedLabel}</span>
          {changes > 0 && (
            <span className="font-sans text-[10px] font-medium normal-case tracking-normal text-warning">
              {changes} line{changes > 1 ? "s" : ""} changed
            </span>
          )}
        </div>
      </div>

      {/* Aligned grid: left[i] and right[i] share a row */}
      <div className="grid max-h-96 grid-cols-2 overflow-y-auto">
        {left.map((l, i) => (
          <DiffCells key={i} left={l} right={right[i]} />
        ))}
      </div>
    </div>
  );
}

function DiffCells({ left, right }: { left: DiffLine; right: DiffLine }) {
  return (
    <>
      <Cell line={left} side="left" />
      <Cell line={right} side="right" />
    </>
  );
}

function Cell({ line, side }: { line: DiffLine; side: "left" | "right" }) {
  const tint =
    line.kind === "changed"
      ? side === "left"
        ? "bg-error/10"
        : "bg-success/10"
      : line.kind === "empty"
        ? "bg-bg/40"
        : "";
  const marker =
    line.kind === "changed" ? (side === "left" ? "-" : "+") : line.kind === "empty" ? "" : " ";
  const markerCls =
    line.kind === "changed"
      ? side === "left"
        ? "text-error"
        : "text-success"
      : "text-transparent";

  return (
    <div className={cn("flex gap-2 px-2 py-px", side === "right" && "border-l border-line", tint)}>
      <span className="w-7 shrink-0 select-none text-right tabular-nums text-faint/70">
        {line.n ?? ""}
      </span>
      <span className={cn("w-2 shrink-0 select-none", markerCls)}>{marker}</span>
      <span
        className={cn(
          "whitespace-pre-wrap break-words",
          line.kind === "empty" ? "text-transparent" : "text-muted",
          line.kind === "changed" && (side === "left" ? "text-error/90" : "text-success/90"),
        )}
      >
        {line.text ?? " "}
      </span>
    </div>
  );
}
