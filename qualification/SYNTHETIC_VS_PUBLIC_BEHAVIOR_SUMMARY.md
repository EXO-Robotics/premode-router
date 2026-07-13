# Synthetic versus public behavior

The panels are not pooled. The earlier 30-task synthetic panel had equal
success (27/30 each) and B0 saved 7.8% tokens, 15.2% requests, 25.8% unique
reads, and 31.0% searches. The 35-task public-repository panel had B0 at
30/35 versus STANDARD 32/35 and nearly double tokens.

The observable structural contrast is not simply “synthetic versus real”:

* synthetic positive cases supplied small, accurate packets with useful paths;
* the public panel projected 488 paths and only 11 were read;
* public tasks had large repositories, duplicate/authority surfaces, and
  cross-module or test-only relationships;
* every public task prompt contained a synthetic marker suffix that also
  appeared in repository text, creating lexical collisions and a benchmark
  confound.

The supported explanation for the direction reversal is therefore conditional:
accurate sparse packets can reduce exploration, while broad low-precision
packets plus missing relational paths can increase exploration. The public
study does not establish how often this occurs on natural task wording.
