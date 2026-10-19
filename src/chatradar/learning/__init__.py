"""Corpus statistics that propose lexicon candidates (ADR-0003). Statistics only, no AI.

Everything here is a pure function or a plain in-memory object; the I/O lives in
`chatradar.services.learning`. Mining never decides: it produces CANDIDATE terms with
numbers (occurrences, distinct chats, distinct authors, a log-odds z-score) and up to a few
example message keys, and a human accepts or rejects them.

Memory. One pass over the corpus keeps, per generator, a counter of the n-grams of the
target class (with sets of author and chat ids and a few example keys) and a plain counter of
the background class. Memory grows with the number of distinct n-grams, roughly linear in
the corpus; it is comfortable for hundreds of thousands of short chat messages. A larger
corpus needs pruning of rare background n-grams or a second pass (see the backlog).

No stemming. Terms are folded surface forms (`pipeline.lexicons.fold`), so inflections of one
word are separate candidates ("lichku", "lichke"); a human merges them by accepting the
useful ones. Stemming or lemmatization is a recorded next step.
"""
