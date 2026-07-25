# ADR-0005: Service Registry

**Status:** Accepted

**Date:** 2026-07-25

---

# Context

QPX_ALPHA now contains several independent platform services.

Examples include:

- Configuration
- Logging
- Event Bus
- Health

As additional services are introduced, manually importing and initializing
them inside the launcher would create unnecessary coupling.

---

# Decision

A Service Registry shall manage platform services.

The launcher initializes the registry.

The registry initializes services.

Each service owns its own startup and shutdown behavior.

---

# Responsibilities

The Service Registry shall:

- Register services
- Initialize services
- Report startup status
- Shutdown services cleanly
- Expose service health

---

# Benefits

- Loose coupling
- Easier testing
- Predictable startup order
- Cleaner launcher
- Extensible architecture

---

# Future Services

Examples include:

- Scheduler
- Database
- AI Manager
- Market Providers
- Portfolio Manager
- Strategy Manager

These services will integrate through the registry without requiring changes
to the launcher.

---

# Engineering Rule

The launcher coordinates platform startup.

Individual services manage their own implementation details.

---

# Notes

This ADR establishes the lifecycle management model for QPX_ALPHA.
