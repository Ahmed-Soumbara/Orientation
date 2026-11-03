# Orientation

git clone https://github.com/Ahmed-Soumbara/Orientation.git
cd Orientation
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pandas pyarrow requests httpx pytest
python data.py
uvicorn api:app --reload
et ouvrir http://127.0.0.1:8000/. 