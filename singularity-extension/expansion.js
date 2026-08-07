/** Prompts and parsers for wiki expansion (terms / concepts / problems). */

function buildExtractListsPrompt(pageContent) {
  return (
    "Read the following page content and extract three lists.\n" +
    "Return ONLY valid JSON with no markdown fences:\n" +
    '{"terms":["..."],"concepts":["..."],"problems":["..."]}\n\n' +
    "Rules:\n" +
    "- terms: important vocabulary (short phrases)\n" +
    "- concepts: key ideas to understand\n" +
    "- problems: exercises, questions, or problems mentioned or implied\n" +
    "- up to 10 items per list\n\n" +
    "Content:\n---\n" +
    (pageContent || "").slice(0, 14000) +
    "\n---"
  );
}

function buildTermPrompt(term, sourceContent) {
  return (
    `Explain the term "${term}" using the source material below.\n\n` +
    "Use exactly these markdown section headings:\n\n" +
    "## Terms\n(related terms with brief definitions)\n\n" +
    "## Concepts\n(key concepts connected to this term)\n\n" +
    "## Problem list\n(practice problems or questions, numbered)\n\n" +
    "Source:\n---\n" +
    sourceContent.slice(0, 12000) +
    "\n---"
  );
}

function buildConceptPrompt(concept, sourceContent) {
  return (
    `Explain the concept "${concept}" using the source material below.\n\n` +
    "Use exactly these markdown section headings:\n\n" +
    "## Terms\n(related terms with brief definitions)\n\n" +
    "## Concepts\n(explain this concept and related ideas)\n\n" +
    "## Problem list\n(practice problems or questions, numbered)\n\n" +
    "Source:\n---\n" +
    sourceContent.slice(0, 12000) +
    "\n---"
  );
}

function buildProblemsPrompt(problems, sourceContent) {
  const list = problems.map((p, i) => `${i + 1}. ${p}`).join("\n");
  return (
    "Using the source material, work through these problems and related exercises.\n\n" +
    "Problems:\n" +
    list +
    "\n\nUse exactly these markdown section headings:\n\n" +
    "## Terms\n(vocabulary needed for these problems)\n\n" +
    "## Concepts\n(concepts required to solve them)\n\n" +
    "## Problem list\n(full problem statements with solutions or hints, numbered)\n\n" +
    "Source:\n---\n" +
    sourceContent.slice(0, 12000) +
    "\n---"
  );
}

function parseExtractedLists(text) {
  const raw = (text || "").trim();
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidate = fenced ? fenced[1].trim() : raw;
  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start < 0 || end <= start) {
    return { terms: [], concepts: [], problems: [] };
  }
  try {
    const o = JSON.parse(candidate.slice(start, end + 1));
    const pick = (arr) =>
      (Array.isArray(arr) ? arr : [])
        .map((x) => String(x || "").trim())
        .filter(Boolean);
    return {
      terms: pick(o.terms),
      concepts: pick(o.concepts),
      problems: pick(o.problems),
    };
  } catch {
    return { terms: [], concepts: [], problems: [] };
  }
}

function ensureStructuredFormat(body) {
  const t = (body || "").trim();
  const hasTerms = /^##\s*Terms\s*$/im.test(t);
  const hasConcepts = /^##\s*Concepts\s*$/im.test(t);
  const hasProblems = /^##\s*Problem list\s*$/im.test(t);
  if (hasTerms && hasConcepts && hasProblems) return t;
  return (
    "## Terms\n\n" +
    t +
    "\n\n## Concepts\n\n_(See terms above.)_\n\n" +
    "## Problem list\n\n_(See problem section in source.)_\n"
  );
}

function buildIndexMarkdown(rootTitle, rootPath, created, lists) {
  const lines = [
    `# Index: ${rootTitle}`,
    "",
    `Extracted from the answer page. Each linked page uses **Terms**, **Concepts**, and **Problem list** sections.`,
    "",
  ];

  lines.push("## Terms", "");
  if (created.terms.length) {
    for (const item of created.terms) {
      lines.push(`- [${item.label}](${item.path})`);
    }
  } else if (lists.terms.length) {
    for (const t of lists.terms) lines.push(`- ${t}`);
  } else {
    lines.push("- _(none extracted)_");
  }

  lines.push("", "## Concepts", "");
  if (created.concepts.length) {
    for (const item of created.concepts) {
      lines.push(`- [${item.label}](${item.path})`);
    }
  } else if (lists.concepts.length) {
    for (const c of lists.concepts) lines.push(`- ${c}`);
  } else {
    lines.push("- _(none extracted)_");
  }

  lines.push("", "## Problem list", "");
  if (created.problemsPage) {
    lines.push(`- [Problem set (${lists.problems.length} items)](${created.problemsPage.path})`);
    for (const p of lists.problems.slice(0, 20)) {
      lines.push(`  - ${p}`);
    }
  } else if (lists.problems.length) {
    for (const p of lists.problems) lines.push(`- ${p}`);
  } else {
    lines.push("- _(none extracted)_");
  }

  lines.push("", "---", "", `[← Answer page](${rootPath})`);
  return lines.join("\n");
}
