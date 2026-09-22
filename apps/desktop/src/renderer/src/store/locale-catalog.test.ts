import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import { arabic } from './locale'

const renderer = join(process.cwd(), 'src', 'renderer', 'src')

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return entry.name.endsWith('.tsx') && !entry.name.endsWith('.test.tsx') ? [path] : []
  })
}

describe('Arabic interface catalogue', () => {
  it('covers every extracted static JSX label and translation lookup', () => {
    const missing = new Set<string>()
    for (const path of sourceFiles(renderer)) {
      const file = ts.createSourceFile(
        path,
        readFileSync(path, 'utf8'),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX
      )
      const visit = (node: ts.Node): void => {
        if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(file) === 'Tr') {
          const attribute = node.attributes.properties.find(
            (property) => ts.isJsxAttribute(property) && property.name.getText(file) === 'text'
          )
          if (
            attribute &&
            ts.isJsxAttribute(attribute) &&
            attribute.initializer &&
            ts.isJsxExpression(attribute.initializer) &&
            attribute.initializer.expression &&
            ts.isStringLiteral(attribute.initializer.expression) &&
            !(attribute.initializer.expression.text in arabic)
          ) {
            missing.add(attribute.initializer.expression.text)
          }
        }
        if (
          ts.isCallExpression(node) &&
          node.expression.getText(file) === 't' &&
          node.arguments[0] &&
          ts.isStringLiteral(node.arguments[0]) &&
          !(node.arguments[0].text in arabic)
        ) {
          missing.add(node.arguments[0].text)
        }
        ts.forEachChild(node, visit)
      }
      visit(file)
    }
    expect([...missing].sort()).toEqual([])
  })
})
