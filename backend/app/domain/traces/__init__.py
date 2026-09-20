"""Perfboard trace routing — maze router, rip-up, scoring, validation.

This package is the perfboard analogue of the breadboard's ``app.domain.route``
module family. It contains:

- :mod:`maze`    — Lee-style BFS maze router on the hole graph
- :mod:`route`   — public :func:`route` driver: pick net order, maze route each
- :mod:`cost`    — per-trace cost function (length, crossings, vias, congestion)
- :mod:`score`   — :class:`LayoutScore` assembly for trace layouts
- :mod:`validate`— pure validator that emits :data:`app.domain.diagnostics`
- :mod:`solve`   — top-level :func:`solve` pipeline (place → trace-route → validate → score)

Domain-only: this package imports nothing from Sanic, SQLAlchemy, redis, boto3
or ``app.settings``.
"""
