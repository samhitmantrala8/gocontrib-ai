.PHONY: install test fixture clean describe

install:
	python -m pip install -r requirements.txt

test:
	pytest -q

fixture:
	python -m go_contributor run --fixture examples/gin_3936

describe:
	python -m go_contributor describe

clean:
	rm -rf workspace/*/.gocontrib_chroma workspace/output workspace/gin workspace/cobra workspace/validator workspace/golangci-lint
	find . -name __pycache__ -prune -exec rm -rf {} +
