import requests
import os
from datetime import datetime

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

def send_files_to_telegram():
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Не установлены BOT_TOKEN или CHAT_ID")
        return
    
    date_str = datetime.now().strftime("%Y%m%d")
    
    files_to_send = [
        f"Список_карт_номиналов_{date_str}.csv",
        f"Список_номеров_СБП_{date_str}.csv"
    ]
    
    for filename in files_to_send:
        if not os.path.exists(filename):
            print(f"⚠️ Файл не найден: {filename}")
            continue
        
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
            
            with open(filename, 'rb') as file:
                files = {'document': (filename, file)}
                data = {'chat_id': CHAT_ID, 'caption': f"📊 {filename}"}
                
                response = requests.post(url, files=files, data=data)
                
            if response.status_code == 200:
                print(f"✅ Отправлен: {filename}")
            else:
                print(f"❌ Ошибка отправки {filename}: {response.text}")
                
        except Exception as e:
            print(f"❌ Ошибка при отправке {filename}: {e}")

if __name__ == "__main__":
    send_files_to_telegram()
