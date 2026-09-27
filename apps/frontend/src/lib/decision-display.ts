type DisplayOption = { id: string; title: string };

export function shortOptionLabel(title: string, maximum = 64) {
  const cleaned = title.trim().replace(/\s+/g, " ");
  for (const marker of [" that ", " which ", " while ", " because ", " in order to "]) {
    const index = cleaned.toLowerCase().indexOf(marker);
    if (index >= 4 && index <= maximum) return cleaned.slice(0, index).replace(/[ ,;:-]+$/, "");
  }
  if (cleaned.length <= maximum) return cleaned;
  const shortened = cleaned.slice(0, maximum);
  return shortened.slice(0, shortened.lastIndexOf(" ")).replace(/[ ,;:-]+$/, "") || shortened;
}

export function resolveOptionReferences(text: string | null | undefined, options: DisplayOption[]) {
  if (!text) return text ?? "";
  let rendered = text;
  for (const option of [...options].sort((left, right) => right.id.length - left.id.length)) {
    const label = shortOptionLabel(option.title);
    const references = new Set([option.id, option.id.slice(0, 8)]);
    for (const reference of references) {
      if (!reference) continue;
      const escaped = reference.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      rendered = rendered.replace(new RegExp(`\\bOption\\s+${escaped}\\b`, "gi"), label);
      rendered = rendered.replace(new RegExp(`\\b${escaped}\\b`, "gi"), label);
    }
  }
  return rendered
    .replace(/\bOption\s+[0-9a-f]{8}(?:-[0-9a-f-]{27})?\b/gi, "the option")
    .replace(/\bthe user(?:'s|’s)\b/gi, "your")
    .replace(/\bthe user\b/gi, "you");
}

export function recommendationStrength(value: string | undefined) {
  if (value === "high") return "Strongly supported";
  if (value === "moderate") return "Reasonably supported";
  if (value === "low") return "Tentative recommendation";
  return "Support not assessed";
}
