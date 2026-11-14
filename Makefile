.PHONY: install run test bench smoke catalog demos
install: ; pip install -r requirements-dev.txt
run: ; uvicorn backend.main:app --reload --port 8000
test: ; pytest -q
bench: ; python scripts/benchmark.py
smoke: ; python scripts/live_smoke_test.py
catalog: ; python scripts/build_catalog.py
demos: ; python scripts/build_demos.py
