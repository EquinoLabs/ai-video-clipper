# AI Video Clipper - Environment & Package Management Rules

## Python Virtual Environment
- **Path**: `backend/.venv/`
- **Interpreter**: `backend/.venv/Scripts/python.exe`
- **Pip executable**: `backend/.venv/Scripts/pip.exe`

## Policy & Invariants
1. **Never install packages globally or outside `backend/.venv`**:
   - Always run commands via `backend\.venv\Scripts\pip install ...` or `backend\.venv\Scripts\python -m pip install ...`.
2. **Always synchronize `backend/requirements.txt` / `backend/requirements-dev.txt`**:
   - Whenever any new dependency is introduced, add it immediately with appropriate version constraints to `backend/requirements.txt` (or `backend/requirements-dev.txt` for test/dev tooling).
3. **Execution**:
   - Run tests and CLI scripts using `backend\.venv\Scripts\pytest` or `backend\.venv\Scripts\python backend/app/...`.
