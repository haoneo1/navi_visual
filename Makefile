sync:
	rsync -ap main.py *.txt *.py *.jpg liuxy@192.168.0.33:~/projects/navi_visual

run:
	uv run main.py

review:
	uv run review_app.py

venv:
	. .venv/bin/activate