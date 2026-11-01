const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo, completeAll, toggleAll } = require('../src/todos')

test('completeAll marks every todo done', () => {
  const todos = addTodo(addTodo([], 'a'), 'b')
  assert.deepEqual(completeAll(todos).map((t) => t.done), [true, true])
  assert.deepEqual(todos.map((t) => t.done), [false, false])
})

test('toggleAll completes all unless all are done', () => {
  const mixed = toggleTodo(addTodo(addTodo([], 'a'), 'b'), 1)
  const allDone = toggleAll(mixed)
  assert.deepEqual(allDone.map((t) => t.done), [true, true])
  assert.deepEqual(toggleAll(allDone).map((t) => t.done), [false, false])
})
