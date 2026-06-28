// Lightweight line-level diff for side-by-side output comparison.
// Produces two equal-length, index-aligned columns so the original and the
// new/branched output line up visually (GitHub split-diff style).

export type LineKind = "equal" | "changed" | "empty";

export interface DiffLine {
  text: string | null;
  kind: LineKind;
  /** Original line number (1-based) when present. */
  n: number | null;
}

export interface SideBySide {
  left: DiffLine[];
  right: DiffLine[];
  /** Number of lines that differ — quick "how much changed" signal. */
  changes: number;
}

/** Longest-common-subsequence over lines → minimal edit script. */
function lcsOps(a: string[], b: string[]): Array<{ t: "eq" | "del" | "ins"; a?: number; b?: number }> {
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops: Array<{ t: "eq" | "del" | "ins"; a?: number; b?: number }> = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ t: "eq", a: i, b: j });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ t: "del", a: i });
      i++;
    } else {
      ops.push({ t: "ins", b: j });
      j++;
    }
  }
  while (i < n) ops.push({ t: "del", a: i++ });
  while (j < m) ops.push({ t: "ins", b: j++ });
  return ops;
}

export function diffLines(originalText: string, modifiedText: string): SideBySide {
  const a = originalText.replace(/\n$/, "").split("\n");
  const b = modifiedText.replace(/\n$/, "").split("\n");
  const ops = lcsOps(a, b);

  const left: DiffLine[] = [];
  const right: DiffLine[] = [];
  let changes = 0;

  // Group consecutive del/ins runs so we can pair them as "changed" rows.
  let k = 0;
  while (k < ops.length) {
    const op = ops[k];
    if (op.t === "eq") {
      left.push({ text: a[op.a!], kind: "equal", n: op.a! + 1 });
      right.push({ text: b[op.b!], kind: "equal", n: op.b! + 1 });
      k++;
      continue;
    }
    // Collect the run of dels then ins.
    const dels: number[] = [];
    const inss: number[] = [];
    while (k < ops.length && ops[k].t === "del") dels.push(ops[k++].a!);
    while (k < ops.length && ops[k].t === "ins") inss.push(ops[k++].b!);
    const rows = Math.max(dels.length, inss.length);
    for (let r = 0; r < rows; r++) {
      const da = dels[r];
      const ib = inss[r];
      left.push(
        da != null
          ? { text: a[da], kind: "changed", n: da + 1 }
          : { text: null, kind: "empty", n: null },
      );
      right.push(
        ib != null
          ? { text: b[ib], kind: "changed", n: ib + 1 }
          : { text: null, kind: "empty", n: null },
      );
      changes++;
    }
  }

  return { left, right, changes };
}

/** Pull the human-readable text out of a span output (LLM content or JSON). */
export function outputToText(output: Record<string, unknown> | null | undefined): string {
  if (!output) return "";
  if (typeof output.content === "string") return output.content;
  return JSON.stringify(output, null, 2);
}
