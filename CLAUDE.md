<!-- codegraph:start -->
## Using CodeGraph

This project has a CodeGraph index at `.codegraph/`. Prefer the
codegraph MCP tools over grep/glob/Read for code exploration.

- For "how does X work", flow questions ("how does X reach Y"),
  or surveying an area — call `codegraph_explore` FIRST. One call
  returns the relevant symbols' source, call paths, and blast
  radius. Name specific symbols/files in the query.
- Trust codegraph results. Do NOT re-verify with grep.
- If a response includes a ⚠️ staleness banner naming a file,
  Read that file directly — the graph is briefly behind an edit.
- Fall back to Read/Grep only when codegraph returns no results
  or explicitly guides you to.

Do not delegate exploration to file-reading sub-agents before
querying codegraph — sub-agents don't see this guidance and will
default to grep.
<!-- codegraph:end -->