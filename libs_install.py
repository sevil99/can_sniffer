import os
import urllib.request

# Папка для библиотек
LIB_DIR = "static"
os.makedirs(LIB_DIR, exist_ok=True)

# Список необходимых библиотек
LIBS = {
    'jquery-3.6.0.min.js': 'https://code.jquery.com/jquery-3.6.0.min.js',
    'moment.min.js': 'https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.4/moment.min.js',
    'chart.js': 'https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js',
    'chartjs-adapter-moment.min.js': 'https://cdn.jsdelivr.net/npm/chartjs-adapter-moment@1.0.1/dist/chartjs-adapter-moment.min.js',
    'chartjs-plugin-zoom.min.js': 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@1.2.1/dist/chartjs-plugin-zoom.min.js',
'plotly-2.24.1.min.js': 'https://cdn.plot.ly/plotly-2.24.1.min.js'
}

print("📥 Проверяю и скачиваю недостающие библиотеки...")

for filename, url in LIBS.items():
    filepath = os.path.join(LIB_DIR, filename)
    
    if os.path.exists(filepath):
        print(f"   ✅ {filename} уже существует")
    else:
        print(f"   📥 Скачиваю {filename}...")
        try:
            urllib.request.urlretrieve(url, filepath)
            print(f"   ✅ {filename} скачан успешно")
        except Exception as e:
            print(f"   ❌ Ошибка скачивания {filename}: {e}")

print("\n✅ Все библиотеки готовы для оффлайн работы!")
print(f"📁 Папка: {os.path.abspath(LIB_DIR)}")