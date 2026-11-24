/** How often the Messages page checks for changes while it is open (milliseconds). Fast while a
 *  message is still being sent, slower otherwise so received messages show up on their own.
 *  `freshMs` is how long a new message keeps its unread marker on screen after it was shown and
 *  marked read. A plain object so tests can shorten the intervals. */
export const POLL = { pendingMs: 1500, idleMs: 3000, freshMs: 3 * 60_000 };
