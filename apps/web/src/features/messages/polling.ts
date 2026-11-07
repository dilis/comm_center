/** How often the Messages page checks for changes while it is open (milliseconds). Fast while a
 *  message is still being sent, slower otherwise so received messages show up on their own.
 *  A plain object so tests can shorten the intervals. */
export const POLL = { pendingMs: 1500, idleMs: 3000 };
