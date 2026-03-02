# TailAdmin Vendor Notes

This directory stores the curated TailAdmin-free layout/component reference for CentraCortex.

- Upstream project: https://github.com/TailAdmin/free-react-tailwind-admin-dashboard
- Integration target: React 19 + Tailwind v4
- Scope in this pass: authenticated shell, navigation patterns, and reusable UI primitives.

The runtime implementation is internalized under `src/layout` and `src/components/ui` so product pages stay decoupled from raw template files.
