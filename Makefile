.PHONY: setup demo dev doctor run export test build
setup:   ; cd backend && pip install -r requirements.txt && cd ../frontend && npm install
demo:    ; cd backend && python -m finn demo
doctor:  ; cd backend && python -m finn doctor
run:     ; cd backend && python -m finn run
export:  ; cd backend && python -m finn export
test:    ; cd backend && python -m pytest -q
build:   ; cd frontend && npm run build
dev:     ; (cd backend && uvicorn finn.api:app --reload --port 8000 &) && cd frontend && VITE_API_URL=http://localhost:8000 npm run dev
