export function exactOffset(text: string, browserOffset: number): number {
  let original = 0, browser = 0;
  while (original < text.length && browser < browserOffset) {
    if (text[original] === "\r" && text[original + 1] === "\n") original += 2;
    else original += 1;
    browser += 1;
  }
  return original;
}

export function retainExactLineEndings(previous: string, browserText: string): string {
  const normalized = previous.replace(/\r\n?/g, "\n");
  let prefix = 0;
  while (prefix < normalized.length && prefix < browserText.length && normalized[prefix] === browserText[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < normalized.length - prefix && suffix < browserText.length - prefix
    && normalized[normalized.length - suffix - 1] === browserText[browserText.length - suffix - 1]) suffix += 1;
  const replacement = browserText.slice(prefix, browserText.length - suffix);
  const newline = previous.match(/\r\n|\r|\n/)?.[0] || "\n";
  return previous.slice(0, exactOffset(previous, prefix)) + replacement.replace(/\n/g, newline)
    + previous.slice(exactOffset(previous, normalized.length - suffix));
}
