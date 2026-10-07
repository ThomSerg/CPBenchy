/**
 * Facts about library components, read from the repository at build time: what git says about their
 * source (last update, authors), the project's version and author, and the code of a class or function.
 */

import { execFileSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { REPOSITORY } from "../data/library";

/** The repository root: the docs build runs in docs/. */
export const ROOT = resolve(process.cwd(), "..");

export interface History {
  /** When the source last changed: its last commit, or else the file's modification time. */
  updated: Date;
  /** Whether `updated` comes from git (false: the file has changes that are not committed yet). */
  committed: boolean;
  /** Commit authors, most commits first. */
  authors: string[];
  commits: number;
}

function git(args: string[]): string {
  try {
    return execFileSync("git", ["-C", ROOT, ...args], { encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

const histories = new Map<string, History>();

export function history(path: string): History {
  const cached = histories.get(path);
  if (cached) return cached;
  const log = git(["log", "--format=%cI%x09%an", "--", path]).split("\n").filter(Boolean);
  const dirty = git(["status", "--porcelain", "--", path]) !== "";
  const counts = new Map<string, number>();
  for (const line of log) {
    const author = line.split("\t")[1];
    counts.set(author, (counts.get(author) ?? 0) + 1);
  }
  const authors = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([a]) => a);
  const fromGit = log.length > 0 && !dirty;
  const updated = fromGit ? new Date(log[0].split("\t")[0]) : statSync(resolve(ROOT, path)).mtime;
  const result = { updated, committed: fromGit, authors, commits: log.length };
  histories.set(path, result);
  return result;
}

const pyproject = readFileSync(resolve(ROOT, "pyproject.toml"), "utf8");

/** The cpbenchy version these docs describe. */
export const VERSION = /^version\s*=\s*"([^"]+)"/m.exec(pyproject)?.[1] ?? "unknown";

/** The project's authors, from pyproject.toml. */
export const PROJECT_AUTHORS = [...pyproject.matchAll(/\{\s*name\s*=\s*"([^"]+)"/g)].map((m) => m[1]);

export interface Snippet {
  code: string;
  /** 1-based, inclusive */
  start: number;
  end: number;
  lines: number;
}

/** The source of `symbol` (a top-level class or function) in a Python file, or the whole file. */
export function snippet(path: string, symbol?: string): Snippet {
  const lines = readFileSync(resolve(ROOT, path), "utf8").replace(/\n+$/, "").split("\n");
  if (!symbol) return { code: lines.join("\n"), start: 1, end: lines.length, lines: lines.length };
  const definition = new RegExp(`^(class|def) ${symbol}\\b`);
  let start = lines.findIndex((l) => definition.test(l));
  if (start < 0) throw new Error(`${symbol} not found in ${path}`);
  while (start > 0 && lines[start - 1].startsWith("@")) start--; // its decorators
  let end = start + 1;
  while (end < lines.length && !(lines[end] && !/^[\s#)\]}]/.test(lines[end]))) end++;
  while (end > start && lines[end - 1].trim() === "") end--;
  return { code: lines.slice(start, end).join("\n"), start: start + 1, end, lines: lines.length };
}

/** A link to the source online, if the repository has a URL. */
export function sourceUrl(path: string, start?: number, end?: number): string | null {
  if (!REPOSITORY.url) return null;
  const lines = start ? `#L${start}${end && end !== start ? `-L${end}` : ""}` : "";
  return `${REPOSITORY.url.replace(/\/$/, "")}/blob/${REPOSITORY.branch}/${path}${lines}`;
}
