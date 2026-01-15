import requests
from datetime import datetime
import os

SPREADSHEET_ID = "14x5PZnq9AX8CcRW1cl5hyne0IndtNh0L"
SHEETS = {
    "Список_карт_номиналов": "1674053030",
    "Список_номеров_СБП": "1789244637"
}

def download_all_sheets():
    date_str = datetime.now().strftime("%Y%m%d")
    print(f"📅 Дата: {date_str}")
    
    for name, gid in SHEETS.items():
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            
            filename = f"{name}_{date_str}.csv"
            with open(filename, 'wb') as f:
                f.write(response.content)
            
            print(f"✅ Скачан: {filename} ({len(response.content)} байт)")
            
        except Exception as e:
            print(f"❌ Ошибка при скачивании {name}: {e}")
            return False
    
    return True

if __name__ == "__main__":
    download_all_sheets()
