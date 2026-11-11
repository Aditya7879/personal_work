# Docs

Reference documents for the NEO Agent Quality Console (`feedback-app/`).

- **`architecture-diagrams.html`** — architecture diagrams for the whole setup: high-level (system context, cloud deployment) and low-level (frontend components, backend modules, workflow sequences, BigQuery data model).
- **`feedback-workflow.html`** — the user flow of the app plus the narrative of the reporter ↔ reviewer feedback loop and how RCA works (Neo4j evidence + Sonnet).
- **`demo-admin-role.md`** — demo admin role guide.
- **`user-flow.png`** — the user flow image embedded in `feedback-workflow.html`.

The HTML pages are standalone documents: they render their diagrams with Mermaid from the jsDelivr CDN, so they need internet access but no other local files. Each diagram panel offers Fit / 100% zoom, SVG and Mermaid source downloads, and the pages print cleanly to PDF.
