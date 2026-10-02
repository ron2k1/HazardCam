# Event-day agent output directory

This directory intentionally contains **no agent implementation** in the prebuild package.

On event day, the fresh Claude/Ultracode session creates the actual OpenClaw agent files here from the tested interfaces, acceptance tests, and requirements in this repo.

Do not place prewritten agent source here before the event. The event-day scripts verify that executable agent implementation files are created after the event-day start marker.
