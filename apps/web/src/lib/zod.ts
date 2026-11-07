import { z } from "zod";

// Zod otherwise compiles its parsers with `new Function`, which the production CSP (no
// 'unsafe-eval') blocks and reports. The interpreter path is plenty fast for these small forms.
z.config({ jitless: true });
