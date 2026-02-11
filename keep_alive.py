from flask import Flask
from threading import Thread
import os 

app = Flask('')

@app.route('/')
def home():
    return "I am alive!"

def run():
    raw_port = os.environ.get("PORT")
    if raw_port and raw_port.strip():
        port = int(raw_port)
    else:
        port = 10000 
        
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True 
    t.start()