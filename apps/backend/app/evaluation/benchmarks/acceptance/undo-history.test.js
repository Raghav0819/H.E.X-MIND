const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo } = require('../src/todos')
const { createHistory } = require('../src/history')

test('apply, undo and redo walk through states', () => {
  const history = createHistory([])
  history.apply((s) => addTodo(s, 'a'))
  history.apply((s) => addTodo(s, 'b'))
  history.apply((s) => toggleTodo(s, 1))
  assert.equal(history.current()[0].done, true)

  assert.equal(history.undo(), true)
  assert.equal(history.current()[0].done, false)
  assert.equal(history.undo(), true)
  assert.equal(history.current().length, 1)
  assert.equal(history.canRedo(), true)
  assert.equal(history.redo(), true)
  assert.equal(history.current().length, 2)
})

test('undo/redo report when there is nothing to do, and apply clears redo', () => {
  const history = createHistory([])
  assert.equal(history.canUndo(), false)
  assert.equal(history.undo(), false)
  history.apply((s) => addTodo(s, 'a'))
  history.undo()
  history.apply((s) => addTodo(s, 'b'))
  assert.equal(history.canRedo(), false)
  assert.equal(history.redo(), false)
  assert.deepEqual(history.current().map((t) => t.title), ['b'])
})
