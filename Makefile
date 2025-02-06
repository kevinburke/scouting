install:
	pip install --upgrade virtualenv pip
	virtualenv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt

clean:
	rm -rf venv
