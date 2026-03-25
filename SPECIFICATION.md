# Technical Specification: ClawTeam Web Dashboard & API

## Overview
The goal is to provide a real-time web-based dashboard for monitoring ClawTeam agent swarms. This includes a landing page and a RESTful API for team management, task tracking, and inter-agent communication.

## Backend Architecture (BoardHandler)
The backend is a lightweight HTTP server implemented in `clawteam/board/server.py` using Python's `http.server` module.

### REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/overview` | Returns a list of all active teams. |
| GET    | `/api/team/{team_name}` | Returns a full snapshot of the specified team (members, tasks, messages). |
| GET    | `/api/events/{team_name}` | Server-Sent Events (SSE) stream for real-time team updates. |
| POST   | `/api/teams` | Creates a new team. |
| POST   | `/api/teams/{team_name}/tasks` | Creates a new task within a team. |
| PATCH  | `/api/teams/{team_name}/tasks/{task_id}` | Updates an existing task (status, owner, etc.). |
| POST   | `/api/teams/{team_name}/messages` | Sends a message to an agent or broadcasts to the team. |

### Real-time Synchronization
- **SSE Stream**: The `/api/events/{team_name}` endpoint provides a continuous stream of team snapshots.
- **Caching**: `TeamSnapshotCache` with a TTL (default 2s) is used to prevent over-collecting from the filesystem during high-frequency SSE requests.

## Frontend Architecture (Landing Page)
The frontend is built using React and Vite, located in the `website/` directory.

### Key Components
- **Hero Section**: High-level value proposition and quick-start guide.
- **Terminal Mockup**: Visual representation of CLI usage.
- **Globe Visualization**: Animated 3D globe showing agent connectivity.
- **Feature Cards**: Summary of core capabilities.
- **Workflow Steps**: Three-step guide to starting a swarm.

## Testing Strategy
- **Unit Tests**: Implement comprehensive unit tests for `BoardHandler` in `tests/test_api.py`.
- **Integration Tests**: Verify end-to-end flows from API calls to filesystem changes.
- **UI Validation**: Ensure the landing page is responsive and visually consistent.

## Task Breakdown

### Phase 1: API Core Implementation (backend-dev)
- [x] Implement `_handle_create_team`
- [x] Implement `_handle_create_task`
- [x] Implement `_handle_update_task`
- [x] Implement `_handle_send_message`
- [ ] Implement robust error handling and validation for all endpoints

### Phase 2: Landing Page & UI (frontend-dev)
- [x] Design and implement Hero section
- [x] Build Terminal Mockup component
- [x] Implement animated Globe visualization
- [ ] Connect dashboard to real API endpoints (currently mocked)

### Phase 3: Quality Assurance (qa-engineer)
- [ ] Write unit tests for API endpoints in `tests/test_api.py`
- [ ] Perform integration testing for task dependency auto-unblocking
- [ ] Verify message delivery across different transport backends

### Phase 4: DevOps & CI/CD (devops)
- [x] Set up basic GitHub Actions workflow for linting and testing
- [ ] Add deployment pipeline for the landing page
- [ ] Configure performance monitoring for the board server
