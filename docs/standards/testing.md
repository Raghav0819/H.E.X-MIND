# Testing standards

## Node tests
Use the built-in runner: `import test from 'node:test'` and `import assert from 'node:assert/strict'`. Name test files `*.test.js` (for example `src/todos.test.js`) so `node --test` finds them. Tests must run offline with no installed packages.

## What to test
Test the pure logic modules (adding, toggling, deleting, filtering, validating, serializing todos). Each acceptance criterion of a task should be covered by at least one assertion. Include an edge case: empty input, missing item, or invalid stored data.

## Style
One behaviour per test, with a name that states it: `test('toggleTodo flips done for the matching id', ...)`. Arrange the input, call the function once, and assert on the result. Do not test DOM rendering with a fake browser; keep DOM code thin instead.

## Running checks
Run the `test` check after making changes and fix failures before finishing. Report the real result; never claim tests pass without running them.
