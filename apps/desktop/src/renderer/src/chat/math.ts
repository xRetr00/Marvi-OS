/** Accept the other LaTeX delimiters models commonly emit, without touching code. */
export function normalizeMathDelimiters(content: string): string {
  return content
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((segment) => {
      if (segment.startsWith('`')) return segment
      return segment
        .replace(/\\\[([\s\S]*?)\\\]/g, (_match, expression: string) => `$$${expression}$$`)
        .replace(/\\\((.*?)\\\)/g, (_match, expression: string) => `$${expression}$`)
    })
    .join('')
}
