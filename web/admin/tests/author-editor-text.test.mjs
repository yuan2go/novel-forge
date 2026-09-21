import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../app/features/editor/text.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}}).outputText;
const {exactOffset, retainExactLineEndings} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('textarea single edits retain exact mixed source newlines and Unicode', () => {
  const before = '　剑😀未出。\r\n她留步。\n我驻足。\r终。';
  const display = before.replace(/\r\n?/g, '\n');
  assert.equal(retainExactLineEndings(before, display.replace('未出', '已出')), before.replace('未出', '已出'));
  assert.equal(retainExactLineEndings(before, display.replace('留步', '未动')), before.replace('留步', '未动'));
  assert.equal(Array.from(before.slice(0, exactOffset(before, display.indexOf('她')))).length, 8);
  assert.equal(retainExactLineEndings(before, display), before);
});
