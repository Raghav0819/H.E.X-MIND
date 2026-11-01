const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo } = require('../src/todos')
const { addTag, removeTag, searchTodos } = require('../src/tags')

test('tags are normalized and unique', () => {
  let todos = addTodo(addTodo([], 'Buy milk'), 'Write report')
  todos = addTag(todos, 1, ' Shopping ')
  todos = addTag(todos, 1, 'shopping')
  assert.deepEqual(todos[0].tags, ['shopping'])
  assert.throws(() => addTag(todos, 1, '  '), { message: 'tag required' })
  todos = removeTag(todos, 1, 'SHOPPING')
  assert.deepEqual(todos[0].tags, [])
})

test('searchTodos matches title or tags case-insensitively', () => {
  let todos = addTodo(addTodo([], 'Buy milk'), 'Write report')
  todos = addTag(todos, 2, 'work')
  assert.deepEqual(searchTodos(todos, 'MILK').map((t) => t.id), [1])
  assert.deepEqual(searchTodos(todos, 'wor').map((t) => t.id), [2])
  assert.deepEqual(searchTodos(todos, '').map((t) => t.id), [1, 2])
})
