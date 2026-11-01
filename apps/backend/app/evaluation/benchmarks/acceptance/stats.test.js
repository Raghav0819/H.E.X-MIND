const test = require('node:test')
const assert = require('node:assert/strict')

const { summarize } = require('../src/stats')

test('summarize counts totals, overdue and completion rate', () => {
  const todos = [
    { id: 1, title: 'a', done: true },
    { id: 2, title: 'b', done: false, dueDate: '2026-01-01' },
    { id: 3, title: 'c', done: false, dueDate: '2026-03-01' },
  ]
  assert.deepEqual(summarize(todos, '2026-02-01'), {
    total: 3, done: 1, remaining: 2, overdue: 1, completionRate: 0.33,
  })
})

test('summarize handles an empty list', () => {
  assert.deepEqual(summarize([], '2026-02-01'), {
    total: 0, done: 0, remaining: 0, overdue: 0, completionRate: 0,
  })
})
