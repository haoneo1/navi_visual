sync:
	rsync -ap main.py *.txt *.py *.jpg liuxy@192.168.0.33:~/projects/navi_visual

run:
	uv run main.py

venv:
	. .venv/bin/activate