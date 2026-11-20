.PHONY: install data run serve test lint all clean

install:
	pip install -e ".[dev]"

data:
	python -m trackflow.cli generate

run:
	python -m trackflow.cli run

serve:
	python -m trackflow.cli serve

test:
	pytest -q

lint:
	ruff check .

all: data run test

clean:
	rm -rf data/raw/*.csv data/warehouse.db
