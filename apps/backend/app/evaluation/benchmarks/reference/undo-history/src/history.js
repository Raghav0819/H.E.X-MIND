function createHistory(initial) {
  const past = []
  const future = []
  let present = initial

  return {
    current: () => present,
    canUndo: () => past.length > 0,
    canRedo: () => future.length > 0,
    apply(fn) {
      past.push(present)
      present = fn(present)
      future.length = 0
    },
    undo() {
      if (past.length === 0) return false
      future.push(present)
      present = past.pop()
      return true
    },
    redo() {
      if (future.length === 0) return false
      past.push(present)
      present = future.pop()
      return true
    },
  }
}

module.exports = { createHistory }
