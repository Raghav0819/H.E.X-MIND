const test = require('node:test')
const assert = require('node:assert/strict')
const { addTodo, toggleTodo } = require('./todos')

test('addTodo appends an open todo with the next id', () => {
  const todos = addTodo(addTodo([], 'a'), 'b')
  assert.deepEqual(todos.map((t) => [t.id, t.title, t.done]), [[1, 'a', false], [2, 'b', false]])
})

test('toggleTodo flips done without mutating the input', () => {
  const todos = addTodo([], 'a')
  const toggled = toggleTodo(todos, 1)
  assert.equal(toggled[0].done, true)
  assert.equal(todos[0].done, false)
})
