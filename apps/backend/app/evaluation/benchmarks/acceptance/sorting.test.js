const test = require('node:test')
const assert = require('node:assert/strict')

const { sortTodos } = require('../src/sort')

const todos = [
  { id: 3, title: 'banana', done: true },
  { id: 1, title: 'Cherry', done: false },
  { id: 2, title: 'apple', done: true },
  { id: 4, title: 'date', done: false },
]

test('sortTodos by title, id and status', () => {
  assert.deepEqual(sortTodos(todos, 'title').map((t) => t.id), [2, 3, 1, 4])
  assert.deepEqual(sortTodos(todos, 'id').map((t) => t.id), [1, 2, 3, 4])
  assert.deepEqual(sortTodos(todos, 'status').map((t) => t.id), [1, 4, 3, 2])
  assert.deepEqual(todos.map((t) => t.id), [3, 1, 2, 4])
})

test('sortTodos rejects unknown keys', () => {
  assert.throws(() => sortTodos(todos, 'size'), { message: 'unknown sort' })
})
