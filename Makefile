# GEX Dashboard Makefile

.PHONY: help install build run run-browser run-desktop run-demo test clean build-run

# Default target
help:
	@echo "GEX Dashboard - Available Commands"
	@echo ""
	@echo "  make install       Install Python dependencies"
	@echo "  make build         Build desktop app (PyInstaller)"
	@echo "  make run           Run desktop app (from source)"
	@echo "  make run-browser   Run in browser (Streamlit)"
	@echo "  make run-desktop   Run built desktop app"
	@echo "  make run-demo      Run demo dashboard (no API needed)"
	@echo "  make build-run     Build and run desktop app"
	@echo "  make test          Run all tests"
	@echo "  make test-tick     Run tick accumulator tests"
	@echo "  make clean         Remove build artifacts"
	@echo ""

# Install dependencies
install:
	pip install -r requirements.txt
	pip install -r requirements-desktop.txt

# Build desktop app
build:
	pyinstaller GEX_Dashboard.spec

# Run from source (desktop window)
run:
	python desktop_app.py

# Run in browser
run-browser:
	streamlit run simple_dashboard.py

# Run built desktop app (macOS)
run-desktop:
	@if [ -d "dist/GEX_Dashboard.app" ]; then \
		open dist/GEX_Dashboard.app; \
	elif [ -f "dist/GEX_Dashboard" ]; then \
		./dist/GEX_Dashboard; \
	else \
		echo "Desktop app not built. Run 'make build' first."; \
	fi

# Run demo (no API required)
run-demo:
	streamlit run demo_dashboard.py

# Build and run
build-run: build run-desktop

# Run all tests
test:
	python -m pytest tests/ -v --ignore=tests/test_demo_dashboard.py

# Run tick accumulator tests only
test-tick:
	python -m pytest tests/test_tick_*.py -v

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
