.PHONY: clean build publish

version=$(cat setup.py | sed -n 's/version=\(.*\),/\1/p')

build: clean
	python -m pip install --upgrade --quiet setuptools wheel twine
	python setup.py --quiet sdist bdist_wheel

publish: build
	python -m twine check dist/*
	python -m twine upload dist/*

clean:
	rm -r build dist *.egg-info || true
