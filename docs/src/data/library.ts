/**
 * The library: everything that comes with cpbenchy, one entry per component. And the examples: files in
 * the repository's examples/ to copy and adapt.
 *
 * Each entry has a page, `src/content/docs/library/<id>.mdx`, that starts with `<PackageHeader id="..." />`
 * (the facts below, plus what git says about `source`) and ends with `<PackageSource id="..." />` (the
 * implementation, from `source`). The overview's cards come from here too. An example's page is
 * `src/content/docs/examples/<id>.mdx`, and its cards are on the examples' overview.
 */

/** Where the code is browsable online, for links to the implementation (null: none yet). */
export const REPOSITORY: { url: string | null; branch: string } = { url: "https://github.com/ThomSerg/CPBenchy", branch: "main" };

export type Kind = "observer" | "plugin" | "rules" | "module" | "command" | "example" | "executor" | "option";

export type Category = "output" | "solutions" | "rules" | "competitions" | "analysis" | "running";

/** How the examples are grouped: by what kind of file to copy. */
export type ExampleCategory = "plugins" | "loaders" | "scripts" | "integrations";

export interface Component {
  /** The page: /library/<id>/ */
  id: string;
  name: string;
  kind: Kind;
  category: Category | ExampleCategory;
  /** One or two plain sentences, for the cards: what it is for, not how it works. */
  summary: string;
  /** For an example: what it shows how to do. */
  shows?: string;
  /** A Phosphor icon, as `ph:<glyph>`. */
  icon: string;
  /** The one line that enables or runs it. */
  use: string;
  /** The implementation, relative to the repository root. */
  source: string;
  /** The class or function in `source` to show; without it, the whole file. */
  symbol?: string;
  /** What it needs besides cpbenchy. */
  requires?: string[];
  /** Instance formats it applies to, if not all. */
  formats?: string[];
  /** An external page about it, e.g. the competition. */
  homepage?: string;
  /** Who wrote it, when git doesn't say (e.g. the file is not committed yet). */
  author?: string;
  related?: string[];
  tags?: string[];
}

export const CATEGORIES: { id: Category; title: string; blurb: string }[] = [
  { id: "output", title: "Competition output", blurb: "Print answers the way solver competitions expect them." },
  { id: "solutions", title: "Solutions", blurb: "Check, keep and re-check the solutions solvers report." },
  { id: "rules", title: "Rules", blurb: "Complete experiment setups, such as a competition track's." },
  { id: "competitions", title: "Competitions", blurb: "Enter a competition, or run as if you were in one." },
  { id: "analysis", title: "Scoring and analysis", blurb: "Rank solvers, and look inside the models that were run." },
  { id: "running", title: "Running", blurb: "Where and how the runs happen." },
];

export const KINDS: Record<Kind, string> = {
  observer: "Observer",
  plugin: "Plugin",
  rules: "Rules",
  module: "Module",
  command: "Command",
  example: "Example",
  executor: "Executor",
  option: "Option",
};

export const LIBRARY: Component[] = [
  // --- output ---
  {
    id: "xcsp3-output",
    name: "XCSP3Output",
    kind: "observer",
    category: "output",
    summary: "Answers in the format of the XCSP3 competition, and optionally checked by its official checker.",
    icon: "ph:file-code",
    use: "-p cpbenchy.observers:XCSP3Output",
    source: "src/cpbenchy/observers.py",
    symbol: "XCSP3Output",
    requires: ["pycsp3, to read XCSP3", "java, for the official checker"],
    formats: ["xcsp3"],
    homepage: "https://xcsp.org/competitions",
    related: ["competition-output", "xcsp3-2025", "check-solutions"],
    tags: ["xcsp3", "competition", "output"],
  },
  {
    id: "pb-output",
    name: "PBOutput",
    kind: "observer",
    category: "output",
    summary: "Answers in the format of the Pseudo-Boolean competition.",
    icon: "ph:file-text",
    use: "-p cpbenchy.observers:PBOutput",
    source: "src/cpbenchy/observers.py",
    symbol: "PBOutput",
    formats: ["opb"],
    homepage: "https://www.cril.univ-artois.fr/PB26/",
    related: ["competition-output", "pb26"],
    tags: ["pseudo-boolean", "competition", "output"],
  },
  {
    id: "maxsat-output",
    name: "MaxSATOutput",
    kind: "observer",
    category: "output",
    summary: "Answers in the format of the MaxSAT Evaluation.",
    icon: "ph:file-text",
    use: "-p cpbenchy.observers:MaxSATOutput",
    source: "src/cpbenchy/observers.py",
    symbol: "MaxSATOutput",
    formats: ["wcnf"],
    related: ["competition-output", "sat-output"],
    tags: ["maxsat", "competition", "output"],
  },
  {
    id: "sat-output",
    name: "SATOutput",
    kind: "observer",
    category: "output",
    summary: "Answers in the format of the SAT competition.",
    icon: "ph:file-text",
    use: "-p cpbenchy.observers:SATOutput",
    source: "src/cpbenchy/observers.py",
    symbol: "SATOutput",
    formats: ["cnf"],
    related: ["competition-output", "maxsat-output", "solution-formats"],
    tags: ["sat", "competition", "output"],
  },
  {
    id: "competition-output",
    name: "CompetitionOutput",
    kind: "observer",
    category: "output",
    summary: "The starting point for the output of another competition: you describe the solution, the rest is done.",
    icon: "ph:puzzle-piece",
    use: "from cpbenchy.observers import CompetitionOutput",
    source: "src/cpbenchy/observers.py",
    symbol: "CompetitionOutput",
    related: ["xcsp3-output", "pb-output", "solution-formats"],
    tags: ["competition", "output", "base class"],
  },

  // --- solutions ---
  {
    id: "check-solutions",
    name: "CheckSolutions",
    kind: "plugin",
    category: "solutions",
    summary: "Catches wrong answers: every solution is checked against the model, and a wrong one counts as an error.",
    icon: "ph:seal-check",
    use: "-p cpbenchy.observers:CheckSolutions",
    source: "src/cpbenchy/observers.py",
    symbol: "CheckSolutions",
    related: ["solution-checker", "save-solution"],
    tags: ["verification", "solutions"],
  },
  {
    id: "save-solution",
    name: "SaveSolution",
    kind: "observer",
    category: "solutions",
    summary: "Keeps every final solution, to look at later or to check again without running anything.",
    icon: "ph:floppy-disk",
    use: "-p cpbenchy.observers:SaveSolution",
    source: "src/cpbenchy/observers.py",
    symbol: "SaveSolution",
    related: ["solution-checker", "check-solutions"],
    tags: ["solutions", "storage"],
  },
  {
    id: "solution-checker",
    name: "cpbenchy check",
    kind: "command",
    category: "solutions",
    summary: "Checks the solutions of finished experiments again, long after they ran.",
    icon: "ph:magnifying-glass",
    use: "cpbenchy check results/",
    source: "src/cpbenchy/check.py",
    symbol: "check_solution",
    related: ["check-solutions", "save-solution", "solution-formats"],
    tags: ["verification", "solutions", "command"],
  },
  {
    id: "solution-formats",
    name: "cpbenchy.formats",
    kind: "module",
    category: "solutions",
    summary: "Turns solutions into the text formats competitions and file formats use, and back.",
    icon: "ph:brackets-curly",
    use: "from cpbenchy import formats",
    source: "src/cpbenchy/formats.py",
    related: ["competition-output", "solution-checker"],
    tags: ["solutions", "formats", "building block"],
  },

  // --- rules ---
  {
    id: "xcsp3-2025",
    name: "xcsp3-2025",
    kind: "rules",
    category: "rules",
    summary: "Run as in the XCSP3 Competition 2025: its time and memory limits, its output.",
    icon: "ph:trophy",
    use: "--rules xcsp3-2025",
    source: "src/cpbenchy/rules/xcsp3-2025.toml",
    formats: ["xcsp3"],
    homepage: "https://arxiv.org/abs/2511.06918",
    related: ["xcsp3-2025-fast", "xcsp3-2025-parallel", "xcsp3-output", "submission"],
    tags: ["xcsp3", "competition", "2025"],
  },
  {
    id: "xcsp3-2025-fast",
    name: "xcsp3-2025-fast",
    kind: "rules",
    category: "rules",
    summary: "The XCSP3 Competition 2025's short track: a few minutes per instance.",
    icon: "ph:trophy",
    use: "--rules xcsp3-2025-fast",
    source: "src/cpbenchy/rules/xcsp3-2025-fast.toml",
    formats: ["xcsp3"],
    homepage: "https://arxiv.org/abs/2511.06918",
    related: ["xcsp3-2025", "xcsp3-2025-parallel"],
    tags: ["xcsp3", "competition", "2025"],
  },
  {
    id: "xcsp3-2025-parallel",
    name: "xcsp3-2025-parallel",
    kind: "rules",
    category: "rules",
    summary: "The XCSP3 Competition 2025's track for solvers that use several cores.",
    icon: "ph:trophy",
    use: "--rules xcsp3-2025-parallel",
    source: "src/cpbenchy/rules/xcsp3-2025-parallel.toml",
    formats: ["xcsp3"],
    homepage: "https://arxiv.org/abs/2511.06918",
    related: ["xcsp3-2025", "xcsp3-2025-fast"],
    tags: ["xcsp3", "competition", "2025", "parallel"],
  },
  {
    id: "pb26",
    name: "pb26",
    kind: "rules",
    category: "rules",
    summary: "Run as in the Pseudo-Boolean Competition 2026.",
    icon: "ph:trophy",
    use: "--rules pb26",
    source: "src/cpbenchy/rules/pb26.toml",
    formats: ["opb"],
    homepage: "https://www.cril.univ-artois.fr/PB26/",
    related: ["pb26-parallel", "pb-output", "submission"],
    tags: ["pseudo-boolean", "competition", "2026"],
  },
  {
    id: "pb26-parallel",
    name: "pb26-parallel",
    kind: "rules",
    category: "rules",
    summary: "The Pseudo-Boolean Competition 2026's tracks for solvers that use several cores.",
    icon: "ph:trophy",
    use: "--rules pb26-parallel",
    source: "src/cpbenchy/rules/pb26-parallel.toml",
    formats: ["opb"],
    homepage: "https://www.cril.univ-artois.fr/PB26/",
    related: ["pb26"],
    tags: ["pseudo-boolean", "competition", "2026", "parallel"],
  },

  // --- competitions ---
  {
    id: "submission",
    name: "cpbenchy submission",
    kind: "command",
    category: "competitions",
    summary: "Builds what you send to a competition, ready to upload and tested before you do.",
    icon: "ph:package",
    use: "cpbenchy submission build --test --archive zip",
    source: "src/cpbenchy/submission.py",
    symbol: "build",
    related: ["solve", "xcsp3-2025", "pb26"],
    tags: ["competition", "submission", "command"],
  },
  {
    id: "solve",
    name: "cpbenchy solve",
    kind: "command",
    category: "competitions",
    summary: "Solves a single instance the way a competition runs a solver.",
    icon: "ph:terminal",
    use: "cpbenchy solve instance.xml -s ortools --rules xcsp3-2025",
    source: "src/cpbenchy/solve.py",
    symbol: "solve",
    related: ["submission", "terminate"],
    tags: ["competition", "command"],
  },
  {
    id: "terminate",
    name: "--terminate",
    kind: "option",
    category: "competitions",
    summary: "Stops runs at their time limit the way competitions do, so they still give their best answer.",
    icon: "ph:hand",
    use: "--terminate --grace 1",
    source: "src/cpbenchy/worker/terminate.py",
    symbol: "stop",
    related: ["solve", "xcsp3-2025"],
    tags: ["limits", "signals", "competition"],
  },

  // --- analysis ---
  {
    id: "par",
    name: "PAR-k scores",
    kind: "option",
    category: "analysis",
    summary: "Ranks solvers the way competitions do: solved fast is good, unsolved is penalised.",
    icon: "ph:trophy",
    use: "--par 2",
    source: "src/cpbenchy/scoring.py",
    symbol: "par",
    related: ["analyze", "model-size"],
    tags: ["scoring", "competition", "par2"],
  },
  {
    id: "model-size",
    name: "ModelSize",
    kind: "observer",
    category: "analysis",
    summary: "Notes how big each model is, to relate solving times to model size.",
    icon: "ph:ruler",
    use: "-p cpbenchy.observers:ModelSize",
    source: "src/cpbenchy/observers.py",
    symbol: "ModelSize",
    related: ["par"],
    tags: ["statistics", "model"],
  },


  // --- running ---
  {
    id: "runlimit",
    name: "runlimit",
    kind: "executor",
    category: "running",
    summary: "Runs each solver in isolation with strict limits and trustworthy measurements.",
    icon: "ph:shield-check",
    use: "--executor runlimit",
    source: "src/cpbenchy/executors.py",
    symbol: "RunlimitExecutor",
    requires: ["Linux with cgroups v2 (see `cpbenchy doctor`)"],
    related: ["subprocess", "inline"],
    tags: ["executor", "benchexec", "measurement"],
  },
  {
    id: "subprocess",
    name: "subprocess",
    kind: "executor",
    category: "running",
    summary: "Runs anywhere, such as a laptop or CI, with best-effort limits.",
    icon: "ph:cpu",
    use: "--executor subprocess",
    source: "src/cpbenchy/executors.py",
    symbol: "SubprocessExecutor",
    related: ["runlimit", "inline"],
    tags: ["executor"],
  },
  {
    id: "inline",
    name: "inline",
    kind: "executor",
    category: "running",
    summary: "Runs inside your own program, to debug plugins step by step.",
    icon: "ph:bug",
    use: "--executor inline",
    source: "src/cpbenchy/executors.py",
    symbol: "InlineExecutor",
    related: ["runlimit", "subprocess"],
    tags: ["executor", "debugging"],
  },
  {
    id: "solution-trajectory",
    name: "solutions",
    kind: "plugin",
    category: "running",
    summary: "Records how solutions improve over time, for every run, out of the box.",
    icon: "ph:trend-up",
    use: "on by default; --no-solutions turns it off",
    source: "src/cpbenchy/solutions.py",
    related: ["par", "analyze"],
    tags: ["built-in", "anytime"],
  },
  {
    id: "backend",
    name: "cpbenchy.backend",
    kind: "module",
    category: "running",
    summary: "Lets another experiment tool use cpbenchy to measure its runs.",
    icon: "ph:plugs-connected",
    use: "cpbenchy.backend.run(submissions)",
    source: "src/cpbenchy/backend.py",
    symbol: "run",
    related: ["runlimit"],
    tags: ["integration", "api"],
  },
];

export const EXAMPLE_CATEGORIES: { id: ExampleCategory; title: string; blurb: string }[] = [
  { id: "plugins", title: "Plugins", blurb: "Score, store or follow runs; enable one with -p." },
  { id: "loaders", title: "Loaders", blurb: "Benchmark problems in a format of your own." },
  { id: "scripts", title: "Scripts", blurb: "Whole experiments and analyses, from Python." },
  { id: "integrations", title: "Integrations", blurb: "Use cpbenchy from other experiment tools." },
];

export const EXAMPLES: Component[] = [
  {
    id: "sqlite-store",
    name: "SqliteStore",
    kind: "example",
    category: "plugins",
    summary: "Also keeps results in a database, to collect many experiments in one place.",
    shows: "a plugin with its own option, a plugin object with state, and trylast",
    icon: "ph:database",
    use: "-p examples/plugins/sqlite_store.py",
    source: "examples/plugins/sqlite_store.py",
    related: ["analyze", "par"],
    tags: ["storage", "sql"],
  },
  {
    id: "knapsack-json",
    name: "KnapsackJSON",
    kind: "example",
    category: "loaders",
    summary: "Benchmarks problems stored in your own file format, here knapsacks written as JSON.",
    shows: "a Loader for a file format of your own",
    icon: "ph:file-plus",
    use: "--loader examples/loaders/knapsack_json.py:KnapsackJSON",
    source: "examples/loaders/knapsack_json.py",
    formats: ["json"],
    related: ["formulations"],
    tags: ["loader"],
  },
  {
    id: "param-sweep",
    name: "param_sweep.py",
    kind: "example",
    category: "scripts",
    summary: "Finds the best settings for a solver by trying several on the same instances.",
    shows: "an Experiment with several settings, and results as they come in",
    icon: "ph:sliders",
    use: "python examples/scripts/param_sweep.py instances/",
    source: "examples/scripts/param_sweep.py",
    related: ["formulations", "analyze"],
    tags: ["tuning", "experiment"],
  },
  {
    id: "formulations",
    name: "formulations.py",
    kind: "example",
    category: "scripts",
    summary: "Compares different ways of modelling the same problem, without any instance files.",
    shows: "generated instances, and a Loader that builds the model in the worker",
    icon: "ph:git-fork",
    use: "python examples/scripts/formulations.py --sizes 8 32 64",
    source: "examples/scripts/formulations.py",
    related: ["knapsack-json", "param-sweep"],
    tags: ["loader", "modelling"],
  },
  {
    id: "analyze",
    name: "analyze.py",
    kind: "example",
    category: "scripts",
    summary: "Compares solvers on finished results: scores, the best of all solvers, and a plot.",
    shows: "results as a pandas DataFrame: scores, the virtual best solver, a cactus plot",
    icon: "ph:chart-line",
    use: "python examples/scripts/analyze.py results/ --plot cactus.png",
    source: "examples/scripts/analyze.py",
    requires: ["pandas", "matplotlib, for the plot"],
    related: ["par", "sqlite-store"],
    tags: ["analysis", "pandas", "plot"],
  },
  {
    id: "run-experiments",
    name: "Run-Experiments",
    kind: "example",
    category: "integrations",
    summary: "Runs the experiments of a runexp config with cpbenchy, and keeps runexp's result folders.",
    shows: "using cpbenchy from another experiment framework, through cpbenchy.backend",
    icon: "ph:plugs-connected",
    use: "python examples/runexp/main.py config.json results/ --jobs 4",
    source: "examples/runexp/cpbenchy_runner.py",
    symbol: "CpbenchyRunner",
    requires: ["runexp (github.com/IgnaceBleukx/Run-Experiments)"],
    related: ["param-sweep", "analyze"],
    tags: ["runexp", "integration", "backend"],
  },
];

export function component(id: string): Component {
  const found = LIBRARY.find((c) => c.id === id) ?? EXAMPLES.find((c) => c.id === id);
  if (!found) throw new Error(`no library entry or example ${id}; add it to src/data/library.ts`);
  return found;
}

/** The page of a component or an example. */
export function pageUrl(c: Component): string {
  return isBuiltIn(c) ? `/library/${c.id}/` : `/examples/${c.id}/`;
}

/** Built-in components ship with cpbenchy; examples are files in the repository's examples/. */
export function isBuiltIn(c: Component): boolean {
  return c.kind !== "example";
}
