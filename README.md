# Mudlogging-Dashboard-Demo

## Usage Guideline

1. First of all make sure about the project directory and folders (all assets should be in `data` folder and make sure that `requirements.txt` is exist).

2. Open the command prompt (or VSCode Terminal (cmd)) in the project directory and type below command:
    `pip install -r requirements.txt`

3. After installing all libraries type below command in Terminal(cmd):
    `streamlit run app.py`
    `python -m compileall .`

    you should se something like this (which is showing that the project is running in local host):
    
   
    `You can now view your Streamlit app in your browser.`
    `Local URL: http://localhost:8501`
    `Network URL: http://192.168.100.7:8501`

your_project/
│
├─ app.py
├─ config.py
├─ data_loader.py
├─ helpers.py
├─ chart_builder.py
├─ sidebar.py
└─ data/
   ├─ catalog.json
   └─ *.parquet