# MkDocs + OKF Knowledge Bundle (Optional)

**Load when:** setting up mkdocs to render a directory that is also a live
OKF-managed knowledge bundle (the `okf` CLI or an `okf-agent-memory` MCP
server), or debugging a wikilink/frontmatter clash between the two.

## When This Applies

This is **not part of the template's default setup.** It is an optional pattern
for projects that adopt both:

- [mkdocs](https://www.mkdocs.org/) (optionally with `mkdocs-material`) to
  publish a docs site, and
- an OKF (Open Knowledge Format) knowledge bundle — `.md` concept files with
  YAML frontmatter, managed by the `okf` CLI or an `okf-agent-memory` MCP server
  — as agent-readable/writable memory.

Adopting this pattern means the same directory of markdown files is
simultaneously live data for OKF tooling and static-site input for mkdocs. It
adds two new dependencies (`mkdocs`, `mkdocs-material`) and is only worth adding
if the project actually wants a rendered, browsable view of its knowledge bundle
— read
[contribution-discipline.md](contribution-discipline.md#unnecessary-third-party-dependencies)
before wiring this into `pixi.toml`.

## Example Wiring (Add Only If Adopting)

```toml
[environments]
docs = { features = ["docs"], solve-group = "default" }

[feature.docs.dependencies]
mkdocs = "*"
mkdocs-material = "*"

[feature.docs.tasks]
docs-build = { cmd = "mkdocs build", description = "Build the knowledge-bundle docs site" }
docs-serve = { cmd = "mkdocs serve", description = "Serve the knowledge-bundle docs site locally" }
```

```yaml
# mkdocs.yml
site_name: <project> knowledge
docs_dir: docs/knowledge # point this at the OKF bundle root
site_dir: site

theme:
  name: material

markdown_extensions:
  - wikilinks:
      base_url: /<section>/ # required — see gotcha #1 below
      end_url: /
```

## Gotchas Found In Practice

1. **The `wikilinks` extension needs an explicit `base_url`/`end_url`.** This is
   core Python-Markdown's `wikilinks` extension (not a `pymdownx` one), and it
   has no awareness of mkdocs' directory nesting. A bare `[[concept-name]]`
   reference resolves relative to `base_url`, not to the linking page's own
   folder — set `base_url` to match where your bundle's files actually live
   under `docs_dir`, or links will 404.

2. **`okf relate` links and hand-written wikilinks are different mechanisms.**
   `okf relate` writes plain relative markdown links (`[Title](slug.md)`) under
   a "Related Concepts" heading — those work with zero mkdocs configuration. A
   hand-written `[[slug]]` wikilink is a second, independent link style that
   depends on the `wikilinks` extension and its `base_url`. Fixing one does not
   fix the other.

3. **YAML frontmatter is dual-consumed.** OKF reads `type`, `title`,
   `description`, and `generated` from the frontmatter fence. mkdocs strips that
   same fence from the rendered body but reuses `title:` for the page's
   `<title>` tag. An `okf update` that changes a concept's title silently
   changes the rendered page title too — there is no way to give OKF and mkdocs
   different titles for the same file.

4. **`index.md` is dual-purpose per directory.** OKF auto-generates and silently
   overwrites each directory's `index.md`/`log.md` on every
   `okf create`/`okf relate` call. mkdocs treats that same `index.md` as the
   directory's nav landing page. Never hand-edit an OKF-managed `index.md`
   expecting mkdocs-specific content to survive — it will be clobbered on the
   next OKF write.

5. **Literal `[[double brackets]]` in a `description:` field leak into rendered
   output.** OKF copies a concept's `description` verbatim into the
   auto-generated `index.md` summary line. If that description contains literal
   `[[...]]` text not meant as a link, the `wikilinks` extension still parses it
   as a link reference when mkdocs renders that `index.md` — and it is usually
   broken, since the bracketed text is rarely a real concept slug. Avoid double
   brackets in `description:` fields entirely if the bundle is also rendered by
   mkdocs.

6. **Each project-local bundle needs its own MCP server entry.** An
   `okf-agent-memory` MCP server is sandboxed to one bundle root at launch
   (`okf mcp <root>`). If broader OKF servers are already configured elsewhere
   (personal or team-wide), a project-local bundle (e.g. `docs/knowledge`) needs
   a separate, additional server entry pointed at that path — it is not
   reachable through a server rooted elsewhere.

## Related

- [contribution-discipline.md](contribution-discipline.md) — read before adding
  the `docs` feature to `pixi.toml`; new dependencies need justification.
- [pixi-environments.md](pixi-environments.md) — general pattern for adding an
  optional feature/environment.
