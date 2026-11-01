const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo } = require('../src/todos')
const { PRIORITIES, setPriority, nextTodo } = require('../src/priority')

test('setPriority validates values', () => {
  assert.deepEqual(PRIORITIES, ['low', 'medium', 'high'])
  const todos = setPriority(addTodo([], 'a'), 1, 'high')
  assert.equal(todos[0].priority, 'high')
  assert.throws(() => setPriority(todos, 1, 'urgent'), { message: 'unknown priority' })
})

test('nextTodo picks the highest-priority open todo, lowest id first', () => {
  let todos = addTodo(addTodo(addTodo(addTodo([], 'a'), 'b'), 'c'), 'd')
  assert.equal(nextTodo(todos).id, 1) // all default to medium
  todos = setPriority(todos, 1, 'low')
  todos = setPriority(todos, 3, 'high')
  todos = setPriority(todos, 4, 'high')
  assert.equal(nextTodo(todos).id, 3)
  todos = toggleTodo(todos, 3)
  assert.equal(nextTodo(todos).id, 4)
  assert.equal(nextTodo([]), null)
})
